"""macro_rates — central-bank policy + benchmark rates via OpenBB sidecar.

One tool covers what would otherwise be 5+ separate tools cluttering the LLM
function-call namespace. The ``source`` enum selects the underlying OpenBB
endpoint + provider:

  fed_effr          → /fixedincome/rate/effr        (federal_reserve)
  fed_sofr          → /fixedincome/rate/sofr        (federal_reserve)
  fed_treasury      → /fixedincome/government/treasury_rates (federal_reserve)
  fed_yield_curve   → /fixedincome/government/yield_curve    (federal_reserve)
  ecb_policy_rate   → /fixedincome/rate/ecb         (ecb)

These providers don't require keys — both the Federal Reserve and ECB
expose their data freely. (FRED in macro_fred.py needs a key because it's a
catalog with rate-limiting on lookups; the Fed/ECB provider plugins scrape
the static daily/weekly data feeds.)

Yield-curve queries return a snapshot keyed by tenor (e.g. 1m/3m/.../30y),
not a time series — handled separately below.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from uteki_api.tools.base import Tool, ToolResult
from uteki_api.tools.openbb_client import OpenBBSidecarError, default_openbb_client

_SOURCE_SPEC: dict[str, dict[str, Any]] = {
    "fed_effr": {
        "path": "/fixedincome/rate/effr",
        "provider": "federal_reserve",
        "label": "Federal Reserve · Effective Funds Rate",
        "url": "https://www.federalreserve.gov/datadownload/Choose.aspx?rel=H15",
        "value_key": "rate",
    },
    "fed_sofr": {
        "path": "/fixedincome/rate/sofr",
        "provider": "federal_reserve",
        "label": "Federal Reserve · SOFR",
        "url": "https://www.newyorkfed.org/markets/reference-rates/sofr",
        "value_key": "rate",
    },
    "fed_treasury": {
        "path": "/fixedincome/government/treasury_rates",
        "provider": "federal_reserve",
        "label": "Federal Reserve · Treasury Par Rates",
        "url": "https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics",
        "value_key": None,  # multi-tenor snapshot — handled specially
    },
    "fed_yield_curve": {
        "path": "/fixedincome/government/yield_curve",
        "provider": "federal_reserve",
        "label": "Federal Reserve · Treasury Yield Curve",
        "url": "https://www.federalreserve.gov/datadownload/Choose.aspx?rel=H15",
        "value_key": None,
    },
    "ecb_policy_rate": {
        # OpenBB exposes ECB rates only through the FRED-backed endpoint —
        # the openbb-ecb provider plugin lives at a different route. FRED
        # republishes ECB rates; the value is identical.
        "path": "/fixedincome/rate/ecb",
        "provider": "fred",
        "label": "ECB · Key Policy Rate (via FRED)",
        "url": "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/key_ecb_interest_rates/html/index.en.html",
        "value_key": "rate",
    },
}


class MacroRatesTool(Tool):
    name = "macro_rates"
    description = (
        "拉取央行政策利率 + 基准利率（Fed EFFR/SOFR/Treasury/Yield Curve，"
        "ECB Policy Rate）。无需 key，通过 OpenBB sidecar。"
        "适合判断货币环境、贴现率、相对估值时机。"
    )
    risk_level = "low"
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "enum": list(_SOURCE_SPEC.keys()),
                "description": "Which rate series. fed_yield_curve / fed_treasury return a multi-tenor snapshot; the rest are time series.",
            },
            "start_date": {
                "type": "string",
                "description": "ISO date YYYY-MM-DD. Default = end_date − ~1y.",
            },
            "end_date": {
                "type": "string",
                "description": "ISO date YYYY-MM-DD. Default = today (or as_of).",
            },
            "limit": {
                "type": "integer",
                "default": 30,
                "minimum": 1,
                "maximum": 365,
                "description": "Newest-first cap on time-series rows.",
            },
        },
        "required": ["source"],
    }

    def __init__(self, client=None) -> None:
        self._client = client or default_openbb_client

    async def run(self, **kwargs: Any) -> ToolResult:
        source = (kwargs.get("source") or "").strip()
        if source not in _SOURCE_SPEC:
            return ToolResult(
                ok=False,
                error=f"unknown source: {source!r}; pick one of {list(_SOURCE_SPEC)}",
            )
        spec = _SOURCE_SPEC[source]
        limit = max(1, min(int(kwargs.get("limit") or 30), 365))

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
            # ~1y window — plenty for time-series sources, harmless for
            # snapshot sources (sidecar ignores start_date when irrelevant).
            start_date = (anchor - timedelta(days=400)).isoformat()

        params = {
            "provider": spec["provider"],
            "start_date": start_date,
            "end_date": end_date,
        }
        try:
            envelope = await self._client.get(spec["path"], params=params)
        except OpenBBSidecarError as e:
            return ToolResult(
                ok=False,
                summary=f"{spec['label']} sidecar 调用失败",
                error=str(e),
            )

        raw = envelope.get("results") or []
        fetched_at = datetime.now(UTC).isoformat()

        if spec["value_key"] is not None:
            # Time-series flavor: each row {"date": ..., "rate": ...}. Sort
            # newest-first and slice — OpenBB returns oldest-first.
            sorted_rows = sorted(raw, key=lambda r: r.get("date") or "", reverse=True)[:limit]
            rows: list[dict[str, Any]] = []
            for r in sorted_rows:
                date = r.get("date")
                value = r.get(spec["value_key"]) or r.get("value")
                if date is None or value is None:
                    continue
                rows.append({"date": date, "value": value})
            latest = rows[0].get("value") if rows else None
            data = {"source": source, "observations": rows, "as_of": as_of}
            summary = f"{spec['label']}：{len(rows)} obs" + (
                f"，最新 {latest}" if latest is not None else ""
            )
        else:
            # Snapshot flavor (treasury rates / yield curve): the row already
            # contains all tenors. Pass through and let the LLM consume.
            data = {"source": source, "snapshot": raw, "as_of": as_of}
            summary = f"{spec['label']}：{len(raw)} 行 (snapshot)"

        sources = [
            {
                "key": f"macro_rates:{source}",
                "value": {"source": source, "rows": len(raw)},
                "source_type": "macro_rates",
                "source_url": spec["url"],
                "publisher": spec["label"].split(" · ")[0],
                "fetched_at": fetched_at,
                "confidence": "high",
                "excerpt": summary,
            }
        ]
        return ToolResult(ok=True, summary=summary, data=data, sources=sources)
