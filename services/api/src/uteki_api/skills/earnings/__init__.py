"""Earnings skill — post-earnings review.

Workflow (per upstream earnings-reviewer): read the call + filing, update
the model, draft a post-earnings note, surface for review. M2 ships the
non-Excel portion of that workflow — the model-update / xlsx-author /
audit-xls sub-skills are deferred until uteki ships Excel tools.

Until the LLM tool-use loop lands (M3), the user is expected to paste the
transcript text directly into the chat. The system prompt instructs the
model to ask for the transcript if it's missing rather than hallucinate.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

from uteki_api.agents.base import BaseAgent
from uteki_api.core.config import settings
from uteki_api.llm.router import default_router
from uteki_api.llm.usage import ToolCallFulfilled, ToolCallRequested, UsageDelta
from uteki_api.schemas.chat import ChatMessage
from uteki_api.schemas.events import AgentEvent
from uteki_api.skills.loader import compute_signature, load_skill_prompt
from uteki_api.tools import default_registry


class EarningsSkill(BaseAgent):
    name = "earnings"

    DEFAULT_TOOLS = ["financials", "report_analysis", "web_extract"]
    DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"

    def __init__(self, model: str | None = None) -> None:
        self.model = model
        self.system_prompt, self.refs = load_skill_prompt("earnings")

    def current_signature(self) -> dict[str, Any]:
        return {
            "prompt": compute_signature(self.system_prompt),
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

        sid = uuid.uuid4().hex[:8]
        yield AgentEvent(type="step_start", step_id=sid, data={"title": "起草财报点评"})

        # Buffer the final draft for artifact persistence (M5).
        collected: list[str] = []

        try:
            payload = [
                ChatMessage(role="system", content=self.system_prompt),
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

        # Persist the earnings note draft as an artifact. Same shape as
        # research's final-research.md so the frontend / pipelines treat
        # them uniformly.
        final_text = "".join(collected).strip()
        if self.artifacts is not None and final_text:
            art = await self.artifacts.write(
                name="final-earnings.md",
                content=final_text,
                kind="markdown",
                description="Final earnings note draft",
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

    async def _mock_run(self, messages: list[ChatMessage]) -> AsyncIterator[AgentEvent]:
        last = messages[-1].content if messages else ""

        yield AgentEvent(
            type="plan",
            data={
                "steps": [
                    "Pull the print（actuals / consensus / 10-Q / 8-K）",
                    "Read the call（指引 / 语气 / 避而不答的问题）",
                    "Variance table（实际 vs consensus vs prior）",
                    "Draft note（headline read + 驱动因素 + 估值更新）",
                    "Surface for review（标 draft）",
                ]
            },
        )
        await asyncio.sleep(0.1)

        s1 = uuid.uuid4().hex[:8]
        yield AgentEvent(type="step_start", step_id=s1, data={"title": "Synthesize draft"})

        if "transcript" not in last.lower() and "电话会" not in last:
            for part in [
                "## 需要电话会原文\n\n",
                "我已加载 earnings-reviewer 提示词，但你没附 transcript / 财务实际值。",
                "M2 阶段需要你直接把以下任一项粘贴到 prompt：\n",
                "- 电话会逐字稿（管理层发言 + Q&A）\n",
                "- 季度财务数据（收入 / 毛利率 / EBITDA / EPS，含 consensus 对比）\n\n",
                "M3 接通 `report_analysis` / `financials` 工具后会自动抓取。",
            ]:
                yield AgentEvent(type="delta", parent_id=s1, data={"text": part})
                await asyncio.sleep(0.04)
        else:
            for part in [
                "## Headline read [UNSOURCED]\n",
                "（mock：未触发真 LLM）\n\n",
                "## Variance table\n\n",
                "| 指标 | actual | consensus | delta |\n",
                "|---|---|---|---|\n",
                "| Revenue | [UNSOURCED] | [UNSOURCED] | — |\n",
                "| Gross margin | [UNSOURCED] | [UNSOURCED] | — |\n",
                "| EPS | [UNSOURCED] | [UNSOURCED] | — |\n\n",
                "## Key drivers vs thesis [UNSOURCED]\n",
                "## Guidance [UNSOURCED]\n",
                "## Estimate changes [UNSOURCED]\n",
                "## Risks [UNSOURCED]\n\n",
                "> ⚠️ Draft only · 不可外发 · 待资深分析师 mark up\n",
            ]:
                yield AgentEvent(type="delta", parent_id=s1, data={"text": part})
                await asyncio.sleep(0.04)

        yield AgentEvent(type="step_end", step_id=s1, data={"status": "ok"})
        yield AgentEvent(type="usage", data={"input_tokens": 5000, "output_tokens": 300})
