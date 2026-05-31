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
        }

    monkeypatch.setattr(mod, "_yfinance_financials", fake_financials)

    result = await FinancialsTool().run(symbol="AAPL", years=1)

    assert result.ok
    assert result.data["source"] == "yfinance"
    assert result.data["rows"][0]["revenue_b"] == 100.0
    assert result.sources[0]["source_type"] == "financials"


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

    async def fake_bars(_symbol: str, _interval: str, _limit: int) -> list[dict]:
        return [{"ts": 1, "o": 10.0, "h": 11.0, "l": 9.0, "c": 10.5, "v": 100}]

    monkeypatch.setattr(mod, "_yfinance_bars", fake_bars)

    result = await KLineTool().run(symbol="AAPL", interval="1d", limit=1)

    assert result.ok
    assert result.data["source"] == "yfinance"
    assert result.data["bars"][0]["c"] == 10.5
    assert result.sources[0]["source_type"] == "market_data"
