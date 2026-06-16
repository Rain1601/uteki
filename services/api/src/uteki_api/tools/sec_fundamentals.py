"""sec_fundamentals — canonical SEC EDGAR fundamentals via OpenBB sidecar.

Why this exists alongside the existing ``financials`` tool: our hand-rolled
``financials`` calls yfinance, which is convenient but inherits whatever
yfinance does with restatement reconciliation and as-reported vs adjusted
figures. The SEC route is the original Form 10-K/10-Q filings — slower
but authoritative, and the right thing to cite when the agent's claim
hinges on exact reported numbers.

Endpoints (all SEC-backed, no key required):

  income          — income statement (Form 10-K / 10-Q)
  balance         — balance sheet
  cash            — cash-flow statement
  income_growth   — period-over-period growth derived from income
  balance_growth  — same for balance
  cash_growth     — same for cash
  filings         — Form filings index (10-K / 10-Q / 8-K / DEF 14A / Form 4 ...)

The tool stays narrow on purpose — management compensation, MD&A, and
13F retrieval each have a different shape and would balloon the JSON
schema if folded in here. Add them as additional tools if needed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from uteki_api.tools.base import Tool, ToolResult
from uteki_api.tools.openbb_client import OpenBBSidecarError, default_openbb_client

_KIND_PATH: dict[str, str] = {
    "income": "/equity/fundamental/income",
    "balance": "/equity/fundamental/balance",
    "cash": "/equity/fundamental/cash",
    "income_growth": "/equity/fundamental/income_growth",
    "balance_growth": "/equity/fundamental/balance_growth",
    "cash_growth": "/equity/fundamental/cash_growth",
    "filings": "/equity/fundamental/filings",
}


class SECFundamentalsTool(Tool):
    name = "sec_fundamentals"
    description = (
        "拉取 SEC EDGAR 原始财报数据：income / balance / cash 三大表 + "
        "income_growth / balance_growth / cash_growth 三类同比增速 + filings 表。"
        "通过 OpenBB sidecar，provider=sec，无 key。"
        "比 yfinance 版 financials 更权威，适合给关键论点上 SEC 直接引用。"
    )
    risk_level = "low"
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": list(_KIND_PATH.keys()),
                "description": "Which statement / index to pull.",
            },
            "symbol": {
                "type": "string",
                "description": "US ticker (SEC filings are US-only). E.g. AAPL, MSFT.",
            },
            "period": {
                "type": "string",
                "enum": ["annual", "quarter"],
                "default": "annual",
                "description": "Reporting period. Filings ignore this.",
            },
            "limit": {
                "type": "integer",
                "default": 8,
                "minimum": 1,
                "maximum": 40,
                "description": "Cap on rows / filings returned.",
            },
        },
        "required": ["kind", "symbol"],
    }

    def __init__(self, client=None) -> None:
        self._client = client or default_openbb_client

    async def run(self, **kwargs: Any) -> ToolResult:
        kind = (kwargs.get("kind") or "").strip()
        if kind not in _KIND_PATH:
            return ToolResult(
                ok=False,
                error=f"unknown kind: {kind!r}; pick one of {list(_KIND_PATH)}",
            )
        symbol = (kwargs.get("symbol") or "").strip().upper()
        if not symbol:
            return ToolResult(ok=False, error="symbol is required")
        params: dict[str, Any] = {
            "provider": "sec",
            "symbol": symbol,
            "limit": max(1, min(int(kwargs.get("limit") or 8), 40)),
        }
        if kind != "filings":
            period = (kwargs.get("period") or "annual").strip()
            if period not in ("annual", "quarter"):
                period = "annual"
            params["period"] = period

        path = _KIND_PATH[kind]
        try:
            envelope = await self._client.get(path, params=params)
        except OpenBBSidecarError as e:
            return ToolResult(
                ok=False,
                summary=f"SEC {kind} ({symbol}) sidecar 调用失败",
                error=str(e),
            )

        rows = envelope.get("results") or []
        fetched_at = datetime.now(UTC).isoformat()
        latest_date = rows[0].get("period_ending") or rows[0].get("filing_date") if rows else None
        summary = (
            f"SEC {kind} ({symbol})：{len(rows)} rows"
            + (f"，latest={latest_date}" if latest_date else "")
        )
        sources = [
            {
                "key": f"sec:{kind}:{symbol}",
                "value": {"kind": kind, "symbol": symbol, "rows": len(rows)},
                "source_type": "sec_fundamentals",
                "source_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={symbol}",
                "publisher": "SEC EDGAR",
                "fetched_at": fetched_at,
                "confidence": "high",
                "excerpt": summary,
            }
        ]
        return ToolResult(
            ok=True,
            summary=summary,
            data={"kind": kind, "symbol": symbol, "rows": rows},
            sources=sources,
        )
