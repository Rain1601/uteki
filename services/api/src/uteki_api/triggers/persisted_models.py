"""SQLModel table for persisted triggers.

Replaces the in-memory ``CronTrigger`` / ``EventTrigger`` registry in
``triggers/registry.py`` and the hardcoded fixture in
``apps/web/lib/triggers.ts``. The ID stays human-readable
(``trg-news-001`` / ``trg-news-002`` etc.) so existing trigger_hit rows
keep their foreign-key meaning across the migration.

Cadence model:

- ``cadence_minutes`` is the polling interval used by the scheduler
  (P10.2). 0 / None means event-driven only (no polling).
- ``boost_in_earnings_window_minutes`` is the cadence that takes over
  when a watchlist company has an EarningsEvent in
  ``earnings_window_hours`` ± now. Lets us hammer SEC every 5 minutes
  on earnings day without burning quota the other 363 days.

State (``last_check_at`` / ``last_triggered_at`` / ``next_check_at`` /
``last_status``) is updated by the scheduler. Admin can read but
shouldn't write — these are runtime fields.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class Trigger(SQLModel, table=True):
    __tablename__ = "trigger"

    id: str = Field(primary_key=True, max_length=64)
    name: str = Field(max_length=200)
    kind: str = Field(max_length=16)  # news | earnings | event | price | schedule

    skill: str = Field(default="uteki", max_length=64)
    condition: str = Field(default="", max_length=1024)

    # CSV of company.symbol values; empty = applies to all watchlist.
    watchlist_symbols: str = Field(default="", max_length=512)

    # Cadence. minutes==0 means event-driven (no scheduler polling).
    cadence_minutes: int = Field(default=60)
    cadence_text: str = Field(default="", max_length=64)  # display string

    # Earnings-window awareness — bump polling when a tracked company's
    # earnings event is within ``earnings_window_hours`` hours of now.
    earnings_window_hours: int = Field(default=0)  # 0 = disabled
    boost_in_earnings_window_minutes: int = Field(default=0)

    enabled: bool = Field(default=True, index=True)

    # Runtime state — written by the scheduler.
    last_check_at: datetime | None = Field(default=None)
    last_triggered_at: datetime | None = Field(default=None)
    next_check_at: datetime | None = Field(default=None)
    last_status: str = Field(default="idle", max_length=16)
    # idle | listening | ok | error

    sort_order: int = Field(default=0)
    created_at: datetime
    updated_at: datetime
