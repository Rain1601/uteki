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

from uteki_api.auth.deps import require_admin
from uteki_api.evolution.cc_runner import run_cc_review
from uteki_api.evolution.proposals import default_proposal_store
from uteki_api.runs import default_run_store
from uteki_api.skills import default_skills
from uteki_api.skills.loader import load_skill_prompt
from uteki_api.users.models import User

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


# Re-export so test conftest can rebind it alongside default_proposal_store.
# (cc_runner reaches into module-level singletons; tests that swap the
# proposal store in must also swap this module's reference so the API
# handler and the background task see the same instance.)
__all__ = ["router", "run_cc_review"]
