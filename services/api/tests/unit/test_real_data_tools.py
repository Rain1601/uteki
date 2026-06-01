"""Unit tests for live-data tool routing without network calls."""

from __future__ import annotations

from typing import Any

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
async def test_web_extract_parses_real_html(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase C.3b — _fetch_and_parse processes article-style HTML, lifts
    title + body + published_at, normalises whitespace, attaches meta."""
    from uteki_api.tools import web_extract as mod

    sample_html = """
    <html>
      <head>
        <title>NVDA Q3 FY25 review</title>
        <meta property="og:title" content="NVDA Q3 FY25 results review">
        <meta property="article:published_time" content="2025-11-21T14:00:00Z">
      </head>
      <body>
        <nav>menu</nav>
        <article>
          <h1>NVDA crushes Q3</h1>
          <p>Revenue hit $35.1B, up 94% YoY.</p>
          <p>Margins expanded to 75%.</p>
          <ul>
            <li>Blackwell ramp tracking ahead</li>
            <li>Datacenter segment up 112%</li>
          </ul>
        </article>
        <footer>copyright nonsense</footer>
        <script>tracker();</script>
      </body>
    </html>
    """

    class _StubResp:
        text = sample_html
        def raise_for_status(self) -> None:
            return None

    class _StubClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...
        async def __aenter__(self) -> _StubClient:
            return self
        async def __aexit__(self, *a: Any) -> None:
            return None
        async def get(self, url: str) -> _StubResp:
            return _StubResp()

    monkeypatch.setattr(mod.httpx, "AsyncClient", _StubClient)
    monkeypatch.setattr(settings, "use_mock_data", False)

    result = await mod.WebExtractTool().run(url="https://example.com/nvda-q3")
    assert result.ok
    data = result.data
    # og:title beats <title>
    assert data["title"] == "NVDA Q3 FY25 results review"
    # body contains article content, NOT nav / footer / scripts
    assert "Revenue hit $35.1B" in data["text"]
    assert "menu" not in data["text"]
    assert "copyright nonsense" not in data["text"]
    assert "tracker" not in data["text"]
    # list items kept (article-mode preserves <li>)
    assert "Blackwell ramp tracking ahead" in data["text"]
    # H1 gets markdown heading prefix
    assert "# NVDA crushes Q3" in data["text"]
    # meta-tag published_at lifted
    assert data["published_at"] == "2025-11-21T14:00:00Z"
    # source point includes the published_at so SourceCatalog can rank/reject
    assert result.sources[0]["published_at"] == "2025-11-21T14:00:00Z"
    assert result.sources[0]["source_type"] == "web_extract"


@pytest.mark.asyncio
async def test_web_extract_degrades_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP failure → mock fixture fallback with explanatory note so the
    agent's tool-use loop keeps progressing instead of crashing."""
    from uteki_api.tools import web_extract as mod

    class _StubClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...
        async def __aenter__(self) -> _StubClient:
            return self
        async def __aexit__(self, *a: Any) -> None:
            return None
        async def get(self, url: str) -> Any:
            raise mod.httpx.ConnectError("simulated network failure")

    monkeypatch.setattr(mod.httpx, "AsyncClient", _StubClient)
    monkeypatch.setattr(settings, "use_mock_data", False)

    result = await mod.WebExtractTool().run(url="https://unreachable.example.com/x")
    assert result.ok  # graceful degrade — tool itself doesn't fail
    assert "fetch failed" in result.summary
    assert result.data["url"] == "https://unreachable.example.com/x"
    assert result.sources[0]["confidence"] == "low"


@pytest.mark.asyncio
async def test_web_extract_validates_url() -> None:
    """Refuses missing or non-http(s) URLs without making a request."""
    from uteki_api.tools.web_extract import WebExtractTool

    tool = WebExtractTool()
    assert (await tool.run(url="")).ok is False
    assert (await tool.run(url="ftp://example.com/x")).ok is False
    assert (await tool.run(url="javascript:alert(1)")).ok is False


@pytest.mark.asyncio
async def test_web_search_uses_live_providers_when_mock_data_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase C.3 — web_search migrated from mock to Google CSE + DDGS.
    Google CSE empty → falls through to DDGS → returns real results."""
    from uteki_api.tools import web_search as mod
    from uteki_api.tools.web_search import WebSearchTool

    monkeypatch.setattr(settings, "use_mock_data", False)

    async def fake_google_empty(_q: str, _l: int) -> list[dict]:
        return []  # simulate missing CSE key

    async def fake_ddgs(query: str, _l: int) -> list[dict]:
        return [
            {
                "title": f"{query} doc",
                "snippet": "real snippet body",
                "source": "example.com",
                "url": "https://example.com/doc",
                "provider": "ddgs",
            }
        ]

    monkeypatch.setattr(mod, "_google_cse_general", fake_google_empty)
    monkeypatch.setattr(mod, "_ddgs_general", fake_ddgs)

    result = await WebSearchTool().run(query="NVDA datacenter", limit=1)
    assert result.ok
    assert result.data["results"][0]["provider"] == "ddgs"
    assert result.sources[0]["source_type"] == "web_search"


@pytest.mark.asyncio
async def test_web_search_prefers_google_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Google CSE returns results → DDGS not called (priority order)."""
    from uteki_api.tools import web_search as mod
    from uteki_api.tools.web_search import WebSearchTool

    monkeypatch.setattr(settings, "use_mock_data", False)

    async def fake_google_ok(query: str, _l: int) -> list[dict]:
        return [
            {
                "title": f"{query} from google",
                "snippet": "cse body",
                "source": "docs.example.com",
                "url": "https://docs.example.com/x",
                "provider": "google_cse",
            }
        ]

    ddgs_called = False

    async def fake_ddgs_unused(_q: str, _l: int) -> list[dict]:
        nonlocal ddgs_called
        ddgs_called = True
        return [{"title": "should not be reached"}]

    monkeypatch.setattr(mod, "_google_cse_general", fake_google_ok)
    monkeypatch.setattr(mod, "_ddgs_general", fake_ddgs_unused)

    result = await WebSearchTool().run(query="NVDA cuda", limit=1)
    assert result.ok
    assert result.data["results"][0]["provider"] == "google_cse"
    assert ddgs_called is False, "DDGS must not be called when Google CSE returns hits"


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


@pytest.fixture(autouse=False)
def _reset_sec_ticker_cache() -> Any:
    """SEC ticker map cache leaks across tests; reset before + after."""
    from uteki_api.tools import report_analysis as mod

    mod._TICKER_CACHE = None
    yield
    mod._TICKER_CACHE = None


@pytest.mark.asyncio
async def test_report_analysis_resolves_sec_filing_for_symbol(
    monkeypatch: pytest.MonkeyPatch, _reset_sec_ticker_cache: Any
) -> None:
    """Phase C.2 — symbol → CIK lookup → submissions → primary doc → text.
    Verifies the full SEC EDGAR happy path, including the doc URL builder
    and that the result carries a sec_edgar source point."""
    from uteki_api.tools import report_analysis as mod

    monkeypatch.setattr(settings, "use_mock_data", False)

    ticker_payload = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp."},
    }
    submissions_payload = {
        "filings": {
            "recent": {
                "form": ["8-K", "10-K", "10-Q"],
                "accessionNumber": [
                    "0000320193-23-000077",
                    "0000320193-23-000106",
                    "0000320193-23-000064",
                ],
                "primaryDocument": [
                    "aapl-20230501.htm",
                    "aapl-20230930.htm",
                    "aapl-20230701.htm",
                ],
                "filingDate": ["2023-05-04", "2023-11-02", "2023-08-03"],
            }
        }
    }
    filing_html = (
        "<html><body>"
        "<script>tracker()</script>"
        "<h2>Item 1A. Risk Factors</h2>"
        "<p>Macroeconomic conditions could materially impact demand for our products.</p>"
        "<p>Supply chain concentration in Asia remains a key operational risk.</p>"
        "<p>Foreign exchange volatility may pressure reported revenue.</p>"
        "<h2>Item 2. Properties</h2>"
        "<p>Headquarters in Cupertino, CA.</p>"
        "</body></html>"
    )

    class _Resp:
        def __init__(self, payload: Any = None, text: str = "") -> None:
            self._payload = payload
            self.text = text

        def json(self) -> Any:
            return self._payload

        def raise_for_status(self) -> None:
            return None

    class _StubClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...
        async def __aenter__(self) -> _StubClient:
            return self
        async def __aexit__(self, *a: Any) -> None:
            return None
        async def get(self, url: str) -> _Resp:
            if url == mod.TICKER_MAP_URL:
                return _Resp(payload=ticker_payload)
            if url.startswith("https://data.sec.gov/submissions/"):
                # CIK should be zero-padded to 10 digits
                assert "CIK0000320193.json" in url
                return _Resp(payload=submissions_payload)
            if url.startswith("https://www.sec.gov/Archives/edgar/data/"):
                # Archive path uses unpadded CIK + dashless accession
                assert "/320193/000032019323000106/aapl-20230930.htm" in url
                return _Resp(text=filing_html)
            raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(mod.httpx, "AsyncClient", _StubClient)

    result = await mod.ReportAnalysisTool().run(
        symbol="AAPL", filing_type="10-K", focus="risks"
    )

    assert result.ok, result.error
    assert result.data["filing"]["form"] == "10-K"
    assert result.data["filing"]["filing_date"] == "2023-11-02"
    sec = result.sources[0]
    assert sec["source_type"] == "sec_edgar"
    assert sec["publisher"] == "SEC EDGAR"
    assert sec["published_at"] == "2023-11-02"
    # The risk-factors section was extracted (not the Properties section)
    section_text = result.data["sections"][0]["bullets"]
    joined = " ".join(section_text)
    assert "Macroeconomic conditions" in joined
    assert "Cupertino" not in joined


@pytest.mark.asyncio
async def test_report_analysis_unknown_symbol_returns_error(
    monkeypatch: pytest.MonkeyPatch, _reset_sec_ticker_cache: Any
) -> None:
    """Unknown ticker → ok=False with a clear summary, no further fetches."""
    from uteki_api.tools import report_analysis as mod

    monkeypatch.setattr(settings, "use_mock_data", False)

    class _Resp:
        def json(self) -> dict:
            return {"0": {"cik_str": 320193, "ticker": "AAPL"}}
        def raise_for_status(self) -> None:
            return None

    fetches: list[str] = []

    class _StubClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...
        async def __aenter__(self) -> _StubClient:
            return self
        async def __aexit__(self, *a: Any) -> None:
            return None
        async def get(self, url: str) -> _Resp:
            fetches.append(url)
            return _Resp()

    monkeypatch.setattr(mod.httpx, "AsyncClient", _StubClient)

    result = await mod.ReportAnalysisTool().run(symbol="ZZZZ", focus="summary")

    assert result.ok is False
    assert "not found" in result.summary
    # Only the ticker map should have been fetched — no submissions call
    assert fetches == [mod.TICKER_MAP_URL]


def test_report_analysis_extract_focus_section_picks_risk_factors() -> None:
    """Section extraction stops at the next ``Item N`` heading and caps length."""
    from uteki_api.tools.report_analysis import _extract_focus_section

    text = (
        "Item 1. Business\n\n"
        "We sell things.\n\n"
        "Item 1A. Risk Factors\n\n"
        "Foreign exchange exposure is a risk.\n\n"
        "Supply chain is a risk.\n\n"
        "Item 2. Properties\n\n"
        "Our HQ is in Cupertino."
    )
    section = _extract_focus_section(text, "risks")
    assert "Foreign exchange exposure" in section
    assert "Supply chain" in section
    # Boundary respected — Properties block excluded
    assert "Cupertino" not in section


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
