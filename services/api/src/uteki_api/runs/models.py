"""Run model — one bounded execution of a skill by the harness.

Captures who triggered the run, when it started/ended, the conversational
input that seeded it, every emitted `AgentEvent`, and a short summary. Stored
by `RunStore` so the API and frontend can list / inspect / diff runs.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from uteki_api.schemas.events import AgentEvent

TriggeredBy = Literal["user", "cron", "event", "eval", "compare"]
RunStatus = Literal["running", "ok", "error", "timeout"]


class UsageSummary(BaseModel):
    """Aggregated token usage + cost across all `usage` events in a run."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0


class Run(BaseModel):
    id: str
    # M4: user that owns this run. ``system`` for platform-level evals.
    # Required — every Run must carry an owner; harness fails fast otherwise.
    user_id: str
    skill: str
    skill_version: str | None = None
    triggered_by: TriggeredBy
    trigger_reason: str = ""
    started_at: float
    ended_at: float | None = None
    status: RunStatus = "running"
    user_input: str = ""
    summary: str = ""
    events: list[AgentEvent] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    usage_summary: UsageSummary = Field(default_factory=UsageSummary)
