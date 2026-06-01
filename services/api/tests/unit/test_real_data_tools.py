"""Unit tests for live-data tool routing without network calls."""

from __future__ import annotations

import pytest

from uteki_api.core.config import settings
from uteki_api.tools.financials import FinancialsTool
from uteki_api.tools.kline import KLineTool
from uteki_api.tools.market_quote import MarketQuoteTool
from uteki_api.tools.news_search import NewsSearchTool


@pytest.mark.asyncio
async def test_market_quote_prefers_yfinance_when_mock_data_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from uteki_api.tools import market_quote as mod

    monkeypatch.setattr(settings, "use_mock_data", False)

    async def fake_yfinance(symbol: str) -> dict:
        return {
            "symbol": symbol,
            "name": "Apple Inc.",
            "price": 312.06,
            "change_pct": 1.2,
            "volume": 123,
            "source": "yfinance",
            "source_url": "https://finance.yahoo.com/quote/AAPL",
        }

    async def fake_fmp(_symbol: str) -> None:
        return None

    monkeypatch.setattr(mod, "_yfinance_quote", fake_yfinance)
    monkeypatch.setattr(mod, "_fmp_quote", fake_fmp)

    result = await MarketQuoteTool().run(symbol="AAPL")

    assert result.ok
    assert result.data["source"] == "yfinance"
    assert result.sources[0]["publisher"] == "Yahoo Finance"
    assert result.sources[0]["source_type"] == "market_data"


@pytest.mark.asyncio
async def test_financials_prefers_yfinance_when_mock_data_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from uteki_api.tools import financials as mod

    monkeypatch.setattr(settings, "use_mock_data", False)

    async def fake_financials(symbol: str, period: str, years: int) -> dict:
        return {
            "symbol": symbol,
            "period": period,
            "source": "yfinance",
            "rows": [
                {
                    "period_label": "2025",
                    "revenue_b": 100.0,
                    "net_profit_b": 20.0,
                    "gross_margin": 0.45,
                    "roe": 0.3,
                    "source": "yfinance",
                }
            ][:years],
            # Phase C.1 — the enriched shape passes through unmodified
            "derived": {"owner_earnings_per_share": 5.25, "free_cashflow": 95_000_000_000.0},
            "insider": [{"insider": "JANE DOE", "transaction": "Buy", "shares": 1000.0, "value": 100000.0}],
            "ownership": {"institutional_pct": 0.62, "insider_pct": 0.018, "top_holders": []},
            "rd_data": {"rd_pct_revenue": 24.5, "rd_history": []},
            "analyst": {"target_mean": 250.0, "number_of_analysts": 35, "recommendations": []},
        }

    monkeypatch.setattr(mod, "_yfinance_financials", fake_financials)

    result = await FinancialsTool().run(symbol="AAPL", years=1)

    assert result.ok
    assert result.data["source"] == "yfinance"
    assert result.data["rows"][0]["revenue_b"] == 100.0
    assert result.sources[0]["source_type"] == "financials"
    # Phase C.1 — enriched fields make it through to the tool result.
    assert result.data["derived"]["owner_earnings_per_share"] == 5.25
    assert result.data["insider"][0]["transaction"] == "Buy"
    assert result.data["ownership"]["institutional_pct"] == 0.62
    assert result.data["rd_data"]["rd_pct_revenue"] == 24.5
    assert result.data["analyst"]["target_mean"] == 250.0


def test_financials_enrichment_helpers_handle_empty_yfinance() -> None:
    """yfinance occasionally returns None / empty DataFrames for newly-IPO'd
    or low-coverage tickers. The enrichment helpers must degrade to empty
    defaults instead of raising."""
    from uteki_api.tools.financials import (
        _yfinance_analyst,
        _yfinance_insider_transactions,
        _yfinance_ownership,
        _yfinance_rd,
    )

    class _StubTicker:
        """yfinance.Ticker-shaped stub that returns nothing for every
        endpoint the helpers probe."""
        insider_transactions = None
        institutional_holders = None
        financials = None
        recommendations = None

    stub = _StubTicker()
    info: dict = {}

    assert _yfinance_insider_transactions(stub) == []
    ownership = _yfinance_ownership(stub, info)
    assert ownership["top_holders"] == []
    assert ownership["insider_pct"] is None
    rd = _yfinance_rd(stub)
    assert rd["rd_history"] == []
    assert rd["rd_pct_revenue"] is None
    analyst = _yfinance_analyst(stub, info)
    assert analyst["recommendations"] == []
    assert analyst["target_mean"] is None


@pytest.mark.asyncio
async def test_news_search_uses_live_provider_when_mock_data_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uteki_api.tools import news_search as mod

    monkeypatch.setattr(settings, "use_mock_data", False)

    async def fake_google(_query: str, _limit: int) -> list[dict]:
        return []

    async def fake_ddgs(query: str, _limit: int) -> list[dict]:
        return [
            {
                "title": f"{query} real news",
                "summary": "real summary",
                "source": "Example News",
                "url": "https://example.com/real",
                "provider": "ddgs",
            }
        ]

    monkeypatch.setattr(mod, "_google_cse_search", fake_google)
    monkeypatch.setattr(mod, "_ddgs_search", fake_ddgs)

    result = await NewsSearchTool().run(query="AAPL earnings", limit=1)

    assert result.ok
    assert result.data["items"][0]["provider"] == "ddgs"
    assert result.sources[0]["source_type"] == "news"


@pytest.mark.asyncio
async def test_kline_uses_yfinance_when_mock_data_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from uteki_api.tools import kline as mod

    monkeypatch.setattr(settings, "use_mock_data", False)

    async def fake_bars(
        _symbol: str, _interval: str, _limit: int, end: str | None = None,
    ) -> list[dict]:
        # signature matches the M1.x as_of-aware `_yfinance_bars`
        return [{"ts": 1, "o": 10.0, "h": 11.0, "l": 9.0, "c": 10.5, "v": 100}]

    monkeypatch.setattr(mod, "_yfinance_bars", fake_bars)

    result = await KLineTool().run(symbol="AAPL", interval="1d", limit=1)

    assert result.ok
    assert result.data["source"] == "yfinance"
    assert result.data["bars"][0]["c"] == 10.5
    assert result.sources[0]["source_type"] == "market_data"
