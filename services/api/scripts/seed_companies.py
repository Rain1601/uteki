"""Seed the company watchlist with the 6 demo tickers that the
/company-agent page used to hardcode in its INITIAL_WATCHLIST.

Idempotent — upsert by symbol. Re-running won't duplicate rows;
``notes`` and updated fields will be overwritten with the values below
unless you remove them from the spec list first.

Usage (from services/api/):
    uv run python scripts/seed_companies.py
"""

from __future__ import annotations

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "src"))

from sqlmodel import Session  # noqa: E402

from uteki_api.companies.store import default_company_store as cs  # noqa: E402
from uteki_api.core.db import engine, init_db  # noqa: E402


# Values match apps/web/app/(app)/company-agent/page.tsx :: INITIAL_WATCHLIST.
# CIKs come from SEC EDGAR (https://www.sec.gov/cgi-bin/browse-edgar).
SEED: list[dict] = [
    {
        "symbol": "GOOGL",
        "name": "Alphabet Inc.",
        "market": "US",
        "sector": "Internet",
        "peers": ["META", "MSFT", "AMZN"],
        "cik": "0001652044",
        "verdict": "BUY",
        "conviction": 0.7,
    },
    {
        "symbol": "TSM",
        "name": "Taiwan Semiconductor Manufacturing",
        "market": "TW",
        "sector": "Semiconductors",
        "peers": ["NVDA", "ASML", "AMD"],
        "cik": "0001046179",
        "verdict": "WATCH",
        "conviction": 0.45,
    },
    {
        "symbol": "NVDA",
        "name": "NVIDIA Corp.",
        "market": "US",
        "sector": "AI Chips",
        "peers": ["AMD", "AVGO", "INTC"],
        "cik": "0001045810",
        "verdict": "WATCH",
        "conviction": 0.55,
    },
    {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "market": "US",
        "sector": "Consumer Tech",
        "peers": ["MSFT", "GOOGL", "META"],
        "cik": "0000320193",
        "verdict": "WATCH",
        "conviction": 0.5,
    },
    {
        "symbol": "MSFT",
        "name": "Microsoft Corp.",
        "market": "US",
        "sector": "Cloud",
        "peers": ["GOOGL", "AMZN", "ORCL"],
        "cik": "0000789019",
        "verdict": "UNRATED",
    },
    {
        "symbol": "TSLA",
        "name": "Tesla, Inc.",
        "market": "US",
        "sector": "Auto",
        "peers": ["GM", "F", "RIVN"],
        "cik": "0001318605",
        "verdict": "AVOID",
        "conviction": 0.35,
    },
]


def main() -> int:
    init_db()
    with Session(engine) as db:
        for spec in SEED:
            company = cs.upsert(
                db,
                symbol=spec["symbol"],
                name=spec["name"],
                market=spec.get("market", "US"),
                sector=spec.get("sector", ""),
                peers=",".join(spec.get("peers", [])),
                cik=spec.get("cik"),
                ir_rss_url=spec.get("ir_rss_url"),
                watch=True,
                verdict=spec.get("verdict", "UNRATED"),
                conviction=spec.get("conviction"),
                notes=spec.get("notes", ""),
            )
            print(f"  · {company.symbol:<8} {company.name}")
    print(f"✓ seeded {len(SEED)} companies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
