"""015 PR ε · Reliable spot-price fetch for backtest layer.

Background: ``market_quote`` tool optimizes for skill-facing analysis
data (PE / 52w high / market cap / etc.) and uses ``yf.Ticker(...).info``
+ ``fast_info``. Those endpoints exhibit occasional cache misbehavior:
the price field may briefly carry stale data from an unrelated ticker
or a pre-split historical value. Observed in PR ε MVP: GOOGL widget
showed entry $368 (correct) but now-price $122.72 — a phantom value
that doesn't match any real GOOGL session since 2024.

For the backtest layer we want **only** the close-of-session price —
no PE, no market cap, no derived fields. Pull it directly from the
``history()`` endpoint which talks to Yahoo's raw price API and is
not affected by the ``info`` / ``fast_info`` cache layer.

This module is intentionally separate from ``tools/market_quote.py`` so:
  - market_quote stays the skill's quote source (with all the analysis
    fields the prompt expects)
  - backtest gets a narrow, reliable spot price
  - the next provider switch (polygon / IEX) lives in one place
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


async def spot_price(symbol: str) -> float | None:
    """Return the latest close price for ``symbol`` via yfinance ``history()``.

    Returns None on any failure. Never raises. Used by the prediction
    dispatcher and the live-widget endpoint.

    Why ``history(period='5d')`` instead of ``fast_info.last_price``:
    history pulls directly from Yahoo's raw price endpoint. fast_info /
    info wrap a separate cache layer that occasionally returns stale or
    cross-contaminated values (the entry $368 → now $122 phantom in
    PR ε MVP). History has not exhibited that failure mode.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _spot_price_sync, symbol)


def _spot_price_sync(symbol: str) -> float | None:
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed; spot_price returning None")
        return None
    try:
        ticker = yf.Ticker(symbol)
        # period=5d covers weekends + holidays; tail(1) picks most-recent close.
        hist = ticker.history(period="5d", auto_adjust=True)
    except Exception as e:  # noqa: BLE001 — backtest must degrade, never raise
        logger.warning("spot_price[%s] history() failed: %s", symbol, e)
        return None
    if hist is None or hist.empty:
        logger.info("spot_price[%s] empty history; symbol may be delisted", symbol)
        return None
    try:
        last_close = float(hist["Close"].iloc[-1])
    except (KeyError, IndexError, TypeError, ValueError) as e:
        logger.warning("spot_price[%s] no Close column in history: %s", symbol, e)
        return None
    if last_close <= 0:
        logger.info("spot_price[%s] non-positive close=%s; rejecting", symbol, last_close)
        return None
    return last_close
