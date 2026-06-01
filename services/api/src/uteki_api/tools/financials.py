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
        # Phase C.1 — enrich profile with employees + business description
        # (needed by company_research_pipeline business_analysis gate).
        "employees": info.get("fullTimeEmployees"),
        "description": (info.get("longBusinessSummary") or "")[:1000],
    }
    # Phase C.1 — owner earnings per share = FCF / shares outstanding.
    # The moat gate uses this as a quality-of-earnings signal; matches
    # uteki.open's `derived.owner_earnings_per_share`.
    fcf = _num(info.get("freeCashflow"))
    shares = _num(info.get("sharesOutstanding"))
    owner_earnings_ps = (
        round(fcf / shares, 4) if fcf and shares and shares > 0 else None
    )
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
        # Phase C.1 — derived metrics not directly in info
        "derived": {
            "owner_earnings_per_share": owner_earnings_ps,
            "free_cashflow": fcf,
            "shares_outstanding": shares,
            "market_cap": _num(info.get("marketCap")),
        },
        "insider": _yfinance_insider_transactions(ticker),
        "ownership": _yfinance_ownership(ticker, info),
        "rd_data": _yfinance_rd(ticker),
        "analyst": _yfinance_analyst(ticker, info),
        "source": "yfinance",
        "fetched_at": fetched_at,
    }


# ── Phase C.1 enrichment helpers (yfinance-only, no new deps) ─────────
# Ported from uteki.open's domains/company/financials.py — same yfinance
# columns, adapted to our return-dict shape. All defensive: any yfinance
# exception or missing column degrades to an empty list/dict so the tool
# never propagates a provider hiccup into the agent run.


def _yfinance_insider_transactions(ticker: Any) -> list[dict[str, Any]]:
    """Recent insider buys/sells. yfinance returns a DataFrame; column
    casing varies by yfinance version so probe both."""
    try:
        df = ticker.insider_transactions
    except Exception:
        return []
    if df is None or getattr(df, "empty", True):
        return []
    rows: list[dict[str, Any]] = []
    try:
        for _, row in df.head(15).iterrows():
            rows.append({
                "insider": str(row.get("Insider", row.get("insider", ""))),
                "relation": str(row.get("Relation", row.get("relation", ""))),
                "date": str(row.get("Start Date", row.get("startDate", row.get("date", "")))),
                "transaction": str(row.get("Transaction", row.get("transaction", ""))),
                "shares": _num(row.get("Shares", row.get("shares"))),
                "value": _num(row.get("Value", row.get("value"))),
            })
    except Exception:
        return []
    return rows


def _yfinance_ownership(ticker: Any, info: dict[str, Any]) -> dict[str, Any]:
    """Institutional + insider ownership %. Combines info-level
    aggregates with the institutional-holders detail list."""
    result: dict[str, Any] = {
        "insider_pct": _num(info.get("heldPercentInsiders")),
        "institutional_pct": _num(info.get("heldPercentInstitutions")),
        "top_holders": [],
    }
    try:
        holders = ticker.institutional_holders
        if holders is not None and not getattr(holders, "empty", True):
            top_holders: list[dict[str, Any]] = []
            for _, row in holders.head(10).iterrows():
                top_holders.append({
                    "holder": str(row.get("Holder", row.get("holder", ""))),
                    "shares": _num(row.get("Shares", row.get("shares"))),
                    "pct_out": _num(
                        row.get("pctHeld", row.get("% Out", row.get("pct_out")))
                    ),
                    "value": _num(row.get("Value", row.get("value"))),
                })
            result["top_holders"] = top_holders
    except Exception:
        pass
    return result


def _yfinance_rd(ticker: Any) -> dict[str, Any]:
    """R&D expense + R&D-as-% revenue per year. Reads the same financials
    DataFrame the income table already came from; cheap second pass."""
    result: dict[str, Any] = {"rd_history": [], "rd_pct_revenue": None}
    try:
        fin = ticker.financials
    except Exception:
        return result
    if fin is None or getattr(fin, "empty", True):
        return result
    try:
        for col in fin.columns[:4]:
            rd: float | None = None
            for key in ("Research Development", "Research And Development"):
                if key in fin.index:
                    try:
                        rd = float(fin.loc[key, col])
                        break
                    except Exception:
                        continue
            revenue: float | None = None
            if "Total Revenue" in fin.index:
                try:
                    revenue = float(fin.loc["Total Revenue", col])
                except Exception:
                    revenue = None
            pct = (
                round(rd / revenue * 100, 2)
                if rd and revenue and revenue > 0
                else None
            )
            year = col.year if hasattr(col, "year") else str(col)
            result["rd_history"].append({
                "year": year,
                "rd_expense": rd,
                "revenue": revenue,
                "rd_pct_revenue": pct,
            })
        # The most recent year's R&D% is the headline number.
        if result["rd_history"] and result["rd_history"][0].get("rd_pct_revenue"):
            result["rd_pct_revenue"] = result["rd_history"][0]["rd_pct_revenue"]
    except Exception:
        pass
    return result


def _yfinance_analyst(ticker: Any, info: dict[str, Any]) -> dict[str, Any]:
    """Analyst target prices + most recent recommendations. The valuation
    gate uses these as anchors (and the management gate flags large
    revisions)."""
    result: dict[str, Any] = {
        "target_high": _num(info.get("targetHighPrice")),
        "target_low": _num(info.get("targetLowPrice")),
        "target_mean": _num(info.get("targetMeanPrice")),
        "target_median": _num(info.get("targetMedianPrice")),
        "recommendation_key": info.get("recommendationKey"),
        "number_of_analysts": info.get("numberOfAnalystOpinions"),
        "recommendations": [],
    }
    try:
        recs = ticker.recommendations
        if recs is not None and not getattr(recs, "empty", True):
            recent_rows: list[dict[str, Any]] = []
            for _, row in recs.tail(5).iterrows():
                entry: dict[str, Any] = {}
                for c in recs.columns:
                    val = row.get(c)
                    if val is None:
                        entry[str(c)] = None
                    elif isinstance(val, (int, float)):
                        entry[str(c)] = _num(val)
                    else:
                        entry[str(c)] = str(val)
                recent_rows.append(entry)
            result["recommendations"] = recent_rows
    except Exception:
        pass
    return result


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
        # Backtest cutoff (ISO date). Reports whose period_label is later than
        # this date get filtered out post-fetch. (FMP / yfinance APIs don't
        # take an upper bound, so client-side filter is the honest path.)
        as_of = kwargs.get("as_of")
        if not symbol:
            return ToolResult(ok=False, error="symbol is required")
        if period not in ("annual", "quarterly"):
            return ToolResult(ok=False, error=f"invalid period: {period}")
        years = max(1, min(years, 10))

        if settings.use_mock_data:
            return self._fixture_result(symbol, period, years, as_of=as_of)

        try:
            data = await _yfinance_financials(symbol.upper(), period, years)
        except Exception as e:  # noqa: BLE001 - provider failure should degrade
            data = None
            provider_error = str(e)
        else:
            provider_error = ""

        if data and data.get("rows"):
            if as_of:
                data = self._slice_by_as_of(data, as_of)
            return self._financials_result(data)

        fallback = self._fixture_result(symbol, period, years, as_of=as_of)
        fallback.summary += " · live provider unavailable; fixture fallback"
        if isinstance(fallback.data, dict):
            fallback.data["provider_error"] = provider_error
        return fallback

    @staticmethod
    def _slice_by_as_of(data: dict[str, Any], as_of: str) -> dict[str, Any]:
        """Drop rows whose period_label is later than as_of.

        period_label can be a year ("2023") or an ISO date ("2024-09-30").
        Both compare correctly against an ISO ``as_of`` prefix-wise (years
        stay below "YYYY-12-31"), so a single lexicographic check suffices.
        """
        cutoff = as_of[:10]
        rows = [
            row for row in data.get("rows", [])
            if str(row.get("period_label", ""))[:10] <= cutoff
        ]
        return {**data, "rows": rows, "as_of": as_of}

    @staticmethod
    def _fixture_result(
        symbol: str, period: str, years: int, *, as_of: str | None = None
    ) -> ToolResult:
        rows = financials_for(symbol, period, years)
        if as_of:
            cutoff = as_of[:10]
            rows = [r for r in rows if str(r.get("period_label", ""))[:10] <= cutoff]
        data: dict[str, Any] = {"symbol": symbol, "period": period, "rows": rows, "source": "mock-fixture"}
        if as_of:
            data["as_of"] = as_of
        return FinancialsTool._financials_result(
            data,
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
