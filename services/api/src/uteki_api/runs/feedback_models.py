"""013 · RunFeedback — per-(user, run) human label row.

Shape parallels ``news_feedback`` but with extra columns the news case
doesn't need (free-text notes, the "needs re-review" flag).

Composite primary key ``(user_id, run_id)`` enforces "one row per
annotator per run" — re-rating just updates ``rating`` / ``notes`` in
place, no append-only history. If we ever want trajectory of edits, add
a sibling ``run_feedback_log`` write-once table; for now the simple
single-row model matches how news_feedback works.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlmodel import Field, SQLModel

RunRating = Literal["up", "down"]

# 013 δ.1 — two annotation modes coexist:
#
# - "blind"   — the API hides ``auto_score`` until the annotator submits
#               a rating. Calibration-grade data: an annotator's label
#               cannot be anchored by the model's score.
# - "review"  — the API reveals ``auto_score`` immediately. Annotator
#               functions as a reviewer of the judge's output: accept /
#               reject / edit. Faster but contaminated for calibration
#               (Phase 2's Cohen's-κ cron drops these rows).
RatingMode = Literal["blind", "review"]


class RunFeedback(SQLModel, table=True):
    """One annotator's rating on one run.

    ``runs:annotate`` permission gates the API surface (see
    ``auth/roles.PERM_ANNOTATE_RUNS``). The model itself stores raw rows;
    visibility / score-masking is the API layer's job.
    """

    __tablename__ = "run_feedback"

    user_id: str = Field(primary_key=True, foreign_key="user.id", max_length=64)
    run_id: str = Field(primary_key=True, foreign_key="run.id", max_length=64)
    rating: str = Field(max_length=8)  # "up" | "down"
    notes: str = Field(default="", max_length=4096)
    # 013 — true when the annotator wants this run pulled into a re-review
    # queue. Today that queue is just ``GET /api/runs?flagged=1``; Phase 2
    # will hang a proper /admin/review page off the same column.
    flagged: bool = Field(default=False, index=True)
    # 013 δ.1 — which annotation mode produced this row. Determines
    # whether the auto-score was visible at label time.
    # Default ``blind`` so existing rows (pre-δ.1) are treated as
    # calibration-grade, which is the safer assumption when we don't
    # know how the annotator was seeing the data.
    rating_mode: str = Field(default="blind", max_length=8, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
