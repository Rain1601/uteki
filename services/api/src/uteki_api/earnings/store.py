"""EarningsStore — DB facade over the ``earnings_event`` table.

Three patterns matter:

- ``next_scheduled(symbol)`` — used by the UI countdown across watchlist,
  /tasks/trg-news-002 ticker rail, and /admin/companies. Returns the
  nearest ``status=scheduled`` event for the symbol (or None).
- ``find_near_date(symbol, when, window_days)`` — for the P9.4 SEC
  auto-link: when a fresh 8-K Item 2.02 lands, this finds the scheduled
  event we should flip to delivered.
- ``prior_delivered(symbol, limit)`` — quick history lookup for the
  earnings detail surfaces.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from uteki_api.earnings.models import EarningsEvent


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


class EarningsStore(ABC):
    @abstractmethod
    def list(
        self,
        db: Session,
        *,
        symbol: str | None = None,
        status: str | None = None,
        upcoming_only: bool = False,
    ) -> list[EarningsEvent]: ...

    @abstractmethod
    def get(self, db: Session, event_id: str) -> EarningsEvent | None: ...

    @abstractmethod
    def upsert(
        self,
        db: Session,
        *,
        symbol: str,
        fiscal_period: str,
        expected_date: datetime,
        bmo_amc: str = "DURING",
        status: str = "scheduled",
        eps_estimate: float | None = None,
        eps_actual: float | None = None,
        revenue_estimate: float | None = None,
        revenue_actual: float | None = None,
        delivered_at: datetime | None = None,
        related_accession: str | None = None,
        call_url: str | None = None,
        notes: str = "",
    ) -> EarningsEvent: ...

    @abstractmethod
    def update(self, db: Session, event_id: str, **fields: object) -> EarningsEvent | None: ...

    @abstractmethod
    def delete(self, db: Session, event_id: str) -> bool: ...

    @abstractmethod
    def next_scheduled(self, db: Session, symbol: str) -> EarningsEvent | None: ...

    @abstractmethod
    def next_scheduled_map(self, db: Session) -> dict[str, EarningsEvent]: ...

    @abstractmethod
    def prior_delivered(
        self, db: Session, symbol: str, *, limit: int = 8
    ) -> list[EarningsEvent]: ...

    @abstractmethod
    def find_near_date(
        self,
        db: Session,
        symbol: str,
        when: datetime,
        *,
        window_days: int = 21,
    ) -> EarningsEvent | None:
        """Find a scheduled event for ``symbol`` whose expected_date is
        within ``±window_days`` of ``when``. Used for P9.4 auto-link
        from a fresh SEC 8-K Item 2.02 filing."""
        ...


class SqlEarningsStore(EarningsStore):
    def list(
        self,
        db: Session,
        *,
        symbol: str | None = None,
        status: str | None = None,
        upcoming_only: bool = False,
    ) -> list[EarningsEvent]:
        stmt = select(EarningsEvent)
        if symbol:
            stmt = stmt.where(EarningsEvent.symbol == _normalize_symbol(symbol))
        if status:
            stmt = stmt.where(EarningsEvent.status == status)
        if upcoming_only:
            stmt = stmt.where(EarningsEvent.expected_date >= _utcnow())
            stmt = stmt.where(EarningsEvent.status == "scheduled")
            stmt = stmt.order_by(EarningsEvent.expected_date.asc())  # type: ignore[attr-defined]
        else:
            stmt = stmt.order_by(EarningsEvent.expected_date.desc())  # type: ignore[attr-defined]
        return list(db.exec(stmt).all())

    def get(self, db: Session, event_id: str) -> EarningsEvent | None:
        return db.get(EarningsEvent, event_id)

    def upsert(
        self,
        db: Session,
        *,
        symbol: str,
        fiscal_period: str,
        expected_date: datetime,
        bmo_amc: str = "DURING",
        status: str = "scheduled",
        eps_estimate: float | None = None,
        eps_actual: float | None = None,
        revenue_estimate: float | None = None,
        revenue_actual: float | None = None,
        delivered_at: datetime | None = None,
        related_accession: str | None = None,
        call_url: str | None = None,
        notes: str = "",
    ) -> EarningsEvent:
        normalized = _normalize_symbol(symbol)
        # UniqueConstraint on (symbol, fiscal_period) — look up existing.
        existing = db.exec(
            select(EarningsEvent).where(
                EarningsEvent.symbol == normalized,
                EarningsEvent.fiscal_period == fiscal_period,
            )
        ).first()
        now = _utcnow()
        if existing is None:
            ev = EarningsEvent(
                id=_new_id(),
                symbol=normalized,
                fiscal_period=fiscal_period,
                expected_date=expected_date,
                bmo_amc=bmo_amc,
                status=status,
                eps_estimate=eps_estimate,
                eps_actual=eps_actual,
                revenue_estimate=revenue_estimate,
                revenue_actual=revenue_actual,
                delivered_at=delivered_at,
                related_accession=related_accession,
                call_url=call_url,
                notes=notes,
                created_at=now,
                updated_at=now,
            )
        else:
            existing.expected_date = expected_date
            existing.bmo_amc = bmo_amc
            existing.status = status
            existing.eps_estimate = eps_estimate
            existing.eps_actual = eps_actual
            existing.revenue_estimate = revenue_estimate
            existing.revenue_actual = revenue_actual
            existing.delivered_at = delivered_at
            existing.related_accession = related_accession
            existing.call_url = call_url
            existing.notes = notes
            existing.updated_at = now
            ev = existing
        db.add(ev)
        db.commit()
        db.refresh(ev)
        return ev

    def update(
        self, db: Session, event_id: str, **fields: object
    ) -> EarningsEvent | None:
        ev = db.get(EarningsEvent, event_id)
        if ev is None:
            return None
        for key, value in fields.items():
            setattr(ev, key, value)
        ev.updated_at = _utcnow()
        db.add(ev)
        db.commit()
        db.refresh(ev)
        return ev

    def delete(self, db: Session, event_id: str) -> bool:
        ev = db.get(EarningsEvent, event_id)
        if ev is None:
            return False
        db.delete(ev)
        db.commit()
        return True

    def next_scheduled(self, db: Session, symbol: str) -> EarningsEvent | None:
        return db.exec(
            select(EarningsEvent)
            .where(EarningsEvent.symbol == _normalize_symbol(symbol))
            .where(EarningsEvent.status == "scheduled")
            .where(EarningsEvent.expected_date >= _utcnow())
            .order_by(EarningsEvent.expected_date.asc())  # type: ignore[attr-defined]
        ).first()

    def next_scheduled_map(self, db: Session) -> dict[str, EarningsEvent]:
        """Return {symbol → nearest upcoming event} for everything that
        has one. Single query so the UI doesn't N+1 the watchlist."""
        rows = db.exec(
            select(EarningsEvent)
            .where(EarningsEvent.status == "scheduled")
            .where(EarningsEvent.expected_date >= _utcnow())
            .order_by(EarningsEvent.expected_date.asc())  # type: ignore[attr-defined]
        ).all()
        out: dict[str, EarningsEvent] = {}
        for ev in rows:
            if ev.symbol not in out:
                out[ev.symbol] = ev
        return out

    def prior_delivered(
        self, db: Session, symbol: str, *, limit: int = 8
    ) -> list[EarningsEvent]:
        return list(
            db.exec(
                select(EarningsEvent)
                .where(EarningsEvent.symbol == _normalize_symbol(symbol))
                .where(EarningsEvent.status == "delivered")
                .order_by(EarningsEvent.expected_date.desc())  # type: ignore[attr-defined]
                .limit(limit)
            ).all()
        )

    def find_near_date(
        self,
        db: Session,
        symbol: str,
        when: datetime,
        *,
        window_days: int = 21,
    ) -> EarningsEvent | None:
        lo = when - timedelta(days=window_days)
        hi = when + timedelta(days=window_days)
        return db.exec(
            select(EarningsEvent)
            .where(EarningsEvent.symbol == _normalize_symbol(symbol))
            .where(EarningsEvent.status == "scheduled")
            .where(EarningsEvent.expected_date >= lo)
            .where(EarningsEvent.expected_date <= hi)
            .order_by(EarningsEvent.expected_date.asc())  # type: ignore[attr-defined]
        ).first()


default_earnings_store: EarningsStore = SqlEarningsStore()
