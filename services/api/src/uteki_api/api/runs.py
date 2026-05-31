"""Run inspection endpoints — user-scoped (M4).

GET /api/runs                       list — current user's runs
GET /api/runs/{run_id}              full Run including events (404 if not yours)
GET /api/runs/{run_id}/events       events only (404 if not yours)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from uteki_api.artifacts import Artifact, default_artifact_store
from uteki_api.auth.deps import current_user
from uteki_api.runs import default_run_store
from uteki_api.runs.models import Run
from uteki_api.users.models import User

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _artifact_ref(artifact: Artifact) -> dict:
    return {
        "name": artifact.name,
        "kind": artifact.kind,
        "size_bytes": artifact.size_bytes,
        "written_by": artifact.written_by,
        "description": artifact.description,
        "url": f"/api/runs/{artifact.run_id}/artifacts/{artifact.name}",
        "role": artifact.role,
        "display_name": artifact.display_name,
        "source_refs": artifact.source_refs,
    }


def _primary_artifact(artifacts: list[Artifact]) -> Artifact | None:
    for artifact in artifacts:
        if artifact.role == "primary":
            return artifact
    for name in ("final-report.md", "investment-memo.md", "final-research.md", "research.md"):
        for artifact in artifacts:
            if artifact.name == name:
                return artifact
    return artifacts[0] if artifacts else None


def _events_summary(run: Run) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in run.events:
        counts[event.type] = counts.get(event.type, 0) + 1
    return counts


async def _artifact_index(run: Run) -> list[Artifact]:
    try:
        return await default_artifact_store.list(run.id, run.user_id)
    except Exception:
        return []


async def _summary(run: Run) -> dict:
    artifacts = await _artifact_index(run)
    primary = _primary_artifact(artifacts)
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
        "user_input": run.user_input,
        "tags": run.tags,
        "artifact_count": len(artifacts),
        "primary_artifact": _artifact_ref(primary) if primary is not None else None,
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
    return {"items": [await _summary(r) for r in runs]}


@router.get("/{run_id}")
async def get_run(run_id: str, user: User = Depends(current_user)) -> dict:
    try:
        run = await default_run_store.get(run_id, user.id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    payload = run.model_dump()
    artifacts = await _artifact_index(run)
    primary = _primary_artifact(artifacts)
    payload["artifacts"] = [_artifact_ref(a) for a in artifacts]
    payload["primary_artifact"] = _artifact_ref(primary) if primary is not None else None
    payload["artifact_count"] = len(artifacts)
    payload["events_summary"] = _events_summary(run)
    return payload


@router.get("/{run_id}/events")
async def get_run_events(run_id: str, user: User = Depends(current_user)) -> dict:
    try:
        run = await default_run_store.get(run_id, user.id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"items": [e.model_dump() for e in run.events]}
