"""Research skill — sector / thematic investment research.

System prompt is composed at import time by `skills/loader.py` from:
- _shared/guardrails.md
- research/SKILL.md            (forked from anthropics/financial-services)
- research/references/*.md     (forked sub-skills)
- _shared/addendum_zh.md

The real LLM path streams a single completion. The mock path remains for
local demo without API keys. The full tool-use loop landed in M3.

M6: when invoked under the ResearchPipeline, the artifacts facade may already
contain a ``sprint-contract.json`` written by the Planner. If so, the
acceptance criteria are concatenated into the system prompt so the LLM treats
them as hard requirements; downstream Evaluator then grades against the same
contract.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from uteki_api.agents.base import BaseAgent
from uteki_api.core.config import settings
from uteki_api.llm.router import default_router
from uteki_api.llm.usage import ToolCallFulfilled, ToolCallRequested, UsageDelta
from uteki_api.schemas.chat import ChatMessage
from uteki_api.schemas.events import AgentEvent
from uteki_api.skills.loader import load_skill_prompt
from uteki_api.tools import default_registry


class ResearchAgent(BaseAgent):
    name = "research"

    DEFAULT_TOOLS = [
        "market_quote",
        "kline",
        "financials",
        "news_search",
        "report_analysis",
        "macro_fred",
        "macro_rates",
        "company_intel",
        "sec_fundamentals",
    ]
    DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"

    def __init__(self, model: str | None = None) -> None:
        self.model = model
        self.system_prompt, self.refs = load_skill_prompt("research")
        tools_prefix = self.tools_allowlist_prefix(self.DEFAULT_TOOLS)
        if tools_prefix:
            self.system_prompt = f"{tools_prefix}\n\n---\n\n{self.system_prompt}"

    def current_signature(self) -> dict[str, Any]:
        return {
            # Full text so any markdown edit auto-bumps the evolution version
            # AND the version-history UI can render the prompt verbatim.
            "prompt": self.system_prompt,
            "tool_names": list(self.DEFAULT_TOOLS),
            "model": self.model or self.DEFAULT_MODEL,
            "params": {"references": list(self.refs)},
        }

    async def run(self, messages: list[ChatMessage]) -> AsyncIterator[AgentEvent]:
        llm = default_router.resolve(self.model)
        if settings.use_mock_llm or not llm.configured:
            async for ev in self._mock_run(messages):
                yield ev
            return

        # Real path: LLM + tool-use loop. The harness injected
        # self._tool_executor before run(); fall back to the plain stream if
        # for any reason it didn't (defensive — keeps demo runnable).
        sid = uuid.uuid4().hex[:8]
        yield AgentEvent(type="step_start", step_id=sid, data={"title": "LLM + 工具循环"})

        # Collect the final assistant text so we can persist it as an
        # artifact after the stream completes (M5).
        collected: list[str] = []

        try:
            # M6: if a sprint contract exists in this run's artifact bucket,
            # inject the acceptance criteria as a hard-requirements block
            # appended to the system prompt. Pipeline runs use this; standalone
            # research runs (no Planner upstream) skip it transparently.
            system_text = self.system_prompt
            criteria_text = await self._load_contract_criteria()
            if criteria_text:
                system_text = system_text + "\n\n" + criteria_text

            payload = [
                ChatMessage(role="system", content=system_text),
                *messages,
            ]
            tools_spec = default_registry.openai_specs()
            if self._tool_executor is not None and tools_spec:
                stream = llm.stream_chat_with_tools(payload, tools_spec, self._tool_executor)
            else:
                stream = llm.stream_chat(payload)

            async for chunk in stream:
                if isinstance(chunk, ToolCallRequested):
                    yield AgentEvent(
                        type="tool_call",
                        step_id=chunk.call_id,
                        data={
                            "name": chunk.name,
                            "args": chunk.arguments,
                            # harness sees this and skips its own dispatch;
                            # we already executed via _tool_executor.
                            "_already_executed": True,
                        },
                    )
                elif isinstance(chunk, ToolCallFulfilled):
                    yield AgentEvent(
                        type="tool_result",
                        step_id=chunk.call_id,
                        data={
                            "name": chunk.name,
                            "ok": chunk.ok,
                            "summary": chunk.summary,
                            "preview": chunk.preview,
                            "error": chunk.error,
                        },
                    )
                elif isinstance(chunk, UsageDelta):
                    yield AgentEvent(
                        type="usage",
                        data={
                            "input_tokens": chunk.input_tokens,
                            "output_tokens": chunk.output_tokens,
                            "cache_read_tokens": chunk.cache_read_tokens,
                            "cache_creation_tokens": chunk.cache_creation_tokens,
                        },
                    )
                else:
                    collected.append(chunk)
                    yield AgentEvent(type="delta", data={"text": chunk})
        finally:
            yield AgentEvent(type="step_end", step_id=sid, data={"status": "ok"})

        # Persist the final synthesized text as an artifact so downstream
        # skills (M6 evaluator / pipeline) can read it and the frontend can
        # display / download it. Only on real LLM path (mock path skips).
        final_text = "".join(collected).strip()
        if self.artifacts is not None and final_text:
            art = await self.artifacts.write(
                name="final-research.md",
                content=final_text,
                kind="markdown",
                description="Final synthesized research output",
                role="draft",
                display_name="Research draft",
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

    async def _load_contract_criteria(self) -> str:
        """Return a formatted acceptance-criteria block, or empty string.

        Looked up under the run's artifact bucket; safe in non-pipeline runs.
        """
        if self.artifacts is None:
            return ""
        try:
            if not await self.artifacts.exists("sprint-contract.json"):
                return ""
            raw = await self.artifacts.read_text("sprint-contract.json")
            contract = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            return ""
        if not isinstance(contract, dict):
            return ""
        criteria = contract.get("acceptance_criteria") or []
        if not isinstance(criteria, list) or not criteria:
            return ""
        lines = ["## 本次研究的验收标准（必须全部满足）"]
        for c in criteria:
            if not isinstance(c, dict):
                continue
            cid = c.get("id") or "?"
            must = c.get("must") or ""
            lines.append(f"- **{cid}** · {must}")
        scope = contract.get("scope")
        if isinstance(scope, list) and scope:
            lines.append("")
            lines.append("## 必须覆盖的维度")
            for s in scope:
                lines.append(f"- {s}")
        return "\n".join(lines)

    async def _mock_run(self, messages: list[ChatMessage]) -> AsyncIterator[AgentEvent]:
        question = messages[-1].content if messages else ""

        yield AgentEvent(
            type="plan",
            data={
                "steps": [
                    "Scope the ask（识别行业 / 主题 / 角度）",
                    "Sector overview（市场规模、增长、价值链）",
                    "Competitive landscape（玩家、份额、近期动作）",
                    "Peer comps（多空可比 + 异常值）",
                    "Ideas shortlist（3-5 个表达此主题的标的）",
                ]
            },
        )
        await asyncio.sleep(0.1)

        s1 = uuid.uuid4().hex[:8]
        yield AgentEvent(type="step_start", step_id=s1, data={"title": "Scope the ask"})
        yield AgentEvent(
            type="thinking",
            parent_id=s1,
            data={"text": f"已加载 market-researcher SKILL.md + 4 个子技能；问题：{question}"},
        )
        yield AgentEvent(type="step_end", step_id=s1, data={"status": "ok"})

        s2 = uuid.uuid4().hex[:8]
        yield AgentEvent(type="step_start", step_id=s2, data={"title": "Synthesize"})
        for part in [
            "## Scope\n",
            f"针对「{question}」，按 market-researcher 工作流给出研究框架草稿。\n\n",
            "## Sector overview [UNSOURCED]\n规模 / 增速 / 价值链 / why-now —— 需 `financials` 工具补数。\n\n",
            "## Competitive landscape [UNSOURCED]\n8-15 个玩家、份额、定位、最近动作。\n\n",
            "## Peer comps [UNSOURCED]\n可比公司 PE / EV-EBITDA / 增速；离群值需复核。\n\n",
            "## Ideas shortlist [UNSOURCED]\n3-5 个标的及一句话论点。\n\n",
            "> ⚠️ 当前是 mock 占位输出，且 LLM 工具循环尚未接入（M3）。",
            "配置 `DEEPSEEK_API_KEY` / `AIHUBMIX_API_KEY` 并 `UTEKI_USE_MOCK_LLM=false` 即可跑真模型。",
        ]:
            yield AgentEvent(type="delta", parent_id=s2, data={"text": part})
            await asyncio.sleep(0.04)
        yield AgentEvent(type="step_end", step_id=s2, data={"status": "ok"})

        yield AgentEvent(type="usage", data={"input_tokens": 14000, "output_tokens": 500})
