"""015 PR ε MVP · Prediction CRUD.

Thin SQLModel store over the ``prediction`` table. Reads are user-scoped
(the API layer enforces ownership); writes are dispatcher-only.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from uteki_api.eval.prediction_models import Prediction


class PredictionStore:
    def get(self, db: Session, run_id: str) -> Prediction | None:
        return db.get(Prediction, run_id)

    def upsert(
        self,
        db: Session,
        *,
        run_id: str,
        user_id: str,
        skill_name: str,
        skill_version: str | None,
        ticker: str,
        action: str,
        conviction: float,
        quality_verdict: str | None,
        t0: float,
        t0_price: float | None,
        t0_currency: str = "USD",
    ) -> Prediction:
        existing = self.get(db, run_id)
        if existing is None:
            row = Prediction(
                run_id=run_id,
                user_id=user_id,
                skill_name=skill_name,
                skill_version=skill_version,
                ticker=ticker,
                action=action,
                conviction=conviction,
                quality_verdict=quality_verdict,
                t0=t0,
                t0_price=t0_price,
                t0_currency=t0_currency,
            )
            db.add(row)
        else:
            # Re-running the same run shouldn't change t0 / t0_price (those
            # are the immutable "what we believed at decision time"). But
            # we let action / conviction update — the dispatcher might be
            # re-running because the verdict re-derivation logic changed.
            existing.action = action
            existing.conviction = conviction
            existing.quality_verdict = quality_verdict
            db.add(existing)
            row = existing
        db.commit()
        db.refresh(row)
        return row

    def list_recent(
        self,
        db: Session,
        *,
        ticker: str | None = None,
        skill_name: str | None = None,
        skill_version: str | None = None,
        action: str | None = None,
        limit: int = 200,
    ) -> list[Prediction]:
        stmt = select(Prediction)
        if ticker is not None:
            stmt = stmt.where(Prediction.ticker == ticker)
        if skill_name is not None:
            stmt = stmt.where(Prediction.skill_name == skill_name)
        if skill_version is not None:
            stmt = stmt.where(Prediction.skill_version == skill_version)
        if action is not None:
            stmt = stmt.where(Prediction.action == action)
        stmt = stmt.order_by(Prediction.t0.desc()).limit(limit)  # type: ignore[attr-defined]
        return list(db.exec(stmt).all())

    def update_outcomes(
        self, db: Session, run_id: str, outcomes: dict[str, Any]
    ) -> Prediction | None:
        """Cron entry point (PR ε.2). MVP doesn't call this — included for
        the contract so the cron can land without touching the store."""
        row = self.get(db, run_id)
        if row is None:
            return None
        row.outcomes = outcomes
        db.add(row)
        db.commit()
        db.refresh(row)
        return row


default_prediction_store = PredictionStore()
