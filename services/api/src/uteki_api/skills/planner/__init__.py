"""Planner skill — expands a 1-2 sentence user intent into a research spec.

Why: per Anthropic's "Generator does not judge itself" principle, an explicit
Planner role produces a machine-checkable acceptance contract that a separate
Evaluator can grade the Generator's draft against. The Planner itself calls
no tools — pure LLM expansion.

Outputs (artifacts):
  - plan.md              human-readable spec
  - sprint-contract.json acceptance criteria + verifier metadata
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

from uteki_api.agents.base import BaseAgent
from uteki_api.core.config import settings
from uteki_api.llm.router import default_router
from uteki_api.llm.usage import UsageDelta
from uteki_api.schemas.chat import ChatMessage
from uteki_api.schemas.events import AgentEvent
from uteki_api.skills.loader import compute_signature, load_skill_prompt


class PlannerSkill(BaseAgent):
    name = "planner"

    DEFAULT_TOOLS: list[str] = []
    # DeepSeek chat — cheap and plenty capable for spec expansion.
    DEFAULT_MODEL = "deepseek/deepseek-chat"

    def __init__(self, model: str | None = None) -> None:
        self.model = model
        self.system_prompt, self.refs = load_skill_prompt("planner")

    def current_signature(self) -> dict[str, Any]:
        return {
            "prompt": compute_signature(self.system_prompt),
            "tool_names": list(self.DEFAULT_TOOLS),
            "model": self.model or self.DEFAULT_MODEL,
            "params": {"references": list(self.refs)},
        }

    async def run(self, messages: list[ChatMessage]) -> AsyncIterator[AgentEvent]:
        # 1. Plan event — what this skill is about to do.
        yield AgentEvent(
            type="plan",
            data={
                "steps": [
                    "拆解需求（intent → scope dimensions）",
                    "起草人类可读的 plan.md",
                    "起草 machine-readable sprint-contract.json",
                    "写两份 artifact 并 yield artifact_written",
                ]
            },
        )

        sid = uuid.uuid4().hex[:8]
        yield AgentEvent(type="step_start", step_id=sid, data={"title": "拆解需求"})

        # 2. Run the LLM (text-only; planner does not call tools).
        llm = default_router.resolve(self.model)
        if settings.use_mock_llm or not llm.configured:
            plan_md, contract_json = self._mock_plan(messages)
        else:
            plan_md, contract_json = await self._llm_plan(llm, messages)

        yield AgentEvent(type="step_end", step_id=sid, data={"status": "ok"})

        # 3. Persist artifacts. We always write something — if parsing failed
        #    upstream, `_safe_contract` returned a default contract so the
        #    pipeline can still progress.
        if self.artifacts is None:
            return

        plan_art = await self.artifacts.write(
            name="plan.md",
            content=plan_md,
            kind="markdown",
            description="Human-readable research spec",
        )
        yield AgentEvent(
            type="artifact_written",
            data={
                "name": plan_art.name,
                "kind": plan_art.kind,
                "size_bytes": plan_art.size_bytes,
                "written_by": plan_art.written_by,
                "description": plan_art.description,
                "url": f"/api/runs/{plan_art.run_id}/artifacts/{plan_art.name}",
            },
        )

        contract_art = await self.artifacts.write(
            name="sprint-contract.json",
            content=json.dumps(contract_json, ensure_ascii=False, indent=2),
            kind="json",
            description="Machine-readable acceptance criteria",
        )
        yield AgentEvent(
            type="artifact_written",
            data={
                "name": contract_art.name,
                "kind": contract_art.kind,
                "size_bytes": contract_art.size_bytes,
                "written_by": contract_art.written_by,
                "description": contract_art.description,
                "url": f"/api/runs/{contract_art.run_id}/artifacts/{contract_art.name}",
            },
        )

    # ── LLM path ────────────────────────────────────────────────────────

    async def _llm_plan(
        self,
        llm: Any,
        messages: list[ChatMessage],
    ) -> tuple[str, dict[str, Any]]:
        """Call the LLM once with the planner system prompt, parse plan + contract."""
        intent = self._extract_intent(messages)
        payload = [
            ChatMessage(role="system", content=self.system_prompt),
            *messages,
        ]
        collected: list[str] = []

        # Plain stream_chat is enough — no tools.
        async for chunk in llm.stream_chat(payload):
            if isinstance(chunk, UsageDelta):
                # Surface usage so harness can budget-check and persist totals.
                # We can't yield here (private coroutine); accumulate via caller.
                self._last_usage = chunk
                continue
            collected.append(chunk)

        raw = "".join(collected)
        plan_md = self._extract_plan_md(raw)
        contract = self._safe_contract(self._extract_contract_json(raw), intent=intent)
        return plan_md, contract

    # ── Mock path (used when no LLM key configured) ─────────────────────

    def _mock_plan(
        self,
        messages: list[ChatMessage],
    ) -> tuple[str, dict[str, Any]]:
        intent = self._extract_intent(messages)
        plan_md = (
            f"# Plan\n\n"
            f"**Intent**: {intent}\n\n"
            f"## Scope dimensions\n"
            f"- 市场规模与增长\n- 主要玩家与份额\n- 估值水平\n- 关键风险\n\n"
            f"## High-level steps\n"
            f"1. Confirm scope and identify 8-15 names that define the space\n"
            f"2. Sector overview (size / growth / value chain / why-now)\n"
            f"3. Competitive landscape with positioning notes\n"
            f"4. Valuation snapshot (PE / PB) for the peer set\n"
            f"5. Risks and catalysts\n\n"
            f"## Out of scope\n"
            f"- 单一标的的详细财务建模\n"
            f"- 短期股价方向预测\n"
        )
        contract = self._default_contract(intent)
        return plan_md, contract

    # ── helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _extract_intent(messages: list[ChatMessage]) -> str:
        for m in reversed(messages):
            if m.role == "user":
                return m.content.strip()
        return ""

    @staticmethod
    def _extract_plan_md(raw: str) -> str:
        """Take everything before the first ```json fence as the plan body."""
        m = re.search(r"```json", raw, flags=re.IGNORECASE)
        head = raw[: m.start()] if m else raw
        head = head.strip()
        # Guarantee a leading "# Plan" so downstream readers can recognise it.
        if not head.lower().startswith("# plan"):
            head = "# Plan\n\n" + head
        return head + "\n"

    @staticmethod
    def _extract_contract_json(raw: str) -> dict[str, Any] | None:
        """Pull the first ```json …``` fenced block and parse it."""
        m = re.search(r"```json\s*(.+?)```", raw, flags=re.IGNORECASE | re.DOTALL)
        if not m:
            # Last-ditch: try to find a standalone {...} block.
            brace = re.search(r"\{[\s\S]*\}\s*$", raw)
            candidate = brace.group(0) if brace else None
            if not candidate:
                return None
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
        try:
            parsed = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _safe_contract(
        self,
        parsed: dict[str, Any] | None,
        *,
        intent: str,
    ) -> dict[str, Any]:
        """Coerce whatever the LLM returned into a valid contract, or fall back."""
        if parsed is None:
            return self._default_contract(intent)

        scope = parsed.get("scope")
        if not isinstance(scope, list) or not scope:
            scope = ["市场规模", "竞争格局", "估值", "风险"]

        criteria = parsed.get("acceptance_criteria")
        if not isinstance(criteria, list) or not criteria:
            criteria = self._default_criteria()
        else:
            # Drop malformed entries; keep up to 8.
            cleaned: list[dict[str, Any]] = []
            for i, c in enumerate(criteria):
                if not isinstance(c, dict):
                    continue
                must = c.get("must")
                verifier = c.get("verifier")
                if not isinstance(must, str) or not isinstance(verifier, str):
                    continue
                args = c.get("args") if isinstance(c.get("args"), dict) else {}
                cleaned.append(
                    {
                        "id": str(c.get("id") or f"C{i + 1}"),
                        "must": must,
                        "verifier": verifier,
                        "args": args,
                    }
                )
            criteria = cleaned or self._default_criteria()

        max_iter = parsed.get("max_iterations")
        if not isinstance(max_iter, int) or max_iter <= 0 or max_iter > 5:
            max_iter = 3

        return {
            "intent": parsed.get("intent") or intent,
            "scope": scope,
            "acceptance_criteria": criteria,
            "max_iterations": max_iter,
        }

    @staticmethod
    def _default_criteria() -> list[dict[str, Any]]:
        return [
            {
                "id": "C1",
                "must": "至少 3 个公司名 + 对应 ticker（A 股六位.SH/.SZ 或美股 2-5 位英文代码）",
                "verifier": "regex_in_text",
                "args": {"pattern": r"(\d{6}\.(SH|SZ)|[A-Z]{2,5})"},
            },
            {
                "id": "C2",
                "must": "至少触发一次 news_search 工具调用以获取新鲜证据",
                "verifier": "tool_call_in_run",
                "args": {"tool_name": "news_search"},
            },
            {
                "id": "C3",
                "must": "估值段包含具体的 PE 或 PB 数字",
                "verifier": "regex_in_text",
                "args": {"pattern": r"PE[\s:：]|PB[\s:：]"},
            },
        ]

    def _default_contract(self, intent: str) -> dict[str, Any]:
        return {
            "intent": intent,
            "scope": ["市场规模", "竞争格局", "估值", "风险"],
            "acceptance_criteria": self._default_criteria(),
            "max_iterations": 3,
        }
