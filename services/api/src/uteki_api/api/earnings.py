"""Earnings calendar CRUD endpoints.

- ``GET /api/earnings`` — list with symbol / status / upcoming filters;
  any authed user (the research desk and admin views both read it).
- ``GET /api/earnings/next`` — convenience map {symbol → nearest
  upcoming event} for the watchlist countdown UI.
- ``POST /api/earnings`` — upsert (symbol, fiscal_period) unique; admin.
- ``PATCH /api/earnings/{id}`` — partial update; admin.
- ``DELETE /api/earnings/{id}`` — hard delete; admin.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from uteki_api.auth.deps import current_user, require_admin
from uteki_api.core.db import get_db
from uteki_api.earnings.models import EarningsEvent
from uteki_api.earnings.store import default_earnings_store
from uteki_api.users.models import User

router = APIRouter(prefix="/api/earnings", tags=["earnings"])


# ─── Schemas ─────────────────────────────────────────────────────────


class EarningsOut(BaseModel):
    id: str
    symbol: str
    fiscal_period: str
    expected_date: str
    bmo_amc: str
    status: str
    delivered_at: str | None
    related_accession: str | None
    eps_estimate: float | None
    eps_actual: float | None
    revenue_estimate: float | None
    revenue_actual: float | None
    call_url: str | None
    notes: str
    created_at: str
    updated_at: str


class EarningsCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=16)
    fiscal_period: str = Field(..., min_length=1, max_length=24)
    expected_date: datetime
    bmo_amc: str = Field("DURING", pattern=r"^(BMO|AMC|DURING)$")
    status: str = Field("scheduled", pattern=r"^(scheduled|delivered|missed)$")
    eps_estimate: float | None = None
    eps_actual: float | None = None
    revenue_estimate: float | None = None
    revenue_actual: float | None = None
    delivered_at: datetime | None = None
    related_accession: str | None = Field(default=None, max_length=64)
    call_url: str | None = Field(default=None, max_length=512)
    notes: str = ""


class EarningsUpdate(BaseModel):
    fiscal_period: str | None = Field(default=None, max_length=24)
    expected_date: datetime | None = None
    bmo_amc: str | None = Field(default=None, pattern=r"^(BMO|AMC|DURING)$")
    status: str | None = Field(default=None, pattern=r"^(scheduled|delivered|missed)$")
    eps_estimate: float | None = None
    eps_actual: float | None = None
    revenue_estimate: float | None = None
    revenue_actual: float | None = None
    delivered_at: datetime | None = None
    related_accession: str | None = Field(default=None, max_length=64)
    call_url: str | None = Field(default=None, max_length=512)
    notes: str | None = None


def _out(ev: EarningsEvent) -> EarningsOut:
    return EarningsOut(
        id=ev.id,
        symbol=ev.symbol,
        fiscal_period=ev.fiscal_period,
        expected_date=ev.expected_date.isoformat(),
        bmo_amc=ev.bmo_amc,
        status=ev.status,
        delivered_at=ev.delivered_at.isoformat() if ev.delivered_at else None,
        related_accession=ev.related_accession,
        eps_estimate=ev.eps_estimate,
        eps_actual=ev.eps_actual,
        revenue_estimate=ev.revenue_estimate,
        revenue_actual=ev.revenue_actual,
        call_url=ev.call_url,
        notes=ev.notes,
        created_at=ev.created_at.isoformat(),
        updated_at=ev.updated_at.isoformat(),
    )


# ─── Routes ──────────────────────────────────────────────────────────


@router.get("", response_model=list[EarningsOut])
async def list_earnings(
    symbol: str | None = Query(None, max_length=16),
    status: str | None = Query(None, pattern=r"^(scheduled|delivered|missed)$"),
    upcoming_only: bool = Query(False),
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[EarningsOut]:
    rows = default_earnings_store.list(
        db, symbol=symbol, status=status, upcoming_only=upcoming_only
    )
    return [_out(r) for r in rows]


@router.get("/next", response_model=dict[str, EarningsOut])
async def next_scheduled_map(
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, EarningsOut]:
    """Map {symbol → nearest upcoming scheduled event}.

    Powers the per-watchlist "下次财报 N 天" countdown across the
    research desk, /admin/companies, and the trg-news-002 ticker rail
    without N+1 queries.
    """
    rows = default_earnings_store.next_scheduled_map(db)
    return {sym: _out(ev) for sym, ev in rows.items()}


@router.post("", response_model=EarningsOut, status_code=201)
async def create_or_update_event(
    body: EarningsCreate,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> EarningsOut:
    ev = default_earnings_store.upsert(
        db,
        symbol=body.symbol,
        fiscal_period=body.fiscal_period,
        expected_date=body.expected_date,
        bmo_amc=body.bmo_amc,
        status=body.status,
        eps_estimate=body.eps_estimate,
        eps_actual=body.eps_actual,
        revenue_estimate=body.revenue_estimate,
        revenue_actual=body.revenue_actual,
        delivered_at=body.delivered_at,
        related_accession=body.related_accession,
        call_url=body.call_url,
        notes=body.notes,
    )
    return _out(ev)


@router.patch("/{event_id}", response_model=EarningsOut)
async def update_event(
    event_id: str,
    body: EarningsUpdate,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> EarningsOut:
    patch = body.model_dump(exclude_unset=True)
    updated = default_earnings_store.update(db, event_id, **patch)
    if updated is None:
        raise HTTPException(404, detail=f"earnings event {event_id} not found")
    return _out(updated)


@router.delete("/{event_id}", status_code=204)
async def delete_event(
    event_id: str,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    ok = default_earnings_store.delete(db, event_id)
    if not ok:
        raise HTTPException(404, detail=f"earnings event {event_id} not found")
