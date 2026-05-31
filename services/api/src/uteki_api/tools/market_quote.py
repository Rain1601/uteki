"""Market quote tool.

The first implementation was fixture-only. The current tool follows the
uteki.open pattern: use live providers for real agent runs, and retain fixtures
for mock/test mode. For US symbols the primary no-key provider is yfinance;
FMP is an optional fallback when ``FMP_API_KEY`` is configured.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from uteki_api.core.config import settings
from uteki_api.tools._fixtures import quote_for
from uteki_api.tools.base import Tool, ToolResult


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_fast_value(fast: Any, *names: str) -> Any:
    for name in names:
        if isinstance(fast, dict) and name in fast:
            return fast[name]
        value = getattr(fast, name, None)
        if value is not None:
            return value
    return None


async def _yfinance_quote(symbol: str) -> dict[str, Any] | None:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _yfinance_quote_sync, symbol)


def _yfinance_quote_sync(symbol: str) -> dict[str, Any] | None:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    fast = ticker.fast_info
    info = ticker.info or {}

    price = _num(
        _get_fast_value(fast, "last_price", "lastPrice")
        or info.get("currentPrice")
        or info.get("regularMarketPrice")
    )
    prev_close = _num(
        _get_fast_value(fast, "previous_close", "previousClose") or info.get("previousClose")
    )
    if price is None:
        return None

    change_pct = None
    if prev_close and prev_close > 0:
        change_pct = round((price - prev_close) / prev_close * 100, 4)

    market_cap = _num(_get_fast_value(fast, "market_cap", "marketCap") or info.get("marketCap"))
    volume = _num(
        _get_fast_value(fast, "last_volume", "lastVolume")
        or info.get("regularMarketVolume")
        or info.get("volume")
    )
    fifty_two_week_high = _num(
        _get_fast_value(fast, "year_high", "yearHigh") or info.get("fiftyTwoWeekHigh")
    )
    fifty_two_week_low = _num(
        _get_fast_value(fast, "year_low", "yearLow") or info.get("fiftyTwoWeekLow")
    )

    return {
        "symbol": symbol,
        "name": info.get("longName") or info.get("shortName") or symbol,
        "price": round(price, 4),
        "previous_close": round(prev_close, 4) if prev_close is not None else None,
        "change_pct": change_pct,
        "volume": int(volume) if volume is not None else None,
        "market_cap": market_cap,
        "market_cap_usd_b": round(market_cap / 1_000_000_000, 3) if market_cap else None,
        "pe_ttm": _num(info.get("trailingPE")),
        "pb": _num(info.get("priceToBook")),
        "fifty_two_week_high": fifty_two_week_high,
        "fifty_two_week_low": fifty_two_week_low,
        "currency": info.get("currency"),
        "exchange": info.get("exchange"),
        "source": "yfinance",
        "source_url": f"https://finance.yahoo.com/quote/{symbol}",
        "fetched_at": datetime.now(UTC).isoformat(),
    }


async def _fmp_quote(symbol: str) -> dict[str, Any] | None:
    if not settings.fmp_api_key:
        return None
    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.get(
            "https://financialmodelingprep.com/stable/quote",
            params={"symbol": symbol, "apikey": settings.fmp_api_key},
        )
        resp.raise_for_status()
        data = resp.json()
    if not data:
        return None
    q = data[0] if isinstance(data, list) else data
    price = _num(q.get("price"))
    if price is None:
        return None
    market_cap = _num(q.get("marketCap"))
    return {
        "symbol": symbol,
        "name": q.get("name") or symbol,
        "price": round(price, 4),
        "change_pct": _num(q.get("changePercentage")),
        "volume": q.get("volume"),
        "market_cap": market_cap,
        "market_cap_usd_b": round(market_cap / 1_000_000_000, 3) if market_cap else None,
        "pe_ttm": _num(q.get("pe")),
        "currency": "USD",
        "exchange": q.get("exchange"),
        "source": "fmp",
        "source_url": f"https://site.financialmodelingprep.com/financial-statements/{symbol}",
        "fetched_at": datetime.now(UTC).isoformat(),
    }


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

        if settings.use_mock_data:
            return self._fixture_result(symbol)

        errors: list[str] = []
        for fetcher in (_yfinance_quote, _fmp_quote):
            try:
                q = await fetcher(symbol.upper())
            except Exception as e:  # noqa: BLE001 - provider failure should degrade
                errors.append(f"{fetcher.__name__}: {e}")
                continue
            if q:
                return self._quote_result(q)

        fallback = self._fixture_result(symbol)
        fallback.summary += " · live providers unavailable; fixture fallback"
        fallback.data["provider_errors"] = errors
        return fallback

    @staticmethod
    def _fixture_result(symbol: str) -> ToolResult:
        q = quote_for(symbol)
        q = {**q, "source": q.get("source", "mock-fixture")}
        return MarketQuoteTool._quote_result(q, confidence="low")

    @staticmethod
    def _quote_result(q: dict[str, Any], confidence: str = "medium") -> ToolResult:
        chg = q.get("change_pct", 0.0)
        sign = "+" if chg is not None and chg >= 0 else ""
        vol = q.get("volume", 0)
        summary = (
            f"{q['symbol']} ({q.get('name', '?')}): {q['price']} "
            f"({sign}{chg if chg is not None else 'n/a'}%) vol={vol or 0:,}"
        )
        source = q.get("source", "unknown")
        publisher = "Yahoo Finance" if source == "yfinance" else "Financial Modeling Prep"
        if source.startswith("mock"):
            publisher = "mock-fixture"
        return ToolResult(
            ok=True,
            summary=summary,
            data=q,
            sources=[
                {
                    "key": f"quote:{q['symbol']}:{source}",
                    "value": q,
                    "source_type": "market_data",
                    "source_url": q.get("source_url"),
                    "publisher": publisher,
                    "published_at": q.get("fetched_at"),
                    "confidence": confidence,
                    "excerpt": summary,
                }
            ],
        )
