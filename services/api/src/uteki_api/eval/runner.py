"""Eval framework — score the agent on a set of cases.

A case = (input messages, expected behaviors). Scoring dimensions:

- **correctness**: does the final answer cover required points?
  (substring contains list, or LLM-as-judge — judge stubbed for now)
- **tool_use**: did the agent call the right tools?
- **latency**: wall time
- **cost**: token usage from `usage` events

The runner collects events from the harness, scores each case, and writes a
report. Wire `/api/eval/run` for one-click execution; persist reports for trend
tracking.

Future:
- LLM-as-judge with a separate `judge_model`
- Regression alerting (compare to baseline)
- A/B between models or prompt variants
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from uteki_api.agents.harness import AgentHarness
from uteki_api.agents.research import ResearchAgent
from uteki_api.artifacts import default_artifact_store
from uteki_api.eval.store import EvalRecord, default_eval_history
from uteki_api.schemas.chat import ChatMessage


class EvalCase(BaseModel):
    id: str
    description: str
    messages: list[ChatMessage]
    expected_substrings: list[str] = []
    expected_tools: list[str] = []
    # M6: optional named skill / pipeline. When set, the runner constructs a
    # fresh harness around the registered skill of that name; falls back to
    # the runner's default (Research) otherwise.
    agent: str | None = None


class CaseResult(BaseModel):
    case_id: str
    passed: bool
    latency_ms: int
    final_text: str
    tools_called: list[str]
    scores: dict[str, float]
    notes: str = ""


class EvalReport(BaseModel):
    started_at: float
    duration_ms: int
    results: list[CaseResult]

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.passed) / len(self.results)


CASES_DIR = Path(__file__).parent / "cases"


class EvalRunner:
    def __init__(
        self,
        harness: AgentHarness | None = None,
        *,
        user_id: str = "system",
    ) -> None:
        # M4: every run produced + every history record written is scoped to
        # ``user_id``. Defaults to ``"system"`` for platform-level evals
        # (drift_monitor, scheduled jobs, tests).
        self.user_id = user_id or "system"
        self.harness = harness or AgentHarness(
            skill=ResearchAgent(), user_id=self.user_id
        )

    @staticmethod
    def load_cases() -> list[EvalCase]:
        cases: list[EvalCase] = []
        if not CASES_DIR.exists():
            return cases
        for path in sorted(CASES_DIR.glob("*.json")):
            cases.append(EvalCase.model_validate_json(path.read_text()))
        return cases

    async def run_case(self, case: EvalCase) -> CaseResult:
        start = time.monotonic()
        final_chunks: list[str] = []
        tools_called: list[str] = []
        run_id: str | None = None

        # If the case names an agent, build a fresh harness around it so
        # case-level routing (e.g. agent=research_pipeline for M6) works.
        harness = self.harness
        if case.agent:
            try:
                from uteki_api.skills import default_skills

                skill = default_skills.create(case.agent)
                harness = AgentHarness(skill=skill, user_id=self.user_id)
            except KeyError:
                pass  # fall back to default harness silently

        async for ev in harness.run(case.messages, session_id=f"eval:{case.id}"):
            if ev.type == "run_start" and ev.run_id and run_id is None:
                run_id = ev.run_id
            if ev.type == "delta":
                final_chunks.append(ev.data.get("text", ""))
            elif ev.type == "tool_call":
                tools_called.append(ev.data.get("name", ""))

        latency_ms = int((time.monotonic() - start) * 1000)
        final_text = "".join(final_chunks)

        substring_score = (
            sum(1 for s in case.expected_substrings if s in final_text)
            / len(case.expected_substrings)
            if case.expected_substrings
            else 1.0
        )
        tool_score = (
            sum(1 for t in case.expected_tools if t in tools_called)
            / len(case.expected_tools)
            if case.expected_tools
            else 1.0
        )
        passed = substring_score >= 0.5 and tool_score >= 0.5

        # M7: record this run in the history store for trend / drift tracking.
        # Best-effort — never fail the eval because of disk issues.
        try:
            judge_scores, decision = await self._read_evaluator_artifacts(run_id)
            await default_eval_history.append(
                self.user_id,
                EvalRecord(
                    case_id=case.id,
                    pass_rate=1.0 if passed else 0.0,
                    judge_scores=judge_scores,
                    decision=decision,
                    run_id=run_id,
                    notes=f"sub={substring_score:.2f} tool={tool_score:.2f}",
                ),
            )
        except Exception:  # noqa: BLE001 — history is observational, never fatal
            pass

        return CaseResult(
            case_id=case.id,
            passed=passed,
            latency_ms=latency_ms,
            final_text=final_text,
            tools_called=tools_called,
            scores={"substring": substring_score, "tool": tool_score},
        )

    async def _read_evaluator_artifacts(
        self,
        run_id: str | None,
    ) -> tuple[dict[str, int], str | None]:
        """If this run produced evaluator artifacts, pull judge scores + decision.

        Returns ``({}, None)`` when the run wasn't a pipeline run (no
        evaluator artifacts) or anything failed to parse — never raises.
        """
        if not run_id:
            return {}, None
        judge_scores: dict[str, int] = {}
        decision: str | None = None
        try:
            artifacts = await default_artifact_store.list(run_id, self.user_id)
        except Exception:  # noqa: BLE001
            return {}, None
        for art in artifacts:
            if art.name.startswith("judge-") and art.name.endswith(".json"):
                try:
                    _, body = await default_artifact_store.read(
                        run_id, art.name, self.user_id
                    )
                    obj = json.loads(body)
                    rubric = obj.get("rubric") or art.name[len("judge-") : -len(".json")]
                    score = int(obj.get("score_1_to_10", 0))
                    judge_scores[rubric] = score
                except Exception:  # noqa: BLE001
                    continue
            elif art.name == "eval-report.json":
                try:
                    _, body = await default_artifact_store.read(
                        run_id, art.name, self.user_id
                    )
                    obj = json.loads(body)
                    decision = obj.get("decision")
                except Exception:  # noqa: BLE001
                    continue
        return judge_scores, decision

    async def run_all(self) -> EvalReport:
        start = time.monotonic()
        cases = self.load_cases()
        results = [await self.run_case(c) for c in cases]
        return EvalReport(
            started_at=time.time(),
            duration_ms=int((time.monotonic() - start) * 1000),
            results=results,
        )

    async def run_dict(self, raw: dict[str, Any]) -> CaseResult:
        return await self.run_case(EvalCase.model_validate(raw))
