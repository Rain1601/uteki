"""as_of backtest mode — per-tool unit tests.

Verifies the contract from design/09-as-of-threading.md §3.3:
- tools accept an ``as_of`` ISO date kwarg and slice/filter accordingly
- when ``as_of`` is omitted, behavior is exactly as before (backward compat)
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from uteki_api.core.config import settings
from uteki_api.tools.financials import FinancialsTool
from uteki_api.tools.kline import KLineTool
from uteki_api.tools.market_quote import MarketQuoteTool
from uteki_api.tools.news_search import NewsSearchTool
from uteki_api.tools.web_search import WebSearchTool

# ── kline ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_kline_mock_anchors_bars_at_as_of(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock bars in backtest mode must end at the as_of date, not 'now'."""
    monkeypatch.setattr(settings, "use_mock_data", True)
    tool = KLineTool()
    result = await tool.run(symbol="AAPL", interval="1d", limit=10, as_of="2024-01-01")
    assert result.ok
    bars = result.data["bars"]
    assert bars
    last_ts = bars[-1]["ts"]
    cutoff = datetime(2024, 1, 2, tzinfo=UTC).timestamp()  # one step ahead of 2024-01-01
    assert last_ts < cutoff, f"latest mock bar ts={last_ts} leaked past as_of=2024-01-01"


@pytest.mark.asyncio
async def test_kline_mock_without_as_of_anchors_now(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without as_of the existing 'now'-anchored generation must be unchanged."""
    monkeypatch.setattr(settings, "use_mock_data", True)
    tool = KLineTool()
    result = await tool.run(symbol="AAPL", interval="1d", limit=5)
    assert result.ok
    # Last bar within the last 2 days of wall-clock time.
    last_ts = result.data["bars"][-1]["ts"]
    assert abs(last_ts - datetime.now(UTC).timestamp()) < 2 * 24 * 60 * 60


# ── financials ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_financials_filters_rows_after_as_of(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixtures often include current/future-year rows; as_of must cut them."""
    monkeypatch.setattr(settings, "use_mock_data", True)
    tool = FinancialsTool()
    result = await tool.run(symbol="AAPL", period="annual", years=10, as_of="2020-12-31")
    assert result.ok
    rows = result.data["rows"]
    for row in rows:
        label = str(row.get("period_label", ""))[:10]
        assert label <= "2020-12-31", f"row {label} leaked past as_of=2020-12-31"


@pytest.mark.asyncio
async def test_financials_without_as_of_returns_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "use_mock_data", True)
    tool = FinancialsTool()
    result = await tool.run(symbol="AAPL", period="annual", years=3)
    assert result.ok
    assert "as_of" not in result.data
    assert len(result.data["rows"]) > 0


# ── news_search ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_news_search_drops_items_after_as_of(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock items have no published_at, so they survive — but if a provider
    returns explicit future dates, those must be dropped + counted."""
    monkeypatch.setattr(settings, "use_mock_data", True)

    # Inject a synthetic item with an explicit future published_at, plus
    # the normal mock_items, to verify the filter discriminates.
    tool = NewsSearchTool()
    future_iso = (date.today() + timedelta(days=365)).isoformat()
    items_with_dates = [
        {"title": "future", "summary": "x", "source": "src", "url": "u", "published_at": future_iso},
        {"title": "past", "summary": "y", "source": "src", "url": "u2", "published_at": "2020-01-01"},
        {"title": "unknown", "summary": "z", "source": "src", "url": "u3"},  # no date
    ]
    result = tool._items_result("q", items_with_dates, as_of="2020-12-31")
    assert result.ok
    titles = [i["title"] for i in result.data["items"]]
    assert "future" not in titles, "future-dated news leaked past as_of"
    assert "past" in titles
    assert "unknown" in titles  # no-date items kept by design
    assert result.data["dropped_post_as_of"] == 1


@pytest.mark.asyncio
async def test_news_search_without_as_of_returns_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "use_mock_data", True)
    tool = NewsSearchTool()
    result = await tool.run(query="AAPL", limit=5)
    assert result.ok
    assert "as_of" not in result.data


# ── market_quote ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_market_quote_refuses_historical_as_of(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backtest mode: market_quote cannot honestly return a spot price for the
    past, so it must refuse and point at kline instead — silent fallback to
    today's price would be a correctness bug."""
    monkeypatch.setattr(settings, "use_mock_data", True)
    tool = MarketQuoteTool()
    result = await tool.run(symbol="AAPL", as_of="2020-01-01")
    assert result.ok is False
    assert "kline" in result.error
    assert "as_of=2020-01-01" in result.error


@pytest.mark.asyncio
async def test_market_quote_with_today_as_of_proceeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """as_of == today is a live request, not a backtest — must succeed."""
    monkeypatch.setattr(settings, "use_mock_data", True)
    tool = MarketQuoteTool()
    today = date.today().isoformat()
    result = await tool.run(symbol="AAPL", as_of=today)
    assert result.ok


@pytest.mark.asyncio
async def test_market_quote_without_as_of_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "use_mock_data", True)
    tool = MarketQuoteTool()
    result = await tool.run(symbol="AAPL")
    assert result.ok


# ── web_search ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_web_search_soft_hints_as_of_in_query() -> None:
    """web_search can't filter externally — it injects 'as of X' into the query
    so the search engine and the LLM both see the constraint."""
    tool = WebSearchTool()
    result = await tool.run(query="AAPL revenue", limit=3, as_of="2024-06-30")
    assert result.ok
    assert "as of 2024-06-30" in result.data["query"]
    assert result.data["as_of"] == "2024-06-30"


@pytest.mark.asyncio
async def test_web_search_without_as_of_unchanged() -> None:
    tool = WebSearchTool()
    result = await tool.run(query="AAPL revenue", limit=3)
    assert result.ok
    assert result.data["query"] == "AAPL revenue"
    assert "as_of" not in result.data
