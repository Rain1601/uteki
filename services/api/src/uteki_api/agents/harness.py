"""Agent harness — the orchestration layer that runs a skill.

A "skill" (e.g. `ResearchAgent`) only needs to express *intent*:
yield AgentEvents like `plan`, `thinking`, `tool_call`, `delta`. The harness
takes care of everything else:

- assigns `run_id` + `step_id`
- runs `tool_call` events through the ToolRegistry and emits matching
  `tool_result` events
- enforces guardrails: `max_steps`, `max_tool_calls`, wall-time deadline
- persists every event to memory (for replay / eval / debugging)
- creates and updates a `Run` record in the `RunStore` (id, summary, status)
- catches per-step exceptions, emits `error` events, lets the run continue
- emits final `done` (or `error` if fatal)

This is the layer where governance lives — model selection, cost caps,
sandboxing — and where the *observability contract* with the frontend is held.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from uteki_api.artifacts import RunArtifacts, default_artifact_store
from uteki_api.diagnosis import build_trace_diagnosis
from uteki_api.memory import Memory, default_memory
from uteki_api.provenance import SOURCE_CATALOG_ARTIFACT, RunSources, SourceCatalog
from uteki_api.runs import Run, RunStore, default_run_store
from uteki_api.schemas.chat import ChatMessage
from uteki_api.schemas.events import AgentEvent
from uteki_api.tools import ToolRegistry, default_registry

if TYPE_CHECKING:
    from uteki_api.agents.base import BaseAgent


class HarnessLimits:
    """Hard caps the harness enforces over a single run.

    Any breach emits an `error` event and terminates the run; the run's status
    is set to `timeout` for wall-time, `error` otherwise. Limits are
    intentionally simple — `None` means "no cap".
    """

    def __init__(
        self,
        max_steps: int = 20,
        max_tool_calls: int = 30,
        wall_time_seconds: float = 120.0,
        max_input_tokens: int | None = 200_000,
        max_output_tokens: int | None = 8_192,
        max_cost_usd: float | None = 1.0,
    ) -> None:
        self.max_steps = max_steps
        self.max_tool_calls = max_tool_calls
        self.wall_time_seconds = wall_time_seconds
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.max_cost_usd = max_cost_usd


# Sonnet-4-6 pricing (USD per million tokens) — used for rough cost estimates.
# Update when pricing changes. Source of truth still lives at Anthropic.
_PRICE_PER_M_TOKENS: dict[str, dict[str, float]] = {
    # Anthropic Sonnet series — pricing held constant across 3.5 → 4.x
    "claude-sonnet-4-6": {
        "input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_creation": 3.75,
    },
    "claude-sonnet-4-5-20250929": {
        "input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_creation": 3.75,
    },
    "claude-sonnet-4-5": {
        "input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_creation": 3.75,
    },
    "claude-3-5-sonnet-20241022": {
        "input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_creation": 3.75,
    },
    "claude-3-5-sonnet-latest": {
        "input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_creation": 3.75,
    },
    # DeepSeek implicit caching: cache_read is auto-credited by the provider
    # on hit. We track the column but the price column is the same as input
    # (provider returns the discount in `prompt_cache_hit_tokens` reporting).
    "deepseek-chat": {
        "input": 0.27,
        "output": 1.10,
        "cache_read": 0.07,
        "cache_creation": 0.27,
    },
    "deepseek-reasoner": {
        "input": 0.55,
        "output": 2.19,
        "cache_read": 0.14,
        "cache_creation": 0.55,
    },
}


def _estimate_cost(model: str, usage: dict[str, int]) -> float:
    """Best-effort USD estimate from a usage dict. Returns 0.0 on unknown model."""
    # Normalise model name: strip provider prefix
    bare = model.rsplit("/", 1)[-1] if model else ""
    price = _PRICE_PER_M_TOKENS.get(bare)
    if price is None:
        return 0.0
    cost = (
        usage.get("input_tokens", 0)          * price["input"]
        + usage.get("output_tokens", 0)       * price["output"]
        + usage.get("cache_read_tokens", 0)   * price["cache_read"]
        + usage.get("cache_creation_tokens", 0) * price["cache_creation"]
    ) / 1_000_000.0
    return round(cost, 6)


class AgentHarness:
    def __init__(
        self,
        skill: BaseAgent,
        memory: Memory | None = None,
        tools: ToolRegistry | None = None,
        limits: HarnessLimits | None = None,
        *,
        triggered_by: str = "user",
        trigger_reason: str = "",
        run_store: RunStore | None = None,
        skill_version: str | None = None,
        # M4: owner of this run. Required for any user-facing route; defaults
        # to ``"system"`` so internal callers (eval / drift_monitor / tests)
        # don't have to plumb a user through.
        user_id: str = "system",
    ) -> None:
        self.skill = skill
        self.memory = memory or default_memory
        self.tools = tools or default_registry
        self.limits = limits or HarnessLimits()
        self.triggered_by = triggered_by
        self.trigger_reason = trigger_reason
        self.run_store = run_store if run_store is not None else default_run_store
        self.skill_version = skill_version
        self.user_id = user_id or "system"

    async def run(
        self,
        messages: list[ChatMessage],
        session_id: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        run_id = uuid.uuid4().hex[:12]
        session_id = session_id or run_id
        deadline = time.monotonic() + self.limits.wall_time_seconds

        step_count = 0
        tool_count = 0

        # Snapshot the conversational input for the run record.
        user_input = ""
        for m in reversed(messages):
            if m.role == "user":
                user_input = m.content
                break

        delta_buffer: list[str] = []
        final_status: str = "ok"
        usage_totals: dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
        }
        # Resolve the model id for cost estimation. Skills carry a `model`
        # attribute or fall back to DEFAULT_MODEL; if neither is present,
        # cost stays at 0 (unknown pricing).
        cost_model = (
            getattr(self.skill, "model", None)
            or getattr(self.skill, "DEFAULT_MODEL", "")
            or ""
        )

        run_record = Run(
            id=run_id,
            user_id=self.user_id,
            skill=self.skill.name,
            skill_version=self.skill_version,
            triggered_by=self.triggered_by,  # type: ignore[arg-type]
            trigger_reason=self.trigger_reason,
            started_at=time.time(),
            user_input=user_input,
        )
        await self.run_store.create(run_record)

        # Inject the tool-executor callback. Skills that opt into the LLM
        # tool-use loop call this; skills that don't can ignore it. Each call
        # produces a fresh tool_call_id and is bounded by the same per-tool
        # timeout / error handling as skill-yielded tool_call events.
        self.skill._tool_executor = self._make_tool_executor(run_id)

        # Inject the artifact facade. Skills write named files via this so
        # downstream agents (planner → generator → evaluator, M6+) can read
        # them, and the frontend can list / preview / download.
        self.skill.artifacts = RunArtifacts(
            store=default_artifact_store,
            run_id=run_id,
            written_by=self.skill.name,
            user_id=self.user_id,
        )
        self.skill.sources = RunSources(
            catalog=SourceCatalog(run_id=run_id),
            run_id=run_id,
            user_id=self.user_id,
        )

        start_event = AgentEvent(
            type="run_start",
            run_id=run_id,
            data={"agent": self.skill.name, "session_id": session_id},
        )
        await self.memory.append_event(self.user_id, session_id, start_event)
        await self.run_store.append_event(run_id, start_event)
        yield start_event

        try:
            async for raw in self.skill.run(messages):
                if time.monotonic() > deadline:
                    err = AgentEvent(type="error", run_id=run_id, data={"reason": "deadline"})
                    await self.memory.append_event(self.user_id, session_id, err)
                    await self.run_store.append_event(run_id, err)
                    yield err
                    final_status = "timeout"
                    break

                event = raw.model_copy(update={"run_id": run_id})

                if event.type == "step_start":
                    step_count += 1
                    if step_count > self.limits.max_steps:
                        err = AgentEvent(
                            type="error",
                            run_id=run_id,
                            data={"reason": "max_steps_exceeded"},
                        )
                        await self.memory.append_event(self.user_id, session_id, err)
                        await self.run_store.append_event(run_id, err)
                        yield err
                        final_status = "error"
                        break

                if event.type == "tool_call":
                    tool_count += 1
                    if tool_count > self.limits.max_tool_calls:
                        err = AgentEvent(
                            type="error",
                            run_id=run_id,
                            data={"reason": "max_tool_calls_exceeded"},
                        )
                        await self.memory.append_event(self.user_id, session_id, err)
                        await self.run_store.append_event(run_id, err)
                        yield err
                        final_status = "error"
                        break

                    await self.memory.append_event(self.user_id, session_id, event)
                    await self.run_store.append_event(run_id, event)
                    yield event

                    # If a skill yielded a tool_call that it (or its LLM tool
                    # loop) has *already* executed, don't double-dispatch —
                    # the matching tool_result event will follow on the next
                    # iteration. Otherwise harness dispatches as before.
                    review_event = self._tool_review_event(run_id, event)
                    if review_event is not None:
                        await self.memory.append_event(self.user_id, session_id, review_event)
                        await self.run_store.append_event(run_id, review_event)
                        yield review_event

                        blocked = self._blocked_tool_result(run_id, event)
                        await self.memory.append_event(self.user_id, session_id, blocked)
                        await self.run_store.append_event(run_id, blocked)
                        yield blocked
                        continue

                    if not event.data.get("_already_executed"):
                        result_event = await self._invoke_tool(run_id, event)
                        await self.memory.append_event(self.user_id, session_id, result_event)
                        await self.run_store.append_event(run_id, result_event)
                        yield result_event
                    continue

                if event.type == "await_review":
                    # M5: persist + auto-approve + tag the run, then continue.
                    # 005.2 will plumb compliance_mode + real pause/approve.
                    await self.memory.append_event(self.user_id, session_id, event)
                    await self.run_store.append_event(run_id, event)
                    yield event
                    record = await self.run_store.get(run_id)
                    if "auto-approved" not in record.tags:
                        record.tags.append("auto-approved")
                    continue

                if event.type == "delta":
                    text = event.data.get("text", "")
                    if isinstance(text, str):
                        delta_buffer.append(text)

                if event.type == "usage":
                    for k in usage_totals:
                        v = event.data.get(k, 0)
                        if isinstance(v, int):
                            usage_totals[k] += v

                    # Budget guards — token caps and cost cap. Trip → error.
                    budget_err = self._check_budget(usage_totals, cost_model)
                    if budget_err is not None:
                        err = AgentEvent(
                            type="error",
                            run_id=run_id,
                            data={"reason": budget_err, "usage": dict(usage_totals)},
                        )
                        await self.memory.append_event(self.user_id, session_id, err)
                        await self.run_store.append_event(run_id, err)
                        yield err
                        final_status = "error"
                        break

                if event.type == "error":
                    final_status = "error"

                await self.memory.append_event(self.user_id, session_id, event)
                await self.run_store.append_event(run_id, event)
                yield event

        except Exception as e:  # noqa: BLE001
            err = AgentEvent(type="error", run_id=run_id, data={"reason": str(e)})
            await self.memory.append_event(self.user_id, session_id, err)
            await self.run_store.append_event(run_id, err)
            yield err
            final_status = "error"

        primary_event = await self._primary_artifact_event(run_id, delta_buffer)
        if primary_event is not None:
            await self.memory.append_event(self.user_id, session_id, primary_event)
            await self.run_store.append_event(run_id, primary_event)
            yield primary_event

        source_event = await self._source_catalog_event(run_id)
        if source_event is not None:
            await self.memory.append_event(self.user_id, session_id, source_event)
            await self.run_store.append_event(run_id, source_event)
            yield source_event

        diagnosis_event = await self._trace_diagnosis_event(run_id, usage_totals, delta_buffer)
        if diagnosis_event is not None:
            await self.memory.append_event(self.user_id, session_id, diagnosis_event)
            await self.run_store.append_event(run_id, diagnosis_event)
            yield diagnosis_event

        done = AgentEvent(type="done", run_id=run_id, data={"steps": step_count, "tools": tool_count})
        await self.memory.append_event(self.user_id, session_id, done)
        await self.run_store.append_event(run_id, done)
        yield done

        summary = "".join(delta_buffer)[:200]
        # Narrow the status to the literal type expected by RunStore.finish.
        from uteki_api.runs.models import RunStatus  # local import to keep top tidy
        status: RunStatus = final_status  # type: ignore[assignment]

        # Persist final usage_summary on the Run record before finish().
        run_record_now = await self.run_store.get(run_id)
        run_record_now.usage_summary.input_tokens = usage_totals["input_tokens"]
        run_record_now.usage_summary.output_tokens = usage_totals["output_tokens"]
        run_record_now.usage_summary.cache_read_tokens = usage_totals["cache_read_tokens"]
        run_record_now.usage_summary.cache_creation_tokens = usage_totals["cache_creation_tokens"]
        run_record_now.usage_summary.cost_usd = _estimate_cost(cost_model, usage_totals)

        await self.run_store.finish(run_id, status, summary)

    def _check_budget(
        self,
        usage_totals: dict[str, int],
        model: str,
    ) -> str | None:
        """Return a budget-violation reason string, or None if all good."""
        limits = self.limits
        if (
            limits.max_input_tokens is not None
            and usage_totals["input_tokens"] > limits.max_input_tokens
        ):
            return "max_input_tokens_exceeded"
        if (
            limits.max_output_tokens is not None
            and usage_totals["output_tokens"] > limits.max_output_tokens
        ):
            return "max_output_tokens_exceeded"
        if limits.max_cost_usd is not None:
            cost = _estimate_cost(model, usage_totals)
            if cost > limits.max_cost_usd:
                return f"max_cost_usd_exceeded (${cost:.4f})"
        return None

    def _make_tool_executor(self, run_id: str):
        """Return a coroutine the LLM client can use to execute tools.

        Skills doing the LLM tool-use loop pass this into
        ``LLMClient.stream_chat_with_tools``. Each call reuses ``_invoke_tool``
        so timeouts / errors / unknown-tool fallbacks behave identically to
        the harness-driven path. The skill is still responsible for emitting
        the ``tool_call`` and ``tool_result`` AgentEvents — we just execute.
        """
        from uteki_api.llm.usage import ToolCallFulfilled

        async def execute(name: str, args: dict) -> ToolCallFulfilled:
            # Reuse _invoke_tool by constructing a synthetic call event. We
            # don't write the call/result events to memory or run_store here;
            # the skill emits them as AgentEvents marked _already_executed.
            call_id = uuid.uuid4().hex[:8]
            synthetic = AgentEvent(
                type="tool_call",
                run_id=run_id,
                step_id=call_id,
                data={"name": name, "args": args},
            )
            result_event = await self._invoke_tool(run_id, synthetic)
            d = result_event.data
            return ToolCallFulfilled(
                call_id=call_id,
                name=d.get("name") or name,
                ok=bool(d.get("ok")),
                summary=str(d.get("summary") or ""),
                preview=d.get("preview"),
                error=d.get("error"),
            )

        return execute

    async def _invoke_tool(self, run_id: str, call: AgentEvent) -> AgentEvent:
        name = call.data.get("name", "")
        args = call.data.get("args", {}) or {}
        tool_call_id = call.step_id or uuid.uuid4().hex[:8]

        try:
            tool = self.tools.get(name)
        except KeyError as e:
            return AgentEvent(
                type="tool_result",
                run_id=run_id,
                step_id=tool_call_id,
                parent_id=call.step_id,
                data={"name": name, "ok": False, "error": str(e)},
            )

        if tool.risk_level == "high":
            return self._blocked_tool_result(run_id, call)

        try:
            result = await asyncio.wait_for(tool.run(**args), timeout=30.0)
        except TimeoutError:
            return AgentEvent(
                type="tool_result",
                run_id=run_id,
                step_id=tool_call_id,
                parent_id=call.step_id,
                data={"name": name, "ok": False, "error": "tool_timeout"},
            )
        except Exception as e:  # noqa: BLE001
            return AgentEvent(
                type="tool_result",
                run_id=run_id,
                step_id=tool_call_id,
                parent_id=call.step_id,
                data={"name": name, "ok": False, "error": str(e)},
            )

        source_ids = await self._register_tool_sources(result.sources, tool_name=name)
        preview: Any = result.data
        if source_ids:
            if isinstance(preview, dict):
                preview = {**preview, "_source_ids": source_ids}
            else:
                preview = {"value": preview, "_source_ids": source_ids}

        return AgentEvent(
            type="tool_result",
            run_id=run_id,
            step_id=tool_call_id,
            parent_id=call.step_id,
            data={
                "name": name,
                "ok": result.ok,
                "summary": result.summary,
                "preview": preview,
                "error": result.error,
            },
        )

    def _tool_review_event(self, run_id: str, call: AgentEvent) -> AgentEvent | None:
        name = call.data.get("name", "")
        try:
            tool = self.tools.get(name)
        except KeyError:
            return None
        if tool.risk_level != "high":
            return None
        return AgentEvent(
            type="await_review",
            run_id=run_id,
            step_id=call.step_id,
            parent_id=call.step_id,
            data={
                "checkpoint": "high_risk_tool",
                "tool_name": name,
                "risk_level": tool.risk_level,
                "args": call.data.get("args", {}) or {},
                "reason": "high-risk tool requires explicit approval before execution",
                "ready_artifacts": [],
                "auto_approved": False,
            },
        )

    @staticmethod
    def _blocked_tool_result(run_id: str, call: AgentEvent) -> AgentEvent:
        name = call.data.get("name", "")
        tool_call_id = call.step_id or uuid.uuid4().hex[:8]
        return AgentEvent(
            type="tool_result",
            run_id=run_id,
            step_id=tool_call_id,
            parent_id=call.step_id,
            data={
                "name": name,
                "ok": False,
                "summary": "blocked by tool governance",
                "preview": None,
                "error": "high_risk_tool_requires_review",
            },
        )

    async def _register_tool_sources(
        self,
        sources: list[dict[str, Any]],
        *,
        tool_name: str,
    ) -> list[int]:
        """Register tool-provided source metadata into the run catalog.

        Source metadata is best-effort. Malformed source entries should make
        citation verification weaker, not break the tool call itself.
        """
        run_sources = getattr(self.skill, "sources", None)
        if run_sources is None or not sources:
            return []
        ids: list[int] = []
        for source in sources:
            if not isinstance(source, dict):
                continue
            try:
                dp_id = await run_sources.add(
                    {
                        "source_type": "tool_result",
                        "key": f"{tool_name}_result",
                        "value": source,
                        **source,
                    }
                )
            except Exception:
                continue
            if dp_id:
                ids.append(dp_id)
        return ids

    async def _source_catalog_event(self, run_id: str) -> AgentEvent | None:
        """Persist the run source catalog as an artifact and return its event."""
        run_sources = getattr(self.skill, "sources", None)
        artifacts = getattr(self.skill, "artifacts", None)
        if run_sources is None or artifacts is None or len(run_sources) == 0:
            return None
        try:
            if await artifacts.exists(SOURCE_CATALOG_ARTIFACT):
                return None
            art = await run_sources.write_artifact(artifacts)
        except Exception as e:  # noqa: BLE001
            return AgentEvent(
                type="log",
                run_id=run_id,
                data={
                    "level": "warn",
                    "message": "failed to persist source catalog",
                    "extra": {"error": str(e)},
                },
            )
        return AgentEvent(
            type="artifact_written",
            run_id=run_id,
            data={
                "name": art.name,
                "kind": art.kind,
                "size_bytes": art.size_bytes,
                "written_by": art.written_by,
                "description": art.description,
                "url": f"/api/runs/{art.run_id}/artifacts/{art.name}",
                "role": art.role,
                "display_name": art.display_name,
            },
        )

    async def _primary_artifact_event(
        self,
        run_id: str,
        delta_buffer: list[str],
    ) -> AgentEvent | None:
        """Ensure a completed run has a stable primary markdown artifact."""
        artifacts = getattr(self.skill, "artifacts", None)
        if artifacts is None or await artifacts.exists("final-report.md"):
            return None

        content = ""
        for candidate in ("investment-memo.md", "final-research.md", "research.md"):
            try:
                if await artifacts.exists(candidate):
                    content = await artifacts.read_text(candidate)
                    break
            except OSError:
                continue
        if not content:
            content = "".join(delta_buffer).strip()
        if not content:
            return None

        art = await artifacts.write(
            name="final-report.md",
            content=content,
            kind="markdown",
            description="Primary run deliverable",
            role="primary",
            display_name="Final report",
        )
        return AgentEvent(
            type="artifact_written",
            run_id=run_id,
            data={
                "name": art.name,
                "kind": art.kind,
                "size_bytes": art.size_bytes,
                "written_by": art.written_by,
                "description": art.description,
                "url": f"/api/runs/{art.run_id}/artifacts/{art.name}",
                "role": art.role,
                "display_name": art.display_name,
            },
        )

    async def _trace_diagnosis_event(
        self,
        run_id: str,
        usage_totals: dict[str, int],
        delta_buffer: list[str],
    ) -> AgentEvent | None:
        artifacts = getattr(self.skill, "artifacts", None)
        if artifacts is None or await artifacts.exists("trace-diagnosis.json"):
            return None
        try:
            run = await self.run_store.get(run_id, self.user_id)
            run_sources = getattr(self.skill, "sources", None)
            diagnosis = build_trace_diagnosis(
                run.events,
                usage_totals=usage_totals,
                source_catalog=run_sources.catalog if run_sources is not None else None,
                final_text="".join(delta_buffer),
            )
            art = await artifacts.write(
                name="trace-diagnosis.json",
                content=json.dumps(diagnosis, ensure_ascii=False, indent=2),
                kind="json",
                description="Derived run trace diagnosis",
                role="diagnosis",
                display_name="Trace diagnosis",
            )
        except Exception as e:  # noqa: BLE001
            return AgentEvent(
                type="log",
                run_id=run_id,
                data={
                    "level": "warn",
                    "message": "failed to persist trace diagnosis",
                    "extra": {"error": str(e)},
                },
            )
        return AgentEvent(
            type="artifact_written",
            run_id=run_id,
            data={
                "name": art.name,
                "kind": art.kind,
                "size_bytes": art.size_bytes,
                "written_by": art.written_by,
                "description": art.description,
                "url": f"/api/runs/{art.run_id}/artifacts/{art.name}",
                "role": art.role,
                "display_name": art.display_name,
            },
        )
