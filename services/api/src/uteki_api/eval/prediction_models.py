"""015 PR ε MVP · Prediction table — ground-truth backtest layer.

Each completed company_research_pipeline run that contains a BUY/WATCH/AVOID
verdict writes one Prediction row. The row freezes the (ticker, action,
conviction, t0_price) tuple at run-completion time so we can later compare
against the actual stock movement at 30 / 90 / 180 days.

Design notes:

- ``run_id`` is the primary key. One prediction per run.
- Not user_id-partitioned because backtest aggregates need cross-user
  rollups by skill_version (admin / system view). User_id is still
  recorded for filtering on the per-user UI.
- ``t0_price`` is the spot when the prediction was *made*. Without this
  snapshot, future scoring can't compute relative returns since stock
  prices update every minute.
- ``horizons_to_score`` and ``outcomes`` are placeholders for the daily
  scoring cron (PR ε.2). MVP keeps them empty; the API just renders
  "29 days left" countdown from ``t0`` until the cron lands.
- ``hit`` definition (per 015 design.md D1): BUY hit ⇔ stock_pct ≥ spy_pct;
  AVOID hit ⇔ spy_pct ≥ stock_pct; WATCH is recorded but never enters
  the hit-rate denominator.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class Prediction(SQLModel, table=True):
    __tablename__ = "prediction"

    run_id: str = Field(primary_key=True, foreign_key="run.id", max_length=64)
    user_id: str = Field(max_length=64, index=True)
    skill_name: str = Field(max_length=64, index=True)
    skill_version: str | None = Field(default=None, max_length=32, index=True)

    ticker: str = Field(max_length=16, index=True)
    action: str = Field(max_length=8, index=True)  # "BUY" | "WATCH" | "AVOID"
    conviction: float = Field(default=0.0)
    quality_verdict: str | None = Field(default=None, max_length=16)
    # "EXCELLENT" | "GOOD" | "MEDIOCRE" | "POOR" — pulled from final-verdict.json

    t0: float = Field(default_factory=time.time, index=True)
    t0_price: float | None = Field(default=None)
    # None means the market_quote at run finish failed; the widget will
    # render "entry price unavailable" rather than showing a fake delta.
    t0_currency: str = Field(default="USD", max_length=8)

    # Horizons-to-score and outcomes — populated by the daily cron (PR ε.2).
    # Shape (when populated):
    #   {"30d":  {"price": 245.6, "spy_price": 612.0, "stock_pct": +5.2,
    #             "spy_pct": +2.1, "hit": True,  "scored_at": 1782000000},
    #    "90d":  {...}, "180d": {...}}
    # MVP leaves this empty {} — countdown timers come from t0 + horizon.
    horizons_to_score: list[int] = Field(
        default_factory=lambda: [30, 90, 180], sa_column=Column(JSON)
    )
    outcomes: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    created_at: float = Field(default_factory=time.time)
