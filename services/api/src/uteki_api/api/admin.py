"""Admin endpoints — operational tooling that isn't part of the user flow.

``POST /api/admin/reload-skills`` clears the skill prompt cache and rebinds
``skill.system_prompt`` for every registered skill. This is the keystone of
the prompt-tuning loop (``scripts/tune-prompt.sh``): edit a SKILL.md or a
shared guardrail file, POST this endpoint, run eval — no API restart.

``POST /api/admin/review/{run_id}`` is the M1 self-evolution loop trigger —
creates a Proposal record for a Run and starts the evolution state machine.
M1.1 phase only writes the meta.json bookkeeping; subsequent M1.x tasks
add snapshot + CC spawn + apply + A/B eval pipeline.

M4+: gated behind admin role so anonymous/read-only callers can't hot-reload
prompts or trigger self-evolution. Configure admins with UTEKI_ADMIN_EMAILS or
GitHub allowlists.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from uteki_api.auth.deps import require_admin
from uteki_api.evolution.proposals import default_proposal_store
from uteki_api.runs import default_run_store
from uteki_api.skills import default_skills
from uteki_api.skills.loader import load_skill_prompt
from uteki_api.users.models import User

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
)


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
