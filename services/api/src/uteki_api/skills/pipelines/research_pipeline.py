"""ResearchPipeline — meta-skill that orchestrates Planner → Research → Evaluator.

Why a meta-skill (not a harness change): the harness contract is "one skill
per run". A pipeline keeps that invariant — to the harness it looks like one
skill that just happens to yield a lot of events. The pipeline manages its
own delegation: it grabs the named sub-skills from ``default_skills``, shares
its run-scoped ``_tool_executor`` and ``artifacts`` facade with them, and
forwards every event they yield (wrapped between ``subagent_start`` /
``subagent_end`` markers so the frontend can render them as nested blocks).

Loop:
  1. Run Planner → produces sprint-contract.json + plan.md.
  2. For up to ``contract.max_iterations`` rounds:
     a. Run Research (Generator) → writes final-research.md.
     b. Persist accumulated events to ``run-trace.json`` so Evaluator's
        ``tool_call_in_run`` verifier can see the full tool history.
     c. Run Evaluator → produces eval-report.json.
     d. If decision == "approve" → break.
        If "revise" → append suggestions to messages and loop.
        If "reject" → break (rare; treated as final).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from uteki_api.agents.base import BaseAgent
from uteki_api.agents.harness import HarnessLimits
from uteki_api.schemas.chat import ChatMessage
from uteki_api.schemas.events import AgentEvent


class ResearchPipeline(BaseAgent):
    name = "research_pipeline"

    DEFAULT_TOOLS: list[str] = []
    # The pipeline itself doesn't call an LLM. The model id is recorded so the
    # harness has a non-empty value for cost reporting; sub-skills carry their
    # own models and their usage events flow up as-is.
    DEFAULT_MODEL = "deepseek/deepseek-chat"

    DEFAULT_MAX_ITERATIONS = 3

    def __init__(self, model: str | None = None) -> None:
        self.model = model

    def recommended_limits(self) -> HarnessLimits:
        # All sub-skills run under one harness, so calls + tokens + cost
        # add up across Planner + Research(0..N) + Evaluator(0..N) + N
        # judge sub-calls. Real-LLM observation across three runs of one
        # revise iteration (DeepSeek + AiHubmix, 2026-05-25):
        #   - tool_call events:  ~32-37  (need >30)
        #   - input_tokens:      ~220-225K  (need >200K — every iteration
        #                        re-sends accumulating context)
        #   - output_tokens:     ~7-8.5K   (default 8192 trips at ~8.4K)
        #   - cost:              ~$0.08-0.09  (default $1 is plenty)
        # Widen the 4 constraints that bind in practice. Cost cap stays at
        # platform default so a runaway loop still aborts.
        return HarnessLimits(
            max_steps=60,
            max_tool_calls=120,
            wall_time_seconds=600.0,
            max_input_tokens=800_000,
            max_output_tokens=32_768,
        )

    def current_signature(self) -> dict[str, Any]:
        return {
            # No SKILL.md — pipeline behavior lives in this Python file,
            # not in markdown. Version-history UI skips rendering when
            # prompt is empty; auto-bump fires on `params` changes
            # (e.g. max_iterations).
            "prompt": "",
            "tool_names": list(self.DEFAULT_TOOLS),
            "model": self.model or self.DEFAULT_MODEL,
            "params": {"max_iterations": self.DEFAULT_MAX_ITERATIONS},
        }

    async def run(
        self, messages: list[ChatMessage]
    ) -> AsyncIterator[AgentEvent]:
        # We mutate ``messages`` between iterations to feed evaluator
        # suggestions back to the generator; copy so the caller's list is safe.
        working_messages: list[ChatMessage] = list(messages)
        run_events: list[dict[str, Any]] = []

        yield AgentEvent(
            type="plan",
            data={
                "steps": [
                    "Planner: 拆解需求 → sprint-contract.json",
                    "Research (Generator): 看 contract 写 final-research.md",
                    "Evaluator: 按 contract 跑 verifier → eval-report.json",
                    "若 revise: 追加 suggestions 给下一轮 generator",
                ]
            },
        )

        # ── Phase 1: Planner ────────────────────────────────────────────
        async for ev in self._delegate("planner", working_messages, run_events):
            yield ev

        contract = await self._read_contract()
        max_iter = self._coerce_max_iter(contract.get("max_iterations") if contract else None)

        last_decision: str | None = None

        # ── Phase 2: Generator + Evaluator loop ─────────────────────────
        for iteration in range(max_iter):
            # Persist accumulated events so Evaluator's tool_call_in_run can
            # see them. We do this BEFORE the evaluator runs (after the
            # generator's events have flowed through `run_events`).
            async for ev in self._delegate(
                "research",
                working_messages,
                run_events,
                iteration=iteration,
            ):
                yield ev

            await self._persist_run_trace(run_events)

            async for ev in self._delegate(
                "evaluator",
                working_messages,
                run_events,
                iteration=iteration,
            ):
                yield ev

            report = await self._read_report()
            decision = (report or {}).get("decision") or "revise"
            last_decision = decision

            if decision == "approve":
                yield AgentEvent(
                    type="log",
                    data={
                        "level": "info",
                        "message": f"pipeline: evaluator approved on iteration {iteration}",
                    },
                )
                break
            if decision == "reject":
                yield AgentEvent(
                    type="log",
                    data={
                        "level": "warn",
                        "message": (
                            f"pipeline: evaluator rejected on iteration {iteration};"
                            " stopping loop"
                        ),
                    },
                )
                break

            # revise → append suggestions to drive next generator round.
            suggestions = (report or {}).get("suggestions") or []
            if not suggestions:
                # Nothing actionable to revise on — stop to avoid burning budget.
                yield AgentEvent(
                    type="log",
                    data={
                        "level": "warn",
                        "message": "pipeline: evaluator wants revise but had no suggestions; stopping",
                    },
                )
                break

            joined = "\n".join(f"- {s}" for s in suggestions)
            working_messages.append(
                ChatMessage(
                    role="user",
                    content=(
                        "Evaluator 反馈，请按以下改进重写研究草稿，"
                        "覆盖原 sprint-contract.json 的所有 acceptance_criteria：\n"
                        f"{joined}"
                    ),
                )
            )

        # Pipeline-level summary event for the trace.
        yield AgentEvent(
            type="log",
            data={
                "level": "info",
                "message": (
                    "pipeline: complete · "
                    f"final_decision={last_decision or 'n/a'}"
                ),
            },
        )

    # ── delegation ──────────────────────────────────────────────────────

    async def _delegate(
        self,
        skill_name: str,
        messages: list[ChatMessage],
        run_events: list[dict[str, Any]],
        *,
        iteration: int | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run a registered sub-skill, sharing the pipeline's run-scoped state.

        Yields ``subagent_start`` → all sub-skill events → ``subagent_end``.
        Appends each sub-skill event (serialised) to ``run_events`` so later
        skills (e.g. Evaluator) can read the full trace.
        """
        from uteki_api.skills import default_skills  # local import to dodge cycle

        meta: dict[str, Any] = {"name": skill_name}
        if iteration is not None:
            meta["iteration"] = iteration

        yield AgentEvent(
            type="subagent_start",
            step_id=uuid.uuid4().hex[:8],
            data=meta,
        )

        try:
            # create() not get() — concurrent pipeline runs share the same
            # singleton planner/research/evaluator otherwise. Writing
            # sub.artifacts = self.artifacts mid-run would race.
            sub = default_skills.create(skill_name)
        except KeyError:
            yield AgentEvent(
                type="error",
                data={"reason": f"pipeline: unknown sub-skill {skill_name!r}"},
            )
            yield AgentEvent(type="subagent_end", data=meta)
            return

        # Share the run-scoped injectables. The harness already wired ours up;
        # the sub-skill must see the same tool executor (so budget / audit
        # are unified) and the same artifacts facade (so reads find what
        # earlier sub-skills wrote in this run).
        sub._tool_executor = self._tool_executor
        sub.artifacts = self.artifacts
        sub.sources = self.sources

        try:
            async for ev in sub.run(messages):
                run_events.append(ev.model_dump())
                yield ev
        except Exception as e:  # noqa: BLE001 — surface, never re-raise
            yield AgentEvent(
                type="error",
                data={"reason": f"pipeline: sub-skill {skill_name!r} crashed: {e}"},
            )

        yield AgentEvent(type="subagent_end", data=meta)

    # ── artifact helpers ────────────────────────────────────────────────

    async def _read_contract(self) -> dict[str, Any] | None:
        if self.artifacts is None or not await self.artifacts.exists("sprint-contract.json"):
            return None
        try:
            text = await self.artifacts.read_text("sprint-contract.json")
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    async def _read_report(self) -> dict[str, Any] | None:
        if self.artifacts is None or not await self.artifacts.exists("eval-report.json"):
            return None
        try:
            text = await self.artifacts.read_text("eval-report.json")
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    async def _persist_run_trace(self, run_events: list[dict[str, Any]]) -> None:
        if self.artifacts is None:
            return
        await self.artifacts.write(
            name="run-trace.json",
            content=json.dumps(run_events, ensure_ascii=False, default=str),
            kind="json",
            description="Flattened event stream of sub-skill runs in this pipeline",
            role="trace",
            display_name="Run trace",
        )

    @staticmethod
    def _coerce_max_iter(value: Any) -> int:
        if isinstance(value, int) and 1 <= value <= 5:
            return value
        return ResearchPipeline.DEFAULT_MAX_ITERATIONS
