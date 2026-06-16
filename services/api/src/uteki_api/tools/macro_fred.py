"""macro_fred — pull a FRED economic series via the OpenBB sidecar.

Why this is a separate tool (vs piggy-backing on financials/market_quote):
the macro track is a different domain — interest rates, inflation, yield
curves, FX — and the skill prompts treat it as such. Keeping it discrete
also keeps the JSON Schema small and the LLM grounded on "this is for
rates, not company earnings".

Series IDs follow FRED's catalog (https://fred.stlouisfed.org). The most
load-bearing ones for an equity research agent:

- DGS10 / DGS2          — 10y / 2y treasury constant-maturity yields
- T10Y2Y                — 10y minus 2y spread (recession bellwether)
- CPIAUCSL              — headline CPI
- CPILFESL              — core CPI
- FEDFUNDS / DFEDTARU   — fed funds effective / upper target
- UNRATE                — unemployment rate
- SOFR                  — secured overnight financing rate

The sidecar normalizes provider responses into the same OBBject envelope
shape, so swapping FRED for an alternate provider (e.g. econdb) would not
change this tool — only the ``provider`` query param.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from uteki_api.tools.base import Tool, ToolResult
from uteki_api.tools.openbb_client import OpenBBSidecarError, default_openbb_client


class MacroFREDTool(Tool):
    name = "macro_fred"
    description = (
        "拉取 FRED 宏观经济序列（利率、通胀、就业、收益率曲线、SOFR 等），"
        "通过 OpenBB sidecar 代理。常用 series_id：DGS10 / DGS2 / T10Y2Y / "
        "CPIAUCSL / CPILFESL / FEDFUNDS / UNRATE / SOFR。"
    )
    risk_level = "low"
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "series_id": {
                "type": "string",
                "description": "FRED series identifier, e.g. DGS10 for the 10-year treasury yield.",
            },
            "start_date": {
                "type": "string",
                "description": "ISO date (YYYY-MM-DD). Inclusive lower bound.",
            },
            "end_date": {
                "type": "string",
                "description": "ISO date (YYYY-MM-DD). Inclusive upper bound.",
            },
            "limit": {
                "type": "integer",
                "default": 60,
                "minimum": 1,
                "maximum": 365,
                "description": "Max observations returned (newest-first slice).",
            },
        },
        "required": ["series_id"],
    }

    def __init__(self, client=None) -> None:
        self._client = client or default_openbb_client

    async def run(self, **kwargs: Any) -> ToolResult:
        series_id = (kwargs.get("series_id") or "").strip().upper()
        if not series_id:
            return ToolResult(ok=False, error="series_id is required")
        limit = max(1, min(int(kwargs.get("limit") or 60), 365))
        # FRED's ``limit`` is start-bounded — without ``start_date`` set you'd
        # get the oldest N observations (DGS10 starts in 1962). Default to a
        # one-year lookback so "give me DGS10 limit=60" returns the last ~60
        # daily prints, not 1962 history. ``limit`` per FRED's daily granularity
        # roughly matches a calendar window via the 1.6× business-day fudge.
        end_date = kwargs.get("end_date")
        start_date = kwargs.get("start_date")
        as_of = kwargs.get("as_of")
        if as_of and not end_date:
            end_date = str(as_of)
        if not start_date:
            anchor = (
                datetime.fromisoformat(end_date).date()
                if end_date
                else datetime.now(UTC).date()
            )
            start_date = (anchor - timedelta(days=int(limit * 1.6) + 14)).isoformat()
        params = {
            "symbol": series_id,
            "start_date": start_date,
            "end_date": end_date,
            "provider": "fred",
            "limit": limit,
        }

        try:
            envelope = await self._client.get("/economy/fred_series", params=params)
        except OpenBBSidecarError as e:
            return ToolResult(
                ok=False,
                summary=f"FRED sidecar 调用失败：{series_id}",
                error=str(e),
            )

        # FRED's sidecar shape: results=[{"date": ..., "<SERIES_ID>": value}, ...]
        # OpenBB keys the numeric value by the series_id rather than a generic
        # "value" field — handle both forms defensively so a provider change
        # (econdb fallback, etc.) doesn't break the tool.
        raw = envelope.get("results") or []
        # Sort newest-first then slice — FRED returns oldest-first by default
        # and ``limit`` caps from the start, not the end.
        raw_sorted = sorted(raw, key=lambda r: r.get("date") or "", reverse=True)
        sliced = raw_sorted[:limit]
        rows: list[dict[str, Any]] = []
        for r in sliced:
            date = r.get("date")
            value = r.get(series_id, r.get("value"))
            if date is None or value is None:
                continue
            rows.append({"date": date, "value": value})
        fetched_at = datetime.now(UTC).isoformat()
        latest_value = rows[0].get("value") if rows else None
        summary = (
            f"FRED {series_id}：{len(rows)} obs"
            + (f"，最新 {latest_value}" if latest_value is not None else "")
        )
        sources = [
            {
                "key": f"fred:{series_id}",
                "value": {"series_id": series_id, "observations": len(rows)},
                "source_type": "macro_fred",
                "source_url": f"https://fred.stlouisfed.org/series/{series_id}",
                "publisher": "FRED · St. Louis Fed",
                "fetched_at": fetched_at,
                "confidence": "high",
                "excerpt": f"latest={latest_value}" if latest_value is not None else "",
            }
        ]
        return ToolResult(
            ok=True,
            summary=summary,
            data={"series_id": series_id, "observations": rows, "as_of": as_of},
            sources=sources,
        )
