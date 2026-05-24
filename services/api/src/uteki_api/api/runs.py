"""Run inspection endpoints — user-scoped (M4).

GET /api/runs                       list — current user's runs
GET /api/runs/{run_id}              full Run including events (404 if not yours)
GET /api/runs/{run_id}/events       events only (404 if not yours)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from uteki_api.auth.deps import current_user
from uteki_api.runs import default_run_store
from uteki_api.users.models import User

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _summary(run) -> dict:  # type: ignore[no-untyped-def]
    return {
        "id": run.id,
        "skill": run.skill,
        "skill_version": run.skill_version,
        "triggered_by": run.triggered_by,
        "trigger_reason": run.trigger_reason,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "status": run.status,
        "summary": run.summary,
    }


@router.get("")
async def list_runs(
    skill: str | None = None,
    triggered_by: str | None = None,
    limit: int = 50,
    user: User = Depends(current_user),
) -> dict:
    runs = await default_run_store.list(
        user_id=user.id, skill=skill, triggered_by=triggered_by, limit=limit
    )
    return {"items": [_summary(r) for r in runs]}


@router.get("/{run_id}")
async def get_run(run_id: str, user: User = Depends(current_user)) -> dict:
    try:
        run = await default_run_store.get(run_id, user.id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return run.model_dump()


@router.get("/{run_id}/events")
async def get_run_events(run_id: str, user: User = Depends(current_user)) -> dict:
    try:
        run = await default_run_store.get(run_id, user.id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"items": [e.model_dump() for e in run.events]}
