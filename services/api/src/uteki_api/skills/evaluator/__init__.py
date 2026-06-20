"""Evaluator skill — deterministic, skeptical reviewer.

Why: per Anthropic's harness design, "Generator does not judge itself".
This skill reads the Planner's sprint contract and the Generator's draft,
runs the named verifier per criterion, and emits a verdict report. No LLM
call is required in the M6 implementation — every verifier is a pure Python
function (regex / event scan / number-near-label / stubbed judge).

Reads:  sprint-contract.json, final-research.md (or final-earnings.md),
        run-trace.json
Writes: eval-report.json
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from uteki_api.agents.base import BaseAgent
from uteki_api.provenance import SOURCE_CATALOG_ARTIFACT
from uteki_api.schemas.chat import ChatMessage
from uteki_api.schemas.events import AgentEvent
from uteki_api.skills.evaluator.verifiers import VERIFIERS
from uteki_api.skills.loader import load_skill_prompt


class EvaluatorSkill(BaseAgent):
    name = "evaluator"

    DEFAULT_TOOLS: list[str] = []
    # Model isn't used today (verifiers are pure Python) but recorded for
    # cost reporting + future M7 LLM-as-judge integration.
    DEFAULT_MODEL = "deepseek/deepseek-chat"

    # Candidate filenames to look for the generator's draft, in order.
    DRAFT_NAMES = ("final-research.md", "final-earnings.md")

    def __init__(self, model: str | None = None) -> None:
        self.model = model
        self.system_prompt, self.refs = load_skill_prompt("evaluator")
        tools_prefix = self.tools_allowlist_prefix(self.DEFAULT_TOOLS)
        if tools_prefix:
            self.system_prompt = f"{tools_prefix}\n\n---\n\n{self.system_prompt}"

    def current_signature(self) -> dict[str, Any]:
        return {
            "prompt": self.system_prompt,
            "tool_names": list(self.DEFAULT_TOOLS),
            "model": self.model or self.DEFAULT_MODEL,
            "params": {"references": list(self.refs)},
        }

    async def run(
        self, messages: list[ChatMessage]  # noqa: ARG002 — evaluator reads artifacts, not messages
    ) -> AsyncIterator[AgentEvent]:
        yield AgentEvent(
            type="plan",
            data={
                "steps": [
                    "读取 sprint-contract.json + 最新 draft",
                    "对每条 acceptance criterion 跑 verifier",
                    "决定 decision (approve / revise / reject)",
                    "写 eval-report.json",
                ]
            },
        )

        sid = uuid.uuid4().hex[:8]
        yield AgentEvent(type="step_start", step_id=sid, data={"title": "跑 verifier"})

        if self.artifacts is None:
            yield AgentEvent(
                type="error",
                step_id=sid,
                data={"reason": "evaluator: artifacts facade missing"},
            )
            yield AgentEvent(type="step_end", step_id=sid, data={"status": "error"})
            return

        # 1. Load contract.
        contract = await self._load_contract()
        if contract is None:
            yield AgentEvent(
                type="error",
                step_id=sid,
                data={"reason": "evaluator: sprint-contract.json missing or invalid"},
            )
            yield AgentEvent(type="step_end", step_id=sid, data={"status": "error"})
            return

        # 2. Load draft text (try each known name in order).
        draft_text, draft_name = await self._load_draft()

        # 3. Load run trace (optional; empty list if missing).
        run_events = await self._load_run_trace()
        source_catalog = await self._load_source_catalog()

        # 4. Run verifiers.
        # Detect the generator's model from the run trace so the LLM judge
        # doesn't grade its own output (Anthropic "external eval" rule).
        avoid_model = self._infer_generator_model(run_events)

        verdicts: list[dict[str, Any]] = []
        suggestions: list[str] = []
        passed_count = 0
        failed_count = 0

        for crit in contract.get("acceptance_criteria", []):
            cid = str(crit.get("id") or "?")
            must = str(crit.get("must") or "")
            verifier_name = str(crit.get("verifier") or "")
            args = crit.get("args") if isinstance(crit.get("args"), dict) else {}

            result = await self._invoke_verifier(
                verifier_name,
                args,
                draft_text=draft_text,
                run_events=run_events,
                source_catalog=source_catalog,
                avoid_model=avoid_model,
            )
            passed = result[0]
            notes = result[1]
            judge_payload = result[2] if len(result) > 2 else None

            verdicts.append(
                {
                    "criterion_id": cid,
                    "verifier": verifier_name,
                    "passed": passed,
                    "notes": notes,
                }
            )
            if passed:
                passed_count += 1
            else:
                failed_count += 1
                suggestions.append(
                    f"[{cid}] {must} — 当前未通过：{notes}"
                )

            # llm_judge_score: persist the full judge rationale as its own
            # artifact so it shows up alongside eval-report.json in the run
            # detail page. Other verifiers don't produce extra payload.
            if judge_payload is not None and self.artifacts is not None:
                rubric_name = str(args.get("rubric") or verifier_name)
                judge_art_name = f"judge-{rubric_name}.json"
                judge_art = await self.artifacts.write(
                    name=judge_art_name,
                    content=json.dumps(judge_payload.model_dump(), ensure_ascii=False, indent=2),
                    kind="json",
                    description=(
                        f"LLM judge result: {rubric_name}="
                        f"{judge_payload.score_1_to_10}/10 (by {judge_payload.judge_model})"
                    ),
                    role="evaluation",
                    display_name=f"Judge: {rubric_name}",
                )
                yield AgentEvent(
                    type="artifact_written",
                    data={
                        "name": judge_art.name,
                        "kind": judge_art.kind,
                        "size_bytes": judge_art.size_bytes,
                        "written_by": judge_art.written_by,
                        "description": judge_art.description,
                        "url": f"/api/runs/{judge_art.run_id}/artifacts/{judge_art.name}",
                    },
                )

        # 5. Decide.
        if failed_count == 0 and passed_count > 0:
            decision = "approve"
        elif passed_count == 0 and failed_count > 0:
            decision = "reject"
        else:
            decision = "revise"

        report: dict[str, Any] = {
            "decision": decision,
            "verdicts": verdicts,
            "suggestions": suggestions,
            "draft_name": draft_name,
            "summary": (
                f"{passed_count}/{passed_count + failed_count} criteria passed"
            ),
        }

        yield AgentEvent(type="step_end", step_id=sid, data={"status": "ok"})

        art = await self.artifacts.write(
            name="eval-report.json",
            content=json.dumps(report, ensure_ascii=False, indent=2),
            kind="json",
            description=f"Evaluator verdict: {decision}",
            role="evaluation",
            display_name="Eval report",
        )
        yield AgentEvent(
            type="artifact_written",
            data={
                "name": art.name,
                "kind": art.kind,
                "size_bytes": art.size_bytes,
                "written_by": art.written_by,
                "description": art.description,
                "url": f"/api/runs/{art.run_id}/artifacts/{art.name}",
            },
        )

    # ── loaders ─────────────────────────────────────────────────────────

    async def _load_contract(self) -> dict[str, Any] | None:
        if self.artifacts is None or not await self.artifacts.exists("sprint-contract.json"):
            return None
        try:
            text = await self.artifacts.read_text("sprint-contract.json")
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    async def _load_draft(self) -> tuple[str, str]:
        if self.artifacts is None:
            return "", ""
        for candidate in self.DRAFT_NAMES:
            if await self.artifacts.exists(candidate):
                try:
                    return await self.artifacts.read_text(candidate), candidate
                except OSError:
                    continue
        return "", ""

    async def _load_run_trace(self) -> list[dict[str, Any]]:
        if self.artifacts is None or not await self.artifacts.exists("run-trace.json"):
            return []
        try:
            text = await self.artifacts.read_text("run-trace.json")
            parsed = json.loads(text)
            return parsed if isinstance(parsed, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    async def _load_source_catalog(self) -> dict[str, Any] | None:
        # In a pipeline run, source-catalog.json is auto-written by the top-level
        # harness at the end, after evaluator has run. During evaluation we use
        # the live run-scoped catalog when available.
        if self.sources is not None and len(self.sources) > 0:
            return self.sources.catalog.to_dict()
        if self.artifacts is None or not await self.artifacts.exists(SOURCE_CATALOG_ARTIFACT):
            return None
        try:
            text = await self.artifacts.read_text(SOURCE_CATALOG_ARTIFACT)
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    # ── dispatch ────────────────────────────────────────────────────────

    @staticmethod
    def _infer_generator_model(run_events: list[dict[str, Any]]) -> str | None:
        """Find the model id the generator (research/earnings) used in this run.

        We look at the `run_start` events emitted by sub-skills and prefer
        the most recent one whose agent is the generator (research / earnings).
        Failing that, we accept any agent's model. None means "we don't know;
        judge can pick freely".
        """
        for ev in reversed(run_events or []):
            if not isinstance(ev, dict) or ev.get("type") != "run_start":
                continue
            data = ev.get("data") or {}
            model = data.get("model")
            if isinstance(model, str) and model:
                return model
        return None

    @staticmethod
    async def _invoke_verifier(
        name: str,
        args: dict[str, Any],
        *,
        draft_text: str,
        run_events: list[dict[str, Any]],
        source_catalog: dict[str, Any] | None = None,
        avoid_model: str | None = None,
    ) -> tuple[bool, str] | tuple[bool, str, Any]:
        """Dispatch a single verifier. Always async, never raises.

        ``llm_judge_score`` returns a 3-tuple ``(passed, notes, JudgeScore)``;
        other verifiers return ``(passed, notes)``. Caller handles both.
        """
        fn = VERIFIERS.get(name)
        if fn is None:
            return False, f"unknown verifier: {name!r}"
        try:
            if name == "regex_in_text":
                return await fn(args.get("pattern", ""), draft_text)
            if name == "tool_call_in_run":
                return await fn(args.get("tool_name", ""), run_events)
            if name == "numeric_in_range":
                return await fn(
                    args.get("name", ""),
                    float(args.get("lo", 0)),
                    float(args.get("hi", 0)),
                    draft_text,
                )
            if name == "citation_ids_exist":
                return await fn(draft_text, source_catalog)
            if name == "llm_judge_score":
                return await fn(
                    args.get("rubric", ""),
                    draft_text,
                    run_events=run_events,
                    avoid_model=avoid_model,
                )
        except Exception as e:  # noqa: BLE001 — defensive; never fatal
            return False, f"verifier crashed: {e}"
        return False, f"unsupported verifier dispatch for {name!r}"
