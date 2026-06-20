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

    @staticmethod
    def tools_allowlist_prefix(tool_names: list[str] | tuple[str, ...]) -> str:
        """Format a tools-whitelist block to prepend to the system prompt.

        Adopts Anthropic finance-skill pattern (`tools:` YAML frontmatter on
        agent definitions like ``earnings-reviewer`` — they declare a hard
        allowlist at the prompt level so the LLM self-constrains even if the
        tool registry exposes more. We had a silent failure mode where
        ``default_registry.openai_specs()`` exposed all 11 registered tools
        but ``DEFAULT_TOOLS`` only listed 9 — LLM would occasionally call
        ``web_search`` from a research run that didn't declare it.

        Skills should call this in ``__init__`` after ``load_skill_prompt``::

            self.system_prompt = (
                self.tools_allowlist_prefix(self.DEFAULT_TOOLS)
                + "\\n\\n---\\n\\n"
                + self.system_prompt
            )

        Returns an empty string if no tool names are provided (some skills
        are pure text generators — no tools call expected)."""
        names = list(tool_names) if tool_names else []
        if not names:
            return ""
        lines = "\n".join(f"- `{n}`" for n in names)
        return (
            "【你的工具白名单 — 硬约束】\n\n"
            f"本 skill 注册了以下 {len(names)} 个工具,**只能调用这些**,不要尝试调用其它:\n\n"
            f"{lines}\n\n"
            "如果某个判断需要的数据这些工具都拿不到,正确做法是:\n"
            "1. 显式标 `[src:none]` 并说明缺什么类型数据\n"
            "2. 在 thinking 里记录 \"工具白名单内无法获得 X,跳过此声明\"\n"
            "3. ❌ **不要**尝试调用白名单外的工具(harness 会拒绝并算一次失败)\n"
            "4. ❌ **不要**在文本里写 `<tool_call>` markup 假装调用 — 这是 process leak"
        )
