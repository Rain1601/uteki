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

    # Skills that orchestrate sub-skills (e.g. research_pipeline) need a
    # wider budget than the harness default. The skill declares what it
    # needs via recommended_limits(); None falls back to the default.
    limits = skill.recommended_limits()

    return AgentHarness(
        skill=skill,
        triggered_by="user",
        trigger_reason=f"chat:{session_id or 'adhoc'}",
        run_store=default_run_store,
        skill_version=skill_version,
        user_id=user_id,
        **({"limits": limits} if limits is not None else {}),
    )


@router.post("/chat")
async def chat(
    req: ChatRequest,
    user: User = Depends(current_user),
) -> EventSourceResponse:
    harness = await _build_harness(req.agent, req.model, req.session_id, user.id)

    async def event_source() -> AsyncIterator[dict]:
        # Hold a reference to the underlying async generator so we can
        # aclose() it deterministically when the client disconnects (or
        # any other GeneratorExit fires). Without this, sse_starlette
        # closes us mid-`await` inside harness.run and we get
        # "async generator ignored GeneratorExit" in the asyncio logs —
        # functionally harmless but noisy and signals torn-down state
        # the harness didn't get to clean up (final run_store.finish,
        # usage rollup, etc).
        agen = harness.run(req.messages, session_id=req.session_id)
        try:
            async for event in agen:
                yield {"event": event.type, "data": event.model_dump_json()}
        finally:
            await agen.aclose()

    return EventSourceResponse(event_source())
