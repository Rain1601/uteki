"""Curated mock fixtures for popular tickers.

These values are **realistic but NOT real-time** — hand-picked snapshots so
that LLM-generated research has stable, plausible numbers to cite, instead
of fabricating from training memory or seeing wild random values.

When a tool is asked about a ticker not in `FIXTURES`, it falls back to
deterministic-random data (seeded on the symbol) so the same ticker always
gets the same fake values during a session — better for repeatable demos
than pure random.

To replace with a real data source, swap the dict lookups for an `await
akshare.stock_quote(symbol)` call in the tool implementations.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any

# ──────────────────────────────────────────────────────────────────────────
# Market quote — realistic snapshot per ticker. Values are *illustrative*,
# not real-time. Updated 2025-Q4 era.
# ──────────────────────────────────────────────────────────────────────────

QUOTE_FIXTURES: dict[str, dict[str, Any]] = {
    # ── A 股动力电池 / 新能源 ──
    "300750.SZ": {
        "name": "宁德时代",
        "price": 268.40,
        "change_pct": 1.65,
        "volume": 18_592_018,
        "market_cap_cny_b": 1180.0,    # 亿元
        "pe_ttm": 22.4,
        "pb": 4.8,
        "fifty_two_week_high": 312.50,
        "fifty_two_week_low": 168.20,
        "sector": "新能源 / 动力电池",
    },
    "600519.SH": {
        "name": "贵州茅台",
        "price": 1418.0,
        "change_pct": -0.42,
        "volume": 1_820_000,
        "market_cap_cny_b": 1782.0,
        "pe_ttm": 24.1,
        "pb": 8.6,
        "fifty_two_week_high": 1820.0,
        "fifty_two_week_low": 1245.0,
        "sector": "消费 / 白酒",
    },
    "000858.SZ": {
        "name": "五粮液",
        "price": 152.30,
        "change_pct": -1.05,
        "volume": 22_500_000,
        "market_cap_cny_b": 591.2,
        "pe_ttm": 17.3,
        "pb": 4.1,
        "fifty_two_week_high": 195.4,
        "fifty_two_week_low": 132.5,
        "sector": "消费 / 白酒",
    },
    # ── 美股 大型科技 ──
    "AAPL": {
        "name": "Apple Inc.",
        "price": 234.12,
        "change_pct": 0.82,
        "volume": 48_300_000,
        "market_cap_usd_b": 3540.0,
        "pe_ttm": 35.6,
        "pb": 55.2,
        "fifty_two_week_high": 260.10,
        "fifty_two_week_low": 164.07,
        "sector": "Tech / Consumer Electronics",
    },
    "NVDA": {
        "name": "NVIDIA",
        "price": 142.55,
        "change_pct": -1.24,
        "volume": 215_400_000,
        "market_cap_usd_b": 3500.0,
        "pe_ttm": 56.3,
        "pb": 48.7,
        "fifty_two_week_high": 153.13,
        "fifty_two_week_low": 75.61,
        "sector": "Semiconductor",
    },
    "TSLA": {
        "name": "Tesla",
        "price": 359.92,
        "change_pct": 2.14,
        "volume": 92_100_000,
        "market_cap_usd_b": 1146.0,
        "pe_ttm": 92.7,
        "pb": 17.2,
        "fifty_two_week_high": 488.54,
        "fifty_two_week_low": 138.80,
        "sector": "Auto / EV",
    },
    "MSFT": {
        "name": "Microsoft",
        "price": 442.18,
        "change_pct": 0.35,
        "volume": 19_800_000,
        "market_cap_usd_b": 3300.0,
        "pe_ttm": 38.4,
        "pb": 12.1,
        "fifty_two_week_high": 468.35,
        "fifty_two_week_low": 366.50,
        "sector": "Tech / Software",
    },
    # ── ETF ──
    "SPY": {
        "name": "SPDR S&P 500",
        "price": 612.45,
        "change_pct": 0.18,
        "volume": 38_700_000,
        "aum_usd_b": 615.0,
        "pe_ttm": 27.0,
        "pb": 5.0,
        "fifty_two_week_high": 624.10,
        "fifty_two_week_low": 481.80,
        "sector": "Broad-market ETF",
    },
    "QQQ": {
        "name": "Invesco QQQ Trust",
        "price": 528.10,
        "change_pct": 0.62,
        "volume": 32_500_000,
        "aum_usd_b": 320.0,
        "pe_ttm": 32.0,
        "pb": 8.6,
        "fifty_two_week_high": 540.20,
        "fifty_two_week_low": 402.30,
        "sector": "Tech-heavy ETF",
    },
    "SOXX": {
        "name": "iShares Semi ETF",
        "price": 245.80,
        "change_pct": -1.85,
        "volume": 4_800_000,
        "aum_usd_b": 14.2,
        "pe_ttm": 38.5,
        "pb": 6.4,
        "fifty_two_week_high": 286.30,
        "fifty_two_week_low": 169.10,
        "sector": "Semiconductor ETF",
    },
    "510300.SH": {
        "name": "沪深300 ETF",
        "price": 4.12,
        "change_pct": 0.45,
        "volume": 280_000_000,
        "aum_cny_b": 1450.0,
        "pe_ttm": 13.2,
        "pb": 1.5,
        "fifty_two_week_high": 4.35,
        "fifty_two_week_low": 3.21,
        "sector": "宽基 ETF",
    },
}


def quote_for(symbol: str) -> dict[str, Any]:
    """Return a quote snapshot for the given symbol.

    Known tickers → curated fixture (stable across calls).
    Unknown tickers → deterministic-random based on symbol hash (still stable
    within a session, but not realistic).
    """
    if symbol in QUOTE_FIXTURES:
        return {**QUOTE_FIXTURES[symbol], "symbol": symbol, "source": "mock-fixture"}

    seed = int(hashlib.md5(symbol.encode("utf-8")).hexdigest()[:8], 16)
    rng = random.Random(seed)
    price = round(rng.uniform(10, 500), 2)
    change = round(rng.uniform(-5, 5), 2)
    return {
        "symbol": symbol,
        "name": f"Unknown ({symbol})",
        "price": price,
        "change_pct": change,
        "volume": rng.randint(100_000, 10_000_000),
        "pe_ttm": round(rng.uniform(8, 60), 1),
        "source": "mock-random",
    }


# ──────────────────────────────────────────────────────────────────────────
# Financials — last N annual / quarterly periods per ticker.
# Numbers in 亿元 (CNY) for A 股，USD billions for US 股.
# ──────────────────────────────────────────────────────────────────────────

FINANCIALS_FIXTURES: dict[str, dict[str, list[dict[str, Any]]]] = {
    "300750.SZ": {
        "annual": [
            {"period_label": "2022", "revenue_b": 3285.9, "net_profit_b": 307.3,  "gross_margin": 0.205, "roe": 0.222, "eps": 12.58, "yoy_revenue": 1.522, "yoy_net_profit": 0.927},
            {"period_label": "2023", "revenue_b": 4009.2, "net_profit_b": 441.2,  "gross_margin": 0.227, "roe": 0.232, "eps": 18.06, "yoy_revenue": 0.220, "yoy_net_profit": 0.436},
            {"period_label": "2024", "revenue_b": 3620.4, "net_profit_b": 507.5,  "gross_margin": 0.241, "roe": 0.211, "eps": 20.78, "yoy_revenue": -0.097, "yoy_net_profit": 0.150},
        ],
        "quarterly": [
            {"period_label": "2024Q2", "revenue_b": 869.0, "net_profit_b": 123.4, "gross_margin": 0.265, "eps": 5.05},
            {"period_label": "2024Q3", "revenue_b": 922.8, "net_profit_b": 131.4, "gross_margin": 0.314, "eps": 5.38},
            {"period_label": "2024Q4", "revenue_b": 1031.0, "net_profit_b": 147.4, "gross_margin": 0.260, "eps": 6.03},
            {"period_label": "2025Q1", "revenue_b": 847.0, "net_profit_b": 139.6, "gross_margin": 0.241, "eps": 5.71},
        ],
    },
    "600519.SH": {
        "annual": [
            {"period_label": "2022", "revenue_b": 1275.5, "net_profit_b": 627.2, "gross_margin": 0.917, "roe": 0.310, "eps": 49.93},
            {"period_label": "2023", "revenue_b": 1505.6, "net_profit_b": 747.3, "gross_margin": 0.919, "roe": 0.326, "eps": 59.49},
            {"period_label": "2024", "revenue_b": 1741.4, "net_profit_b": 862.3, "gross_margin": 0.920, "roe": 0.333, "eps": 68.64},
        ],
    },
    "AAPL": {
        "annual": [
            {"period_label": "FY2022", "revenue_b": 394.3, "net_profit_b": 99.8,  "gross_margin": 0.433, "roe": 1.747, "eps": 6.11},
            {"period_label": "FY2023", "revenue_b": 383.3, "net_profit_b": 97.0,  "gross_margin": 0.444, "roe": 1.564, "eps": 6.13},
            {"period_label": "FY2024", "revenue_b": 391.0, "net_profit_b": 93.7,  "gross_margin": 0.462, "roe": 1.643, "eps": 6.08},
        ],
    },
    "NVDA": {
        "annual": [
            {"period_label": "FY2023", "revenue_b": 27.0,  "net_profit_b": 4.4,   "gross_margin": 0.563, "roe": 0.197, "eps": 0.17},
            {"period_label": "FY2024", "revenue_b": 60.9,  "net_profit_b": 29.8,  "gross_margin": 0.726, "roe": 0.690, "eps": 1.19},
            {"period_label": "FY2025", "revenue_b": 130.5, "net_profit_b": 72.9,  "gross_margin": 0.749, "roe": 0.910, "eps": 2.94},
        ],
    },
}


def financials_for(symbol: str, period: str, years: int) -> list[dict[str, Any]]:
    """Return up to `years` rows of financial periods."""
    bundle = FINANCIALS_FIXTURES.get(symbol)
    if bundle is None:
        # Deterministic-random fallback
        seed = int(hashlib.md5(f"fin:{symbol}:{period}".encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        rows = []
        base_year = 2025
        for i in range(years):
            yr = base_year - (years - 1 - i)
            label = f"{yr}" if period == "annual" else f"{yr}Q4"
            rev = round(rng.uniform(50, 500), 1)
            net = round(rev * rng.uniform(0.05, 0.25), 1)
            rows.append({
                "period_label": label,
                "revenue_b": rev,
                "net_profit_b": net,
                "gross_margin": round(rng.uniform(0.15, 0.50), 3),
                "roe": round(rng.uniform(0.08, 0.30), 3),
                "eps": round(rng.uniform(0.5, 8.0), 2),
                "source": "mock-random",
            })
        return rows

    series = bundle.get(period) or bundle.get("annual") or []
    return list(series[-years:])
