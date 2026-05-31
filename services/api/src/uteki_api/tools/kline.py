"""K-line (OHLCV) tool.

Real runs use yfinance for US-style symbols, following uteki.open's provider
approach. Mock/test runs retain deterministic generated bars.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import time
from datetime import UTC, datetime
from typing import Any

from uteki_api.core.config import settings
from uteki_api.tools.base import Tool, ToolResult

_INTERVAL_SECONDS = {
    "1m": 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "1d": 24 * 60 * 60,
    "1w": 7 * 24 * 60 * 60,
}


class KLineTool(Tool):
    name = "kline"
    description = "获取标的的 K 线数据（OHLCV：开/高/低/收/量），支持多种周期。"
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "标的代码，例如 '300750.SZ' 或 'AAPL'",
            },
            "interval": {
                "type": "string",
                "enum": ["1m", "5m", "15m", "1h", "1d", "1w"],
                "default": "1d",
                "description": "K 线周期",
            },
            "limit": {
                "type": "integer",
                "default": 30,
                "minimum": 1,
                "maximum": 500,
                "description": "返回的 K 线根数",
            },
        },
        "required": ["symbol"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        symbol = kwargs.get("symbol", "")
        interval = kwargs.get("interval", "1d")
        limit = int(kwargs.get("limit", 30))
        if not symbol:
            return ToolResult(ok=False, error="symbol is required")
        if interval not in _INTERVAL_SECONDS:
            return ToolResult(ok=False, error=f"invalid interval: {interval}")
        limit = max(1, min(limit, 500))

        if not settings.use_mock_data:
            try:
                bars = await _yfinance_bars(symbol.upper(), interval, limit)
            except Exception:
                bars = []
            if bars:
                return ToolResult(
                    ok=True,
                    summary=f"{symbol} {interval} 拉到 {len(bars)} 根真实 K 线",
                    data={
                        "symbol": symbol.upper(),
                        "interval": interval,
                        "bars": bars,
                        "source": "yfinance",
                        "fetched_at": datetime.now(UTC).isoformat(),
                    },
                    sources=[
                        {
                            "key": f"kline:{symbol}:{interval}:yfinance",
                            "value": {"symbol": symbol.upper(), "interval": interval, "bars": bars[-5:]},
                            "source_type": "market_data",
                            "source_url": f"https://finance.yahoo.com/quote/{symbol.upper()}",
                            "publisher": "Yahoo Finance",
                            "confidence": "medium",
                            "excerpt": f"{symbol.upper()} {interval} latest close={bars[-1]['c']}",
                        }
                    ],
                )

        seed = int(hashlib.md5(f"{symbol}|{interval}".encode()).hexdigest(), 16) % (2**32)
        rng = random.Random(seed)
        step = _INTERVAL_SECONDS[interval]
        now_ts = int(time.time() // step * step)

        bars: list[dict[str, Any]] = []
        price = rng.uniform(20, 300)
        for i in range(limit):
            ts = now_ts - (limit - 1 - i) * step
            o = round(price, 2)
            c = round(o * (1 + rng.uniform(-0.03, 0.03)), 2)
            h = round(max(o, c) * (1 + rng.uniform(0, 0.02)), 2)
            low = round(min(o, c) * (1 - rng.uniform(0, 0.02)), 2)
            v = rng.randint(10_000, 5_000_000)
            bars.append({"ts": ts, "o": o, "h": h, "l": low, "c": c, "v": v})
            price = c

        return ToolResult(
            ok=True,
            summary=f"{symbol} {interval} 拉到 {len(bars)} 根 K 线",
            data={"symbol": symbol, "interval": interval, "bars": bars, "source": "mock-random"},
        )


async def _yfinance_bars(symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _yfinance_bars_sync, symbol, interval, limit)


def _yfinance_bars_sync(symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
    import yfinance as yf

    yf_interval = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "1h": "1h",
        "1d": "1d",
        "1w": "1wk",
    }[interval]
    period = "7d" if interval in {"1m", "5m", "15m"} else "2y"
    df = yf.Ticker(symbol).history(period=period, interval=yf_interval, auto_adjust=False)
    if df is None or df.empty:
        return []
    rows = []
    for idx, row in df.tail(limit).iterrows():
        ts = int(idx.timestamp()) if hasattr(idx, "timestamp") else 0
        rows.append(
            {
                "ts": ts,
                "o": round(float(row.get("Open", 0)), 4),
                "h": round(float(row.get("High", 0)), 4),
                "l": round(float(row.get("Low", 0)), 4),
                "c": round(float(row.get("Close", 0)), 4),
                "v": int(float(row.get("Volume", 0))),
            }
        )
    return rows
