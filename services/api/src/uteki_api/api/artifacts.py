"""Artifact REST endpoints — user-scoped (M4).

The store partitions by user; we resolve ``user_id`` from the run record
(rather than asking the caller) so URLs stay clean: a user can hit
``/api/runs/{id}/artifacts/{name}`` without knowing which partition holds
the file.

Cross-user access: ``run_store.get(run_id, user.id)`` raises KeyError when
the run isn't owned by this user, which the endpoint maps to 404 — same
shape as "doesn't exist", to avoid leaking existence.

Path traversal is blocked at the store layer via filename whitelist +
absolute-path containment check; this router only maps store errors to
HTTP codes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from uteki_api.artifacts import default_artifact_store
from uteki_api.auth.deps import current_user
from uteki_api.runs import default_run_store
from uteki_api.users.models import User

router = APIRouter(prefix="/api/runs/{run_id}/artifacts", tags=["artifacts"])


async def _owner_id(run_id: str, user: User) -> str:
    try:
        run = await default_run_store.get(run_id, user.id)
    except KeyError as e:
        raise HTTPException(404, detail=str(e)) from e
    return run.user_id


@router.get("")
async def list_artifacts(
    run_id: str,
    user: User = Depends(current_user),
) -> dict:
    owner = await _owner_id(run_id, user)
    items = await default_artifact_store.list(run_id, owner)
    return {"items": [i.model_dump() for i in items]}


@router.get("/{name}")
async def get_artifact(
    run_id: str,
    name: str,
    user: User = Depends(current_user),
) -> Response:
    owner = await _owner_id(run_id, user)
    try:
        meta, content = await default_artifact_store.read(run_id, name, owner)
    except FileNotFoundError as e:
        raise HTTPException(404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e

    return Response(
        content=content,
        media_type=meta.content_type or "application/octet-stream",
        headers={
            "X-Artifact-Kind": meta.kind,
            "X-Written-By": meta.written_by,
        },
    )
