"""Agent execution event schema.

Every step of the agent — planning, thinking, tool calls, deltas, citations —
is emitted as one of these events. Frontend pattern-matches on `type` to render.

Keep `data` loose for now; tighten as the UI matures.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "run_start",        # run created
    "plan",             # high-level plan (list of step titles)
    "step_start",       # a step begins
    "step_end",         # a step ends (with status)
    "thinking",         # free-form thinking text
    "tool_call",        # tool invocation (name, args)
    "tool_result",      # tool result (ok, summary, preview)
    "delta",            # token delta of the final assistant message
    "citation",         # cited source
    "usage",            # token/cost usage
    "log",              # structured log line ({level, message, extra?})
    "artifact_written", # file-typed output written ({name, kind, size_bytes, written_by, url})
    "await_review",     # skill requests a checkpoint review ({checkpoint, ready_artifacts, reason?})
    "subagent_start",   # pipeline delegates to a sub-skill ({name, iteration?})
    "subagent_end",     # sub-skill returned control to the pipeline ({name, iteration?})
    "error",            # error in this step or run
    "done",             # run finished
]


class AgentEvent(BaseModel):
    type: EventType
    run_id: str | None = None
    step_id: str | None = None
    parent_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    ts: float = Field(default_factory=lambda: time.time())
