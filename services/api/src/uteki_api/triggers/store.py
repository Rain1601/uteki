"""TriggerStore — DB facade over the ``trigger`` table.

Pattern mirrors UserStore / CompanyStore / EarningsStore. ID stays
human-readable for fixture compatibility (trg-news-001 / etc) — the
caller passes it on create; the store doesn't generate one.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime

from sqlmodel import Session, select

from uteki_api.triggers.persisted_models import Trigger


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TriggerStore(ABC):
    @abstractmethod
    def list(
        self, db: Session, *, enabled_only: bool = False
    ) -> list[Trigger]: ...

    @abstractmethod
    def get(self, db: Session, trigger_id: str) -> Trigger | None: ...

    @abstractmethod
    def upsert(
        self,
        db: Session,
        *,
        id: str,
        name: str,
        kind: str,
        skill: str = "uteki",
        condition: str = "",
        watchlist_symbols: str = "",
        cadence_minutes: int = 60,
        cadence_text: str = "",
        earnings_window_hours: int = 0,
        boost_in_earnings_window_minutes: int = 0,
        enabled: bool = True,
        sort_order: int = 0,
    ) -> Trigger: ...

    @abstractmethod
    def update(
        self, db: Session, trigger_id: str, **fields: object
    ) -> Trigger | None: ...

    @abstractmethod
    def delete(self, db: Session, trigger_id: str) -> bool: ...

    @abstractmethod
    def mark_state(
        self,
        db: Session,
        trigger_id: str,
        *,
        last_check_at: datetime | None = None,
        last_triggered_at: datetime | None = None,
        next_check_at: datetime | None = None,
        last_status: str | None = None,
    ) -> Trigger | None:
        """Scheduler-only state update — bypasses ``updated_at`` bump."""
        ...


class SqlTriggerStore(TriggerStore):
    def list(
        self, db: Session, *, enabled_only: bool = False
    ) -> list[Trigger]:
        stmt = select(Trigger)
        if enabled_only:
            stmt = stmt.where(Trigger.enabled == True)  # noqa: E712
        return list(db.exec(stmt.order_by(Trigger.sort_order, Trigger.id)).all())

    def get(self, db: Session, trigger_id: str) -> Trigger | None:
        return db.get(Trigger, trigger_id)

    def upsert(
        self,
        db: Session,
        *,
        id: str,
        name: str,
        kind: str,
        skill: str = "uteki",
        condition: str = "",
        watchlist_symbols: str = "",
        cadence_minutes: int = 60,
        cadence_text: str = "",
        earnings_window_hours: int = 0,
        boost_in_earnings_window_minutes: int = 0,
        enabled: bool = True,
        sort_order: int = 0,
    ) -> Trigger:
        existing = db.get(Trigger, id)
        now = _utcnow()
        if existing is None:
            trig = Trigger(
                id=id,
                name=name,
                kind=kind,
                skill=skill,
                condition=condition,
                watchlist_symbols=watchlist_symbols,
                cadence_minutes=cadence_minutes,
                cadence_text=cadence_text,
                earnings_window_hours=earnings_window_hours,
                boost_in_earnings_window_minutes=boost_in_earnings_window_minutes,
                enabled=enabled,
                sort_order=sort_order,
                created_at=now,
                updated_at=now,
            )
        else:
            existing.name = name
            existing.kind = kind
            existing.skill = skill
            existing.condition = condition
            existing.watchlist_symbols = watchlist_symbols
            existing.cadence_minutes = cadence_minutes
            existing.cadence_text = cadence_text
            existing.earnings_window_hours = earnings_window_hours
            existing.boost_in_earnings_window_minutes = boost_in_earnings_window_minutes
            existing.enabled = enabled
            existing.sort_order = sort_order
            existing.updated_at = now
            trig = existing
        db.add(trig)
        db.commit()
        db.refresh(trig)
        return trig

    def update(
        self, db: Session, trigger_id: str, **fields: object
    ) -> Trigger | None:
        trig = db.get(Trigger, trigger_id)
        if trig is None:
            return None
        for key, value in fields.items():
            setattr(trig, key, value)
        trig.updated_at = _utcnow()
        db.add(trig)
        db.commit()
        db.refresh(trig)
        return trig

    def delete(self, db: Session, trigger_id: str) -> bool:
        trig = db.get(Trigger, trigger_id)
        if trig is None:
            return False
        db.delete(trig)
        db.commit()
        return True

    def mark_state(
        self,
        db: Session,
        trigger_id: str,
        *,
        last_check_at: datetime | None = None,
        last_triggered_at: datetime | None = None,
        next_check_at: datetime | None = None,
        last_status: str | None = None,
    ) -> Trigger | None:
        trig = db.get(Trigger, trigger_id)
        if trig is None:
            return None
        if last_check_at is not None:
            trig.last_check_at = last_check_at
        if last_triggered_at is not None:
            trig.last_triggered_at = last_triggered_at
        if next_check_at is not None:
            trig.next_check_at = next_check_at
        if last_status is not None:
            trig.last_status = last_status
        # No updated_at bump — this is a runtime/state edit, not an
        # admin edit. Helps the UI distinguish "I changed config" vs
        # "scheduler just ran".
        db.add(trig)
        db.commit()
        db.refresh(trig)
        return trig


default_trigger_store: TriggerStore = SqlTriggerStore()
