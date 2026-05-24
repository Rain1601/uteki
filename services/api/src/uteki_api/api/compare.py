"""Multi-agent compare endpoints.

POST /api/compare/run   run N agents in parallel on the same messages.
POST /api/compare/diff  fetch persisted runs and return a structured diff.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from uteki_api.agents.harness import AgentHarness
from uteki_api.auth.deps import current_user
from uteki_api.evolution import default_evolution_store
from uteki_api.runs import default_run_store
from uteki_api.schemas.chat import ChatMessage
from uteki_api.skills import default_skills
from uteki_api.users.models import User

router = APIRouter(prefix="/api/compare", tags=["compare"])


class CompareRunRequest(BaseModel):
    messages: list[ChatMessage]
    agents: list[str]
    model: str | None = None


class CompareDiffRequest(BaseModel):
    run_ids: list[str]


@router.post("/run")
async def compare_run(
    req: CompareRunRequest,
    user: User = Depends(current_user),
) -> dict:
    if not req.agents:
        raise HTTPException(status_code=400, detail="agents must be non-empty")

    reason = f"compare-vs-{','.join(req.agents)}"
    # Pre-resolve and validate skill names; raise before launching workers.
    for name in req.agents:
        try:
            default_skills.entry(name)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    async def _worker(agent_name: str) -> str:
        skill = default_skills.get(agent_name)
        latest = await default_evolution_store.latest(agent_name)
        skill_version = latest.version if latest else None
        harness = AgentHarness(
            skill=skill,
            triggered_by="compare",
            trigger_reason=reason,
            skill_version=skill_version,
            user_id=user.id,
        )
        rid = ""
        async for ev in harness.run(req.messages):
            if ev.type == "run_start" and ev.run_id:
                rid = ev.run_id
        return rid

    run_ids = await asyncio.gather(*(_worker(n) for n in req.agents))
    return {"run_ids": list(run_ids)}


@router.post("/diff")
async def compare_diff(
    req: CompareDiffRequest,
    user: User = Depends(current_user),
) -> dict:
    out = []
    for rid in req.run_ids:
        try:
            run = await default_run_store.get(rid, user.id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

        latency_ms: float | None = None
        if run.ended_at is not None:
            latency_ms = (run.ended_at - run.started_at) * 1000.0

        tools_called: list[str] = []
        usage: dict = {}
        final_text_parts: list[str] = []
        for ev in run.events:
            if ev.type == "tool_call":
                name = ev.data.get("name", "")
                if name:
                    tools_called.append(name)
            elif ev.type == "usage":
                usage = dict(ev.data)
            elif ev.type == "delta":
                text = ev.data.get("text", "")
                if isinstance(text, str):
                    final_text_parts.append(text)

        out.append(
            {
                "id": run.id,
                "skill": run.skill,
                "skill_version": run.skill_version,
                "status": run.status,
                "latency_ms": latency_ms,
                "tools_called": tools_called,
                "usage": usage,
                "summary": run.summary,
                "final_text": "".join(final_text_parts),
            }
        )
    return {"runs": out}
