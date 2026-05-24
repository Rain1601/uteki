"""Trigger management + event ingestion endpoints.

M4: ``GET /api/triggers`` is gated behind ``current_user`` — the trigger
catalog is platform-level metadata but not public. ``POST /event`` is the
webhook target for external systems (财报披露 / 突发新闻 feeds) and stays
open here; the real production gate is a per-source HMAC signature check,
which will land alongside 005.2 once webhook delivery is real.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from uteki_api.auth.deps import current_user
from uteki_api.triggers import default_triggers

router = APIRouter(prefix="/api/triggers", tags=["triggers"])


@router.get("", dependencies=[Depends(current_user)])
async def list_triggers() -> dict:
    return {"items": [t.model_dump() for t in default_triggers.list()]}


class EventIngest(BaseModel):
    topic: str
    payload: dict


@router.post("/event")
async def ingest_event(body: EventIngest) -> dict:
    """Hook for external webhooks (财报披露 / 突发新闻).

    Looks up matching EventTriggers and returns the prompts that would fire.
    Actual run dispatch is a TODO — wire to a queue (Vercel Queues / Celery /
    arq) so webhooks return fast.
    """
    matches = default_triggers.by_topic(body.topic)
    fired = []
    for t in matches:
        try:
            prompt = t.prompt_template.format(**body.payload)
        except KeyError as e:
            fired.append({"trigger_id": t.id, "error": f"missing key: {e}"})
            continue
        fired.append({"trigger_id": t.id, "agent": t.agent, "prompt": prompt})
    return {"topic": body.topic, "fired": fired}
