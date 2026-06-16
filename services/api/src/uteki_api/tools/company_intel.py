"""company_intel — FMP-backed company catalysts via the OpenBB sidecar.

One tool, one ``kind`` enum, six categories of data the equity-research
agent needs but has historically had to guess at:

  earnings_calendar       — upcoming + recent earnings releases by symbol or window
  analyst_estimates       — historical consensus EPS/revenue beats and misses
  forward_eps             — forward EPS estimate timeseries
  price_target            — consensus + per-analyst target prices
  insider_trading         — Form 4 transactions for a symbol
  institutional_holdings  — top institutional holders + 13F filings

Provider is FMP across the board; their free tier comfortably covers US +
most major international tickers. The OpenBB shape is uniform enough that
unrolling to six tools (one per kind) would just bloat the LLM function-
call namespace — one tool with a clear enum is easier for the model to
choose correctly.

If a kind is uncalled-for in a given run, the LLM simply doesn't invoke
it; there's no per-call overhead from the broad surface.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from uteki_api.tools.base import Tool, ToolResult
from uteki_api.tools.openbb_client import OpenBBSidecarError, default_openbb_client

# Each entry maps the LLM-facing "kind" to a sidecar route + the parameter
# names the LLM is allowed to pass through. Anything not in ``passthrough``
# is dropped before hitting the sidecar — defense against the model
# inventing parameters that confuse the upstream router.
_KIND_SPEC: dict[str, dict[str, Any]] = {
    "earnings_calendar": {
        "path": "/equity/calendar/earnings",
        "provider": "fmp",
        "label": "FMP · Earnings Calendar",
        "url": "https://site.financialmodelingprep.com/developer/docs",
        "passthrough": ("symbol", "start_date", "end_date"),
        "needs_symbol": False,
    },
    "analyst_estimates": {
        "path": "/equity/estimates/historical",
        "provider": "fmp",
        "label": "FMP · Historical Analyst Estimates",
        "url": "https://site.financialmodelingprep.com/developer/docs",
        "passthrough": ("symbol", "period", "limit"),
        "needs_symbol": True,
    },
    "forward_eps": {
        "path": "/equity/estimates/forward_eps",
        "provider": "fmp",
        "label": "FMP · Forward EPS",
        "url": "https://site.financialmodelingprep.com/developer/docs",
        "passthrough": ("symbol", "limit"),
        "needs_symbol": True,
    },
    "price_target": {
        "path": "/equity/estimates/price_target",
        "provider": "fmp",
        "label": "FMP · Analyst Price Targets",
        "url": "https://site.financialmodelingprep.com/developer/docs",
        "passthrough": ("symbol", "limit"),
        "needs_symbol": True,
    },
    "insider_trading": {
        "path": "/equity/ownership/insider_trading",
        "provider": "fmp",
        "label": "FMP · Insider Trading (Form 4)",
        "url": "https://site.financialmodelingprep.com/developer/docs",
        "passthrough": ("symbol", "limit"),
        "needs_symbol": True,
    },
    "institutional_holdings": {
        "path": "/equity/ownership/institutional",
        "provider": "fmp",
        "label": "FMP · Institutional Holdings",
        "url": "https://site.financialmodelingprep.com/developer/docs",
        "passthrough": ("symbol",),
        "needs_symbol": True,
    },
}


class CompanyIntelTool(Tool):
    name = "company_intel"
    description = (
        "拉取公司层面的催化剂数据：earnings_calendar / analyst_estimates / "
        "forward_eps / price_target / insider_trading / institutional_holdings。"
        "通过 OpenBB sidecar + FMP provider。"
        "适合判断业绩催化、共识 vs 现实、机构动向、内部人信号。"
    )
    risk_level = "low"
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": list(_KIND_SPEC.keys()),
                "description": "Which dataset to pull. See tool description for what each one is for.",
            },
            "symbol": {
                "type": "string",
                "description": "Ticker (US: AAPL · TW: 2330.TW · HK: 0700.HK). Required for everything except earnings_calendar.",
            },
            "start_date": {
                "type": "string",
                "description": "ISO date YYYY-MM-DD. Used by earnings_calendar.",
            },
            "end_date": {
                "type": "string",
                "description": "ISO date YYYY-MM-DD. Used by earnings_calendar.",
            },
            "period": {
                "type": "string",
                "enum": ["annual", "quarter"],
                "default": "quarter",
                "description": "Period granularity for analyst_estimates.",
            },
            "limit": {
                "type": "integer",
                "default": 12,
                "minimum": 1,
                "maximum": 100,
                "description": "Cap on rows returned.",
            },
        },
        "required": ["kind"],
    }

    def __init__(self, client=None) -> None:
        self._client = client or default_openbb_client

    async def run(self, **kwargs: Any) -> ToolResult:
        kind = (kwargs.get("kind") or "").strip()
        if kind not in _KIND_SPEC:
            return ToolResult(
                ok=False,
                error=f"unknown kind: {kind!r}; pick one of {list(_KIND_SPEC)}",
            )
        spec = _KIND_SPEC[kind]
        symbol = (kwargs.get("symbol") or "").strip().upper() or None
        if spec["needs_symbol"] and not symbol:
            return ToolResult(ok=False, error=f"symbol is required for {kind}")

        params: dict[str, Any] = {"provider": spec["provider"]}
        for key in spec["passthrough"]:
            value = kwargs.get(key)
            if key == "symbol" and value is not None:
                value = str(value).upper()
            if value is not None:
                params[key] = value
        # as_of → end_date for time-windowed queries.
        as_of = kwargs.get("as_of")
        if as_of and "end_date" in spec["passthrough"] and "end_date" not in params:
            params["end_date"] = str(as_of)

        try:
            envelope = await self._client.get(spec["path"], params=params)
        except OpenBBSidecarError as e:
            return ToolResult(
                ok=False,
                summary=f"{spec['label']} sidecar 调用失败",
                error=str(e),
            )

        rows = envelope.get("results") or []
        fetched_at = datetime.now(UTC).isoformat()
        head_label = f"{symbol or '*'}"
        summary = f"{spec['label']} ({head_label})：{len(rows)} rows"
        sources = [
            {
                "key": f"company_intel:{kind}:{symbol or '*'}",
                "value": {"kind": kind, "symbol": symbol, "rows": len(rows)},
                "source_type": "company_intel",
                "source_url": spec["url"],
                "publisher": spec["label"].split(" · ")[0],
                "fetched_at": fetched_at,
                "confidence": "medium",
                "excerpt": summary,
            }
        ]
        return ToolResult(
            ok=True,
            summary=summary,
            data={"kind": kind, "symbol": symbol, "rows": rows, "as_of": as_of},
            sources=sources,
        )
