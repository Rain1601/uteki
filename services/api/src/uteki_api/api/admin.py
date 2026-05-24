"""Admin endpoints — operational tooling that isn't part of the user flow.

``POST /api/admin/reload-skills`` clears the skill prompt cache and rebinds
``skill.system_prompt`` for every registered skill. This is the keystone of
the prompt-tuning loop (``scripts/tune-prompt.sh``): edit a SKILL.md or a
shared guardrail file, POST this endpoint, run eval — no API restart.

M4: gated behind ``current_user`` so anonymous callers can't hot-reload
prompts. There's no role/is_admin field yet, so any authenticated user can
call this — the real ACL gate will land alongside team workspaces. In dev
mode (``UTEKI_AUTH_REQUIRED=false``) the demo user fallback keeps this
endpoint reachable from ``scripts/tune-prompt.sh`` without touching tokens.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from uteki_api.auth.deps import current_user
from uteki_api.skills import default_skills
from uteki_api.skills.loader import load_skill_prompt

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(current_user)],
)


@router.post("/reload-skills")
async def reload_skills() -> dict:
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
