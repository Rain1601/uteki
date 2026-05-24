"""Market quote tool — mock implementation backed by curated fixtures.

Known tickers (300750.SZ / AAPL / NVDA / ...) return realistic snapshots from
``_fixtures.QUOTE_FIXTURES``; unknown tickers fall back to deterministic-random
data seeded on the symbol so the same ticker yields stable values per session.

Future: plug into akshare / Tushare / WindAPI / Bloomberg by replacing the
``quote_for(symbol)`` call below.
"""

from __future__ import annotations

from typing import Any

from uteki_api.tools._fixtures import quote_for
from uteki_api.tools.base import Tool, ToolResult


class MarketQuoteTool(Tool):
    name = "market_quote"
    description = (
        "获取股票/ETF 的最新行情快照，含价格、涨跌幅、成交量、市值、PE/PB、"
        "52 周高低。已覆盖：300750.SZ(宁德时代)、600519.SH(贵州茅台)、"
        "000858.SZ(五粮液)、AAPL、NVDA、TSLA、MSFT、SPY、QQQ、SOXX、510300.SH。"
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "标的代码，例如 '300750.SZ' / 'AAPL'",
            },
        },
        "required": ["symbol"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        symbol = kwargs.get("symbol", "").strip()
        if not symbol:
            return ToolResult(ok=False, error="symbol is required")

        q = quote_for(symbol)
        chg = q.get("change_pct", 0.0)
        sign = "+" if chg >= 0 else ""
        vol = q.get("volume", 0)
        summary = (
            f"{q['symbol']} ({q.get('name', '?')}): {q['price']} "
            f"({sign}{chg}%) vol={vol:,}"
        )
        return ToolResult(ok=True, summary=summary, data=q)
