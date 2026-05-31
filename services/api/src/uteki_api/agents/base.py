"""Base agent — the unit of intent that the harness orchestrates.

Subclasses ("skills") are responsible only for yielding `AgentEvent`s. The
harness handles tool dispatch, guardrails, memory, run tracking, etc.

Each skill may optionally expose `current_signature()` so the evolution store
can detect changes (prompt/tool/model edits) and bump the version.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from uteki_api.schemas.chat import ChatMessage
from uteki_api.schemas.events import AgentEvent

if TYPE_CHECKING:
    from uteki_api.agents.harness import HarnessLimits
    from uteki_api.artifacts import RunArtifacts
    from uteki_api.llm.client import ToolExecutor
    from uteki_api.provenance import RunSources


class BaseAgent(ABC):
    """A 'skill' — pure intent stream. The harness wraps execution."""

    name: str = "base"

    # Injected by AgentHarness before `run()` is called. Skills that opt into
    # the LLM tool-use loop pass this to ``LLMClient.stream_chat_with_tools``;
    # skills that don't can ignore it. None when the harness is unable to
    # wire tools (e.g. mock-only tests).
    _tool_executor: ToolExecutor | None = None

    # Injected alongside _tool_executor. Run-scoped, identity-bound facade for
    # writing named artifacts (plan.md / draft.md / eval-report.json / etc.).
    # See ``services/api/src/uteki_api/artifacts/`` and openspec/changes/005.
    artifacts: RunArtifacts | None = None

    # Injected alongside artifacts. Run-scoped source catalog facade for
    # registering citable facts and validating `[src:N]` markers.
    sources: RunSources | None = None

    @abstractmethod
    def run(self, messages: list[ChatMessage]) -> AsyncIterator[AgentEvent]:
        """Yield AgentEvents (plan / step / thinking / tool_call / delta)."""

    def recommended_limits(self) -> HarnessLimits | None:
        """Skills that need a budget different from the harness default
        return one here. Callers (e.g. ``api/agent.py``) pass it to
        ``AgentHarness(limits=...)`` when the skill is the top-level
        target. Return ``None`` to inherit the platform default.

        Use sparingly — the default exists to keep run cost bounded. Only
        widen when the workload genuinely needs it (e.g. a pipeline that
        orchestrates several sub-skills under one harness)."""
        return None

    def current_signature(self) -> dict[str, Any]:
        """Return a stable description of the skill's current behavior.

        Used by the evolution store to detect changes and auto-bump versions.
        Keys: `prompt`, `tool_names`, `model`, `params`. Default is empty.
        """
        return {}
