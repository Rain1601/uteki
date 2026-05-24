"""财务指标工具 — mock implementation backed by curated fixtures.

Known tickers (300750.SZ / 600519.SH / AAPL / NVDA) return realistic period
data from ``_fixtures.FINANCIALS_FIXTURES``. Unknown tickers get deterministic
random rows so the model still has *something* with a stable shape.

Future: plug into akshare / Tushare / Wind / 财报 SDK by replacing the
``financials_for(...)`` call.
"""

from __future__ import annotations

from typing import Any

from uteki_api.tools._fixtures import financials_for
from uteki_api.tools.base import Tool, ToolResult


class FinancialsTool(Tool):
    name = "financials"
    description = (
        "拉取财务指标（营收 / 净利润 / 毛利率 / ROE / EPS / YoY），"
        "支持年报 / 季报。已覆盖：300750.SZ(宁德时代年报+季报)、"
        "600519.SH(贵州茅台)、AAPL、NVDA。其它 ticker 返回近似值（须谨慎使用）。"
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "标的代码，例如 '300750.SZ' 或 'AAPL'",
            },
            "period": {
                "type": "string",
                "enum": ["annual", "quarterly"],
                "default": "annual",
                "description": "报表周期",
            },
            "years": {
                "type": "integer",
                "default": 3,
                "minimum": 1,
                "maximum": 10,
                "description": "返回的期数（年报为年数，季报为季度数）",
            },
        },
        "required": ["symbol"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        symbol = kwargs.get("symbol", "").strip()
        period = kwargs.get("period", "annual")
        years = int(kwargs.get("years", 3))
        if not symbol:
            return ToolResult(ok=False, error="symbol is required")
        if period not in ("annual", "quarterly"):
            return ToolResult(ok=False, error=f"invalid period: {period}")
        years = max(1, min(years, 10))

        rows = financials_for(symbol, period, years)
        return ToolResult(
            ok=True,
            summary=f"{symbol} {period} 财务指标 {len(rows)} 期 (最新: {rows[-1]['period_label'] if rows else 'n/a'})",
            data={"symbol": symbol, "period": period, "rows": rows},
        )
