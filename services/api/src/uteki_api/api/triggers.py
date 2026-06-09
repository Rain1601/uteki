"""Trigger management + event ingestion endpoints.

Triggers are now DB-persisted (``trigger`` table). The in-memory
``default_triggers`` registry from ``triggers/registry.py`` survives for
webhook event matching (POST /event) until P11 unifies the two.

- ``GET /api/triggers`` — list persisted triggers; any authed user.
- ``POST /api/triggers`` — upsert by id; admin-only.
- ``PATCH /api/triggers/{id}`` — partial update; admin-only.
- ``DELETE /api/triggers/{id}`` — hard delete; admin-only. Any
  trigger_hit rows pointing at the deleted ID get orphaned (the news
  detail page will simply skip them); we don't cascade because the
  hits are historic facts worth keeping.
- ``POST /api/triggers/event`` — webhook ingestion (legacy registry).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from uteki_api.auth.deps import current_user, require_admin
from uteki_api.core.db import get_db
from uteki_api.triggers import default_triggers, default_trigger_store
from uteki_api.triggers.persisted_models import Trigger
from uteki_api.users.models import User

router = APIRouter(prefix="/api/triggers", tags=["triggers"])


# ─── Schemas ─────────────────────────────────────────────────────────


class TriggerOut(BaseModel):
    id: str
    name: str
    kind: str
    skill: str
    condition: str
    watchlist_symbols: list[str]
    cadence_minutes: int
    cadence_text: str
    earnings_window_hours: int
    boost_in_earnings_window_minutes: int
    enabled: bool
    last_check_at: str | None
    last_triggered_at: str | None
    next_check_at: str | None
    last_status: str
    sort_order: int
    created_at: str
    updated_at: str


class TriggerUpsert(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=200)
    kind: str = Field(..., pattern=r"^(news|earnings|event|price|schedule)$")
    skill: str = Field("uteki", max_length=64)
    condition: str = Field("", max_length=1024)
    watchlist_symbols: list[str] = Field(default_factory=list)
    cadence_minutes: int = Field(60, ge=0, le=10_080)  # 0 = event-driven; max = 1 week
    cadence_text: str = Field("", max_length=64)
    earnings_window_hours: int = Field(0, ge=0, le=72)
    boost_in_earnings_window_minutes: int = Field(0, ge=0, le=1_440)
    enabled: bool = True
    sort_order: int = 0


class TriggerPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    kind: str | None = Field(default=None, pattern=r"^(news|earnings|event|price|schedule)$")
    skill: str | None = Field(default=None, max_length=64)
    condition: str | None = Field(default=None, max_length=1024)
    watchlist_symbols: list[str] | None = None
    cadence_minutes: int | None = Field(default=None, ge=0, le=10_080)
    cadence_text: str | None = Field(default=None, max_length=64)
    earnings_window_hours: int | None = Field(default=None, ge=0, le=72)
    boost_in_earnings_window_minutes: int | None = Field(default=None, ge=0, le=1_440)
    enabled: bool | None = None
    sort_order: int | None = None


def _split_csv(raw: str) -> list[str]:
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _join_csv(items: list[str]) -> str:
    return ",".join(s.strip().upper() for s in items if s.strip())


def _out(trig: Trigger) -> TriggerOut:
    return TriggerOut(
        id=trig.id,
        name=trig.name,
        kind=trig.kind,
        skill=trig.skill,
        condition=trig.condition,
        watchlist_symbols=_split_csv(trig.watchlist_symbols),
        cadence_minutes=trig.cadence_minutes,
        cadence_text=trig.cadence_text,
        earnings_window_hours=trig.earnings_window_hours,
        boost_in_earnings_window_minutes=trig.boost_in_earnings_window_minutes,
        enabled=trig.enabled,
        last_check_at=trig.last_check_at.isoformat() if trig.last_check_at else None,
        last_triggered_at=trig.last_triggered_at.isoformat() if trig.last_triggered_at else None,
        next_check_at=trig.next_check_at.isoformat() if trig.next_check_at else None,
        last_status=trig.last_status,
        sort_order=trig.sort_order,
        created_at=trig.created_at.isoformat(),
        updated_at=trig.updated_at.isoformat(),
    )


# ─── Routes ──────────────────────────────────────────────────────────


@router.get("", response_model=list[TriggerOut])
async def list_triggers(
    enabled_only: bool = False,
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[TriggerOut]:
    rows = default_trigger_store.list(db, enabled_only=enabled_only)
    return [_out(t) for t in rows]


@router.post("", response_model=TriggerOut, status_code=201)
async def create_or_update_trigger(
    body: TriggerUpsert,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TriggerOut:
    trig = default_trigger_store.upsert(
        db,
        id=body.id,
        name=body.name,
        kind=body.kind,
        skill=body.skill,
        condition=body.condition,
        watchlist_symbols=_join_csv(body.watchlist_symbols),
        cadence_minutes=body.cadence_minutes,
        cadence_text=body.cadence_text,
        earnings_window_hours=body.earnings_window_hours,
        boost_in_earnings_window_minutes=body.boost_in_earnings_window_minutes,
        enabled=body.enabled,
        sort_order=body.sort_order,
    )
    return _out(trig)


@router.patch("/{trigger_id}", response_model=TriggerOut)
async def update_trigger(
    trigger_id: str,
    body: TriggerPatch,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TriggerOut:
    patch = body.model_dump(exclude_unset=True)
    if "watchlist_symbols" in patch and patch["watchlist_symbols"] is not None:
        patch["watchlist_symbols"] = _join_csv(patch["watchlist_symbols"])
    updated = default_trigger_store.update(db, trigger_id, **patch)
    if updated is None:
        raise HTTPException(404, detail=f"trigger {trigger_id} not found")
    return _out(updated)


@router.delete("/{trigger_id}", status_code=204)
async def delete_trigger(
    trigger_id: str,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    ok = default_trigger_store.delete(db, trigger_id)
    if not ok:
        raise HTTPException(404, detail=f"trigger {trigger_id} not found")


# ─── Legacy webhook ingestion (kept for the in-memory event registry) ──


class EventIngest(BaseModel):
    topic: str
    payload: dict


@router.post("/event")
async def ingest_event(body: EventIngest) -> dict:
    """Hook for external webhooks (legacy registry; pre-DB).

    Looks up matching in-memory EventTriggers and returns the prompts
    that would fire. The DB-persisted triggers above don't participate
    yet — P10.2 scheduler will own the dispatch from there.
    """
    matches = default_triggers.by_topic(body.topic)
    fired = []
    for t in matches:
        try:
            prompt = t.prompt_template.format(**body.payload)
        except KeyError as e:
            fired.append({"trigger_id": t.id, "error": f"missing key: {e}"})
            continue
        fired.append({"trigger_id": t.id, "agent": t.agent, "prompt": prompt})
    return {"topic": body.topic, "fired": fired}
