"""Recap skill — daily/weekly portfolio recap (mock).

Emits a fixed plan and synthesises a short Chinese summary of a fictional
trading day. Used to demo multi-skill UX without LLM credentials.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

from uteki_api.agents.base import BaseAgent
from uteki_api.schemas.chat import ChatMessage
from uteki_api.schemas.events import AgentEvent


class RecapSkill(BaseAgent):
    name = "recap"

    DEFAULT_PROMPT = (
        "You are a portfolio recap assistant. Review the market, the user's "
        "positions, and produce a concise end-of-day digest in Chinese."
    )
    DEFAULT_TOOLS = ["market_quote", "news_search"]
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
            data={"steps": ["回顾大盘", "盘点持仓", "总结亮点"]},
        )
        await asyncio.sleep(0.1)

        s1 = uuid.uuid4().hex[:8]
        yield AgentEvent(type="step_start", step_id=s1, data={"title": "回顾大盘"})
        yield AgentEvent(
            type="thinking",
            parent_id=s1,
            data={"text": "沪指 +0.42%，深成指 +0.81%，创业板 +1.05%。两市成交 9800 亿。"},
        )
        yield AgentEvent(type="step_end", step_id=s1, data={"status": "ok"})

        s2 = uuid.uuid4().hex[:8]
        yield AgentEvent(type="step_start", step_id=s2, data={"title": "盘点持仓"})
        yield AgentEvent(
            type="thinking",
            parent_id=s2,
            data={"text": "新能源 +1.6%，半导体 +0.9%，消费 -0.3%。"},
        )
        yield AgentEvent(type="step_end", step_id=s2, data={"status": "ok"})

        s3 = uuid.uuid4().hex[:8]
        yield AgentEvent(type="step_start", step_id=s3, data={"title": "总结亮点"})
        parts = [
            "**今日复盘**\n\n",
            "- 大盘整体偏强，量能温和放大。\n",
            "- 新能源板块领涨，宁德时代领涨权重。\n",
            "- 消费板块承压，建议关注估值切换窗口。\n\n",
            "（mock 输出，仅用于演示。）",
        ]
        for p in parts:
            yield AgentEvent(type="delta", parent_id=s3, data={"text": p})
            await asyncio.sleep(0.05)
        yield AgentEvent(type="step_end", step_id=s3, data={"status": "ok"})

        yield AgentEvent(type="usage", data={"input_tokens": 80, "output_tokens": 220})
