"""013 · RunFeedback store — thin CRUD over the (user, run) composite-key
table. Mirrors the news_feedback store but adds the ``flagged`` queue
helpers the eval UI uses.

Caller is responsible for the ``runs:annotate`` permission check (the
API layer does that via ``Depends(require_perm(...))``). This module
just translates calls into DB rows — no auth logic.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session, select

from uteki_api.runs.feedback_models import RunFeedback


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class RunFeedbackStore:
    """Synchronous store; one row per (user_id, run_id).

    Re-labeling is upsert: ``rating`` / ``notes`` / ``flagged`` get
    overwritten on subsequent calls, never appended. Justification: a
    single annotator changing their mind is the common case; if we ever
    want an audit log of edits, a sibling write-once table is the right
    add-on, not loosening the primary key here.
    """

    def get(
        self, db: Session, *, user_id: str, run_id: str
    ) -> RunFeedback | None:
        return db.get(RunFeedback, (user_id, run_id))

    def upsert(
        self,
        db: Session,
        *,
        user_id: str,
        run_id: str,
        rating: str,
        notes: str = "",
        flagged: bool = False,
        rating_mode: str = "blind",
    ) -> RunFeedback:
        existing = self.get(db, user_id=user_id, run_id=run_id)
        now = _utcnow()
        if existing is None:
            row = RunFeedback(
                user_id=user_id,
                run_id=run_id,
                rating=rating,
                notes=notes,
                flagged=flagged,
                rating_mode=rating_mode,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
        else:
            existing.rating = rating
            existing.notes = notes
            existing.flagged = flagged
            existing.rating_mode = rating_mode
            existing.updated_at = now
            db.add(existing)
            row = existing
        db.commit()
        db.refresh(row)
        return row

    def delete(self, db: Session, *, user_id: str, run_id: str) -> bool:
        existing = self.get(db, user_id=user_id, run_id=run_id)
        if existing is None:
            return False
        db.delete(existing)
        db.commit()
        return True

    def list_by_user(
        self, db: Session, *, user_id: str, flagged_only: bool = False, limit: int = 200
    ) -> list[RunFeedback]:
        stmt = select(RunFeedback).where(RunFeedback.user_id == user_id)
        if flagged_only:
            stmt = stmt.where(RunFeedback.flagged.is_(True))  # type: ignore[attr-defined]
        stmt = stmt.order_by(RunFeedback.updated_at.desc()).limit(limit)  # type: ignore[attr-defined]
        return list(db.exec(stmt).all())

    def list_flagged_run_ids(
        self, db: Session, *, user_id: str, limit: int = 200
    ) -> list[str]:
        """Just the run IDs ``user_id`` has flagged — what /runs?flagged=1
        consumes to AND-filter its own list query."""
        stmt = (
            select(RunFeedback.run_id)
            .where(RunFeedback.user_id == user_id)
            .where(RunFeedback.flagged.is_(True))  # type: ignore[attr-defined]
            .limit(limit)
        )
        return list(db.exec(stmt).all())


default_run_feedback_store = RunFeedbackStore()
