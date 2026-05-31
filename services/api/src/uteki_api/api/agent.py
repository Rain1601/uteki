"""POST /api/agent/chat   — Server-Sent Events stream of AgentEvents.
POST /api/agent/start    — fire-and-forget; returns {run_id} immediately.

Resolves the requested `agent` against the skill registry (falling back to
"research"), binds the latest evolution version, and wires the harness to
the default RunStore. (M4) Runs are tagged with the calling user's id so
isolation works downstream.

The /chat endpoint is what the web client uses (it wants the SSE stream).
The /start endpoint is what the MCP server uses: MCP tool calls have to
return promptly (typically <30s), so we kick off the harness, capture the
run_id from the first event (run_start), then keep draining the async
generator in a background task. Callers poll /api/runs/{id} for state.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from uteki_api.agents.harness import AgentHarness
from uteki_api.auth.deps import current_user
from uteki_api.auth.roles import can_run_agent, required_permission_for_agent
from uteki_api.evolution import default_evolution_store
from uteki_api.runs import default_run_store
from uteki_api.schemas.chat import ChatRequest
from uteki_api.skills import default_skills
from uteki_api.users.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent"])

# Holds in-flight background harness tasks so they aren't garbage-collected
# mid-run. Tasks remove themselves on completion via the done_callback.
_inflight_runs: set[asyncio.Task] = set()


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
    if not can_run_agent(user, req.agent):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"permission required: {required_permission_for_agent(req.agent)}",
        )
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


@router.post("/start")
async def start(
    req: ChatRequest,
    user: User = Depends(current_user),
) -> dict:
    """Kick off a run, return ``{run_id}`` immediately; harness keeps
    running in a background asyncio task.

    Designed for the MCP server (and other non-streaming clients) — MCP
    tool-call responses have to come back promptly, but a pipeline run
    can take 2+ minutes. The first event the harness yields is always
    ``run_start`` with the freshly-allocated run_id, so we can pull
    that synchronously and hand off the rest of the stream to a task.
    """
    if not can_run_agent(user, req.agent):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"permission required: {required_permission_for_agent(req.agent)}",
        )
    harness = await _build_harness(req.agent, req.model, req.session_id, user.id)
    agen = harness.run(req.messages, session_id=req.session_id)

    # First yield is run_start — happens after harness creates the Run
    # row but before it awaits the skill's first event. Pulls in ~ms.
    first = await agen.__anext__()
    run_id = first.run_id or ""

    async def _drain() -> None:
        try:
            async for _ev in agen:
                pass
        except Exception as e:  # noqa: BLE001 — log & swallow; harness
            # already wrote an error event to the store in normal paths.
            logger.exception("background drain failed for run %s: %s", run_id, e)
        finally:
            with contextlib.suppress(Exception):
                await agen.aclose()

    task = asyncio.create_task(_drain(), name=f"run-{run_id}")
    _inflight_runs.add(task)
    task.add_done_callback(_inflight_runs.discard)

    return {"run_id": run_id, "agent": req.agent, "status": "running"}
