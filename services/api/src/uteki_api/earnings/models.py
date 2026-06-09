"""SQLModel table for earnings calendar events.

Status transitions:

    scheduled  → delivered    (filing landed; auto-set in P9.4)
    scheduled  → missed       (expected date passed without a filing)
    delivered  ↔ scheduled    (admin can correct a wrong link)

``expected_date`` is intentionally a ``datetime`` (not a ``date``) so
the BMO / AMC / DURING flag can shift the timestamp ±a few hours when
display logic wants finer ordering. Most consumers just look at the
date portion.

``related_accession`` is a soft reference to ``news_article.id`` for
the linked 8-K Item 2.02 — kept as a plain string rather than an FK so
the DB ingest order doesn't constrain us (admin can set the event before
the 8-K lands, and the auto-link runs later).
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel, UniqueConstraint


class EarningsEvent(SQLModel, table=True):
    __tablename__ = "earnings_event"
    # One event per (symbol, fiscal_period) — re-creating wipes the old.
    __table_args__ = (UniqueConstraint("symbol", "fiscal_period"),)

    id: str = Field(primary_key=True, max_length=64)
    symbol: str = Field(foreign_key="company.symbol", index=True, max_length=16)
    fiscal_period: str = Field(max_length=24)  # e.g. "FY2026 Q3" / "FY2026 Annual"
    expected_date: datetime = Field(index=True)
    bmo_amc: str = Field(default="DURING", max_length=8)  # BMO | AMC | DURING

    status: str = Field(default="scheduled", index=True, max_length=12)
    # scheduled | delivered | missed

    delivered_at: datetime | None = Field(default=None)
    related_accession: str | None = Field(default=None, max_length=64)

    eps_estimate: float | None = Field(default=None)
    eps_actual: float | None = Field(default=None)
    revenue_estimate: float | None = Field(default=None)  # in millions USD
    revenue_actual: float | None = Field(default=None)

    call_url: str | None = Field(default=None, max_length=512)
    notes: str = Field(default="", max_length=2048)

    created_at: datetime
    updated_at: datetime
