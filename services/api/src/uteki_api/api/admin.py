"""Admin endpoints — operational tooling that isn't part of the user flow.

``POST /api/admin/reload-skills`` clears the skill prompt cache and rebinds
``skill.system_prompt`` for every registered skill. This is the keystone of
the prompt-tuning loop (``scripts/tune-prompt.sh``): edit a SKILL.md or a
shared guardrail file, POST this endpoint, run eval — no API restart.

``POST /api/admin/review/{run_id}`` is the M1 self-evolution loop trigger —
creates a Proposal record for a Run.

``POST /api/admin/proposals/{proposal_id}/run-cc`` (M1.3) drives the
self-evolution pipeline from ``triggered`` → ``pending_review``. Snapshots
the skill + run artifacts, builds brief.md, spawns the ``claude`` CLI
(or canned mock when ``UTEKI_USE_MOCK_CC=true``), and collects critique.md
+ patch.diff. Runs in a background task — the endpoint returns immediately
with ``{status:'spawning'}`` and the caller polls the proposal.

M4+: gated behind admin role so anonymous/read-only callers can't hot-reload
prompts or trigger self-evolution. Configure admins with UTEKI_ADMIN_EMAILS or
GitHub allowlists.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from uteki_api.auth.deps import require_admin
from uteki_api.core.db import get_db
from uteki_api.evolution.cc_runner import run_cc_review
from uteki_api.evolution.proposals import default_proposal_store
from uteki_api.runs import default_run_store
from uteki_api.skills import default_skills
from uteki_api.skills.loader import load_skill_prompt
from uteki_api.users.models import User
from uteki_api.users.store import default_user_store

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
)

# Track in-flight cc_runner tasks so they aren't garbage-collected mid-run.
# Mirrors the pattern in api/agent.py's _inflight_runs.
_inflight_cc_reviews: set[asyncio.Task] = set()


@router.post("/reload-skills")
async def reload_skills(_user: User = Depends(require_admin)) -> dict:
    """Clear the loader cache and refresh each skill's `system_prompt`."""
    load_skill_prompt.cache_clear()
    cleared: list[str] = []
    skipped: list[str] = []
    for entry in default_skills.list():
        name = entry["name"]
        skill = default_skills.get(name)
        if not hasattr(skill, "system_prompt"):
            skipped.append(name)
            continue
        try:
            new_text, new_refs = load_skill_prompt(name)
        except FileNotFoundError:
            skipped.append(name)
            continue
        skill.system_prompt = new_text
        skill.refs = new_refs
        cleared.append(name)
    return {"cleared": cleared, "skipped": skipped, "count": len(cleared)}


@router.post("/review/{run_id}")
async def trigger_review(
    run_id: str,
    reason: str = "manual trigger",
    user: User = Depends(require_admin),
) -> dict:
    """Create a self-evolution Proposal for ``run_id``.

    M1.1: only writes bookkeeping (meta.json + decisions/001-triggered.json).
    The actual CC-review pipeline (snapshot → spawn → critique → validate)
    lands in M1.2-M1.4. Returns the freshly-allocated ``proposal_id`` so
    callers can poll status later via a (future) ``GET /api/admin/proposals``.

    Auth: caller must be admin and own the run. Ownership is enforced by
    ``run_store.get(run_id, user.id)`` raising KeyError on cross-user access —
    same 404 shape as "doesn't exist".
    """
    try:
        run = await default_run_store.get(run_id, user.id)
    except KeyError as e:
        raise HTTPException(404, detail=str(e)) from e

    proposal = default_proposal_store.create(
        source_run_id=run.id,
        source_skill=run.skill,
        source_user_id=run.user_id,
        triggered_by=f"user:{user.id}",
        trigger_reason=reason,
    )
    return {
        "proposal_id": proposal.proposal_id,
        "status": proposal.status,
        "source_skill": proposal.source_skill,
        "source_run_id": proposal.source_run_id,
    }


@router.post("/proposals/{proposal_id}/run-cc")
async def run_cc(
    proposal_id: str,
    _user: User = Depends(require_admin),
) -> dict:
    """Kick off the cc_runner pipeline for a triggered proposal.

    Returns immediately after validating the proposal exists and is in
    ``triggered`` state; the actual snapshot → spawn → collect flow runs
    in a background asyncio task. Callers poll
    ``GET /api/admin/proposals/{proposal_id}`` (M1.5) — or directly read
    ``meta.json`` — to observe progress through the state machine.

    Idempotency: refuses if the proposal is anything other than
    ``triggered``. A failed/invalidated proposal needs a fresh trigger
    (per the state-machine spec — ``invalidated`` is terminal).
    """
    try:
        proposal = default_proposal_store.get(proposal_id)
    except KeyError as e:
        raise HTTPException(404, detail=str(e)) from e
    if proposal.status != "triggered":
        raise HTTPException(
            409,
            detail=(
                f"proposal {proposal_id} is {proposal.status}, expected triggered"
            ),
        )

    async def _drive() -> None:
        try:
            await run_cc_review(proposal_id)
        except Exception:  # noqa: BLE001 — cc_runner logs internally
            logger.exception("background cc_runner failed for %s", proposal_id)

    task = asyncio.create_task(_drive(), name=f"cc-review-{proposal_id}")
    _inflight_cc_reviews.add(task)
    task.add_done_callback(_inflight_cc_reviews.discard)

    return {
        "proposal_id": proposal_id,
        "status": "spawning",
        "background": True,
    }


@router.get("/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: str,
    _user: User = Depends(require_admin),
) -> dict:
    """Read the current meta.json of a proposal.

    Lightweight inspection endpoint — the full G1 review UI (M1.5) will
    layer richer projections (critique excerpt, patch stats, etc) on top.
    This one is just "give me the current state machine truth".
    """
    try:
        proposal = default_proposal_store.get(proposal_id)
    except KeyError as e:
        raise HTTPException(404, detail=str(e)) from e
    return proposal.model_dump()


class UserRow(BaseModel):
    id: str
    email: str
    display_name: str
    avatar_url: str | None
    role: str
    status: str
    created_at: str
    providers: list[str]


class UsersListResponse(BaseModel):
    items: list[UserRow]
    total: int
    limit: int
    offset: int


class UpdateRoleBody(BaseModel):
    role: str = Field(..., pattern=r"^(admin|reader)$")


def _row(db: Session, user: User) -> UserRow:
    return UserRow(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        role=user.role,
        status=user.status,
        created_at=user.created_at.isoformat(),
        providers=default_user_store.providers_for(db, user.id),
    )


@router.get("/users", response_model=UsersListResponse)
async def list_users(
    limit: int = 50,
    offset: int = 0,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UsersListResponse:
    """List all real users (demo@local hidden) with their identity providers.

    Paginated. Newest first by ``created_at``. Used by the ``/admin/users``
    console page; not part of the public API contract.
    """
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    rows, total = default_user_store.list(db, limit=limit, offset=offset)
    return UsersListResponse(
        items=[_row(db, u) for u in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/users/{user_id}", response_model=UserRow)
async def update_user_role(
    user_id: str,
    body: UpdateRoleBody,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserRow:
    """Promote / demote a user. Two guards against lockout:

    1. An admin cannot demote themselves — must be done by another admin.
    2. Cannot demote the last remaining admin (system would have zero).
    """
    if user_id == actor.id and body.role != "admin":
        raise HTTPException(
            409, detail="cannot demote yourself; ask another admin"
        )

    target = default_user_store.get(db, user_id)
    if target is None:
        raise HTTPException(404, detail=f"user {user_id} not found")

    if target.role == "admin" and body.role != "admin":
        admin_count = default_user_store.count_admins(db)
        if admin_count <= 1:
            raise HTTPException(
                409,
                detail="refusing to demote the last admin",
            )

    if target.role == body.role:
        # No-op; still return current state so the UI can reconcile.
        return _row(db, target)

    updated = default_user_store.update_role(db, user_id, body.role)
    if updated is None:
        raise HTTPException(404, detail=f"user {user_id} not found")
    logger.info(
        "admin role change actor=%s target=%s %s→%s",
        actor.id, updated.id, target.role, updated.role,
    )
    return _row(db, updated)


# Re-export so test conftest can rebind it alongside default_proposal_store.
# (cc_runner reaches into module-level singletons; tests that swap the
# proposal store in must also swap this module's reference so the API
# handler and the background task see the same instance.)
__all__ = ["router", "run_cc_review"]
