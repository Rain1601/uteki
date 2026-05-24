"""Screener skill — multi-factor stock screener (mock).

Emits a plan to pull quotes, filter, rank, and produce a top-5 list. Issues
tool calls to `kline` / `financials` which may or may not be available; the
harness tolerates unknown tool names and surfaces the error in `tool_result`.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

from uteki_api.agents.base import BaseAgent
from uteki_api.schemas.chat import ChatMessage
from uteki_api.schemas.events import AgentEvent


class ScreenerSkill(BaseAgent):
    name = "screener"

    DEFAULT_PROMPT = (
        "You are an equity screener. Pull quotes, filter on factors, rank, "
        "and emit a top-5 candidate list with brief rationale."
    )
    DEFAULT_TOOLS = ["kline", "financials"]
    DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"

    def __init__(self, model: str | None = None) -> None:
        self.model = model

    def current_signature(self) -> dict[str, Any]:
        return {
            "prompt": self.DEFAULT_PROMPT,
            "tool_names": list(self.DEFAULT_TOOLS),
            "model": self.model or self.DEFAULT_MODEL,
            "params": {},
        }

    async def run(self, messages: list[ChatMessage]) -> AsyncIterator[AgentEvent]:
        async for ev in self._mock_run(messages):
            yield ev

    async def _mock_run(self, messages: list[ChatMessage]) -> AsyncIterator[AgentEvent]:
        yield AgentEvent(
            type="plan",
            data={"steps": ["拉行情", "过滤", "排序", "输出 top 5"]},
        )
        await asyncio.sleep(0.1)

        s1 = uuid.uuid4().hex[:8]
        yield AgentEvent(type="step_start", step_id=s1, data={"title": "拉行情"})
        yield AgentEvent(
            type="tool_call",
            step_id=s1,
            data={"name": "kline", "args": {"symbol": "300750.SZ", "interval": "1d", "limit": 60}},
        )
        yield AgentEvent(type="step_end", step_id=s1, data={"status": "ok"})

        s2 = uuid.uuid4().hex[:8]
        yield AgentEvent(type="step_start", step_id=s2, data={"title": "过滤 & 拉财务"})
        yield AgentEvent(
            type="tool_call",
            step_id=s2,
            data={"name": "financials", "args": {"symbol": "300750.SZ"}},
        )
        yield AgentEvent(type="step_end", step_id=s2, data={"status": "ok"})

        s3 = uuid.uuid4().hex[:8]
        yield AgentEvent(type="step_start", step_id=s3, data={"title": "排序 & 输出"})
        parts = [
            "**Top 5 候选**\n\n",
            "1. 宁德时代（300750.SZ）— 量价齐升，ROE 稳健。\n",
            "2. 比亚迪（002594.SZ）— 海外销量超预期。\n",
            "3. 中芯国际（688981.SH）— 产能利用率回暖。\n",
            "4. 隆基绿能（601012.SH）— 估值已回落至低位。\n",
            "5. 海尔智家（600690.SH）— 高分红 + 稳定增长。\n",
        ]
        for p in parts:
            yield AgentEvent(type="delta", parent_id=s3, data={"text": p})
            await asyncio.sleep(0.04)
        yield AgentEvent(type="step_end", step_id=s3, data={"status": "ok"})

        yield AgentEvent(type="usage", data={"input_tokens": 95, "output_tokens": 260})
