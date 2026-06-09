"""SQLModel table for the company watchlist.

PK is the upper-cased ticker (``AAPL`` / ``BABA`` / ``9988.HK``). Simple
and human-readable; no separate UUID. ``peers`` stays CSV to match the
NewsArticle.symbols convention.

``watch=False`` means "archived" — kept in the DB so notes and historical
verdict survive, but hidden from the research desk watchlist by default.
``DELETE /api/companies/{symbol}`` flips this flag rather than
hard-deleting, so there's no FK breakage with NewsArticle.symbols or
future research run records that name the ticker.

``cik`` and ``ir_rss_url`` are the hooks for P7 (SEC EDGAR connector) and
the optional IR RSS layer. Both nullable because non-US tickers don't
have a CIK and many companies have no IR RSS at all.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class Company(SQLModel, table=True):
    __tablename__ = "company"

    symbol: str = Field(primary_key=True, max_length=16)
    name: str = Field(max_length=200)
    market: str = Field(default="US", max_length=8)  # US | CN | HK | TW
    sector: str = Field(default="", max_length=64)
    peers: str = Field(default="", max_length=512)  # CSV of related tickers

    # News ingestion hooks (filled out via /admin/companies for P7 / P8)
    cik: str | None = Field(default=None, max_length=12)  # SEC CIK
    ir_rss_url: str | None = Field(default=None, max_length=512)

    # Watchlist + research metadata
    watch: bool = Field(default=True, index=True)
    verdict: str = Field(default="UNRATED", max_length=12)  # BUY | WATCH | AVOID | UNRATED
    conviction: float | None = Field(default=None)  # 0.0–1.0
    notes: str = Field(default="", max_length=2048)

    created_at: datetime
    updated_at: datetime
