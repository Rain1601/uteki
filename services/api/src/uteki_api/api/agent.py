"""POST /api/agent/chat — Server-Sent Events stream of AgentEvents.

Resolves the requested `agent` against the skill registry (falling back to
"research"), binds the latest evolution version, and wires the harness to
the default RunStore. (M4) Runs are tagged with the calling user's id so
isolation works downstream.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from uteki_api.agents.harness import AgentHarness
from uteki_api.auth.deps import current_user
from uteki_api.evolution import default_evolution_store
from uteki_api.runs import default_run_store
from uteki_api.schemas.chat import ChatRequest
from uteki_api.skills import default_skills
from uteki_api.users.models import User

router = APIRouter(prefix="/api/agent", tags=["agent"])


async def _build_harness(
    agent_name: str,
    model: str | None,
    session_id: str | None,
    user_id: str,
) -> AgentHarness:
    try:
        skill = default_skills.get(agent_name)
    except KeyError:
        skill = default_skills.get("research")

    # Inject the caller's model override if the skill accepts it.
    if model is not None and hasattr(skill, "model"):
        with contextlib.suppress(Exception):
            skill.model = model  # type: ignore[attr-defined]

    latest = await default_evolution_store.latest(skill.name)
    skill_version = latest.version if latest else None

    return AgentHarness(
        skill=skill,
        triggered_by="user",
        trigger_reason=f"chat:{session_id or 'adhoc'}",
        run_store=default_run_store,
        skill_version=skill_version,
        user_id=user_id,
    )


@router.post("/chat")
async def chat(
    req: ChatRequest,
    user: User = Depends(current_user),
) -> EventSourceResponse:
    harness = await _build_harness(req.agent, req.model, req.session_id, user.id)

    async def event_source() -> AsyncIterator[dict]:
        async for event in harness.run(req.messages, session_id=req.session_id):
            yield {"event": event.type, "data": event.model_dump_json()}

    return EventSourceResponse(event_source())
