"""Financial metrics tool.

Real runs use yfinance, matching uteki.open's company-data path. Mock/test runs
keep the original fixtures so backend E2E remains deterministic.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from uteki_api.core.config import settings
from uteki_api.tools._fixtures import financials_for
from uteki_api.tools.base import Tool, ToolResult


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float | None, ndigits: int = 4) -> float | None:
    return round(value, ndigits) if value is not None else None


def _statement_value(frame: Any, column: Any, names: tuple[str, ...]) -> float | None:
    if frame is None or getattr(frame, "empty", True):
        return None
    for name in names:
        try:
            if name in frame.index:
                return _num(frame.loc[name, column])
        except Exception:
            continue
    return None


async def _yfinance_financials(symbol: str, period: str, years: int) -> dict[str, Any] | None:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _yfinance_financials_sync, symbol, period, years)


def _yfinance_financials_sync(symbol: str, period: str, years: int) -> dict[str, Any] | None:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    info = ticker.info or {}
    income = ticker.quarterly_financials if period == "quarterly" else ticker.financials
    cashflow = ticker.quarterly_cashflow if period == "quarterly" else ticker.cashflow
    if income is None or income.empty:
        return None

    fetched_at = datetime.now(UTC).isoformat()
    columns = list(income.columns[:years])
    rows: list[dict[str, Any]] = []
    previous_revenue: float | None = None
    for column in reversed(columns):
        revenue = _statement_value(income, column, ("Total Revenue", "Operating Revenue"))
        gross_profit = _statement_value(income, column, ("Gross Profit",))
        operating_income = _statement_value(income, column, ("Operating Income",))
        net_income = _statement_value(
            income,
            column,
            ("Net Income", "Net Income Common Stockholders"),
        )
        eps = _statement_value(income, column, ("Basic EPS", "Diluted EPS"))
        operating_cf = _statement_value(cashflow, column, ("Operating Cash Flow",))
        capex = _statement_value(cashflow, column, ("Capital Expenditure",))
        free_cashflow = _statement_value(cashflow, column, ("Free Cash Flow",))
        if free_cashflow is None and operating_cf is not None and capex is not None:
            free_cashflow = operating_cf + capex

        revenue_yoy = None
        if previous_revenue and revenue is not None and previous_revenue != 0:
            revenue_yoy = (revenue - previous_revenue) / abs(previous_revenue) * 100
        previous_revenue = revenue if revenue is not None else previous_revenue

        label = column.date().isoformat() if hasattr(column, "date") else str(column)[:10]
        if period == "annual" and hasattr(column, "year"):
            label = str(column.year)

        rows.append(
            {
                "period_label": label,
                "revenue_b": _round(revenue / 1_000_000_000, 3) if revenue is not None else None,
                "net_profit_b": _round(net_income / 1_000_000_000, 3)
                if net_income is not None
                else None,
                "gross_profit_b": _round(gross_profit / 1_000_000_000, 3)
                if gross_profit is not None
                else None,
                "operating_income_b": _round(operating_income / 1_000_000_000, 3)
                if operating_income is not None
                else None,
                "free_cashflow_b": _round(free_cashflow / 1_000_000_000, 3)
                if free_cashflow is not None
                else None,
                "gross_margin": _round(gross_profit / revenue, 4)
                if gross_profit is not None and revenue
                else _round(_num(info.get("grossMargins")), 4),
                "operating_margin": _round(operating_income / revenue, 4)
                if operating_income is not None and revenue
                else _round(_num(info.get("operatingMargins")), 4),
                "profit_margin": _round(net_income / revenue, 4)
                if net_income is not None and revenue
                else _round(_num(info.get("profitMargins")), 4),
                "roe": _round(_num(info.get("returnOnEquity")), 4),
                "revenue_yoy": _round(revenue_yoy, 2),
                "eps": _round(eps, 3) or _round(_num(info.get("trailingEps")), 3),
                "source": "yfinance",
                "source_url": f"https://finance.yahoo.com/quote/{symbol}/financials",
                "fetched_at": fetched_at,
            }
        )

    profile = {
        "symbol": symbol,
        "name": info.get("longName") or info.get("shortName") or symbol,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "country": info.get("country"),
        "website": info.get("website"),
    }
    return {
        "symbol": symbol,
        "period": period,
        "rows": rows,
        "profile": profile,
        "profitability": {
            "gross_margin": _num(info.get("grossMargins")),
            "operating_margin": _num(info.get("operatingMargins")),
            "profit_margin": _num(info.get("profitMargins")),
            "roe": _num(info.get("returnOnEquity")),
            "roa": _num(info.get("returnOnAssets")),
        },
        "balance": {
            "current_ratio": _num(info.get("currentRatio")),
            "debt_equity": _num(info.get("debtToEquity")),
            "total_cash": _num(info.get("totalCash")),
            "total_debt": _num(info.get("totalDebt")),
        },
        "growth": {
            "revenue_growth_yoy": _num(info.get("revenueGrowth")),
            "earnings_growth_yoy": _num(info.get("earningsGrowth")),
        },
        "source": "yfinance",
        "fetched_at": fetched_at,
    }


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

        if settings.use_mock_data:
            return self._fixture_result(symbol, period, years)

        try:
            data = await _yfinance_financials(symbol.upper(), period, years)
        except Exception as e:  # noqa: BLE001 - provider failure should degrade
            data = None
            provider_error = str(e)
        else:
            provider_error = ""

        if data and data.get("rows"):
            return self._financials_result(data)

        fallback = self._fixture_result(symbol, period, years)
        fallback.summary += " · live provider unavailable; fixture fallback"
        if isinstance(fallback.data, dict):
            fallback.data["provider_error"] = provider_error
        return fallback

    @staticmethod
    def _fixture_result(symbol: str, period: str, years: int) -> ToolResult:
        rows = financials_for(symbol, period, years)
        return FinancialsTool._financials_result(
            {"symbol": symbol, "period": period, "rows": rows, "source": "mock-fixture"},
            confidence="medium" if all(row.get("source") != "mock-random" for row in rows) else "low",
        )

    @staticmethod
    def _financials_result(data: dict[str, Any], confidence: str = "medium") -> ToolResult:
        symbol = str(data.get("symbol", ""))
        period = str(data.get("period", "annual"))
        rows = data.get("rows", [])
        source_type = str(data.get("source", "financials"))
        publisher = "Yahoo Finance" if source_type == "yfinance" else "mock-fixture"
        source_url = f"https://finance.yahoo.com/quote/{symbol}/financials"
        sources = [
            {
                "key": f"financials:{symbol}:{period}:{row.get('period_label', idx)}",
                "value": row,
                "source_type": "financials",
                "source_url": row.get("source_url") or source_url,
                "publisher": publisher,
                "published_at": row.get("period_label"),
                "fetched_at": row.get("fetched_at") or data.get("fetched_at"),
                "confidence": confidence if row.get("source") != "mock-random" else "low",
                "excerpt": (
                    f"{symbol} {row.get('period_label', idx)} revenue={row.get('revenue_b')} "
                    f"net_profit={row.get('net_profit_b')}"
                ),
            }
            for idx, row in enumerate(rows)
        ]
        return ToolResult(
            ok=True,
            summary=f"{symbol} {period} 财务指标 {len(rows)} 期 (最新: {rows[-1]['period_label'] if rows else 'n/a'})",
            data=data,
            sources=sources,
        )
