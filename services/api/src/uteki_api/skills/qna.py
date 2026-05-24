"""Q&A skill — quickest path mock skill.

A minimal Q&A-style agent: plan, one thinking event, a short streamed answer.
Useful for smoke tests, latency baselines, and frontend examples.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

from uteki_api.agents.base import BaseAgent
from uteki_api.schemas.chat import ChatMessage
from uteki_api.schemas.events import AgentEvent


class QnaSkill(BaseAgent):
    name = "qna"

    DEFAULT_PROMPT = (
        "You are a concise Q&A assistant. Understand the question, then "
        "produce a short, direct answer."
    )
    DEFAULT_TOOLS: list[str] = []
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
        question = messages[-1].content if messages else ""

        yield AgentEvent(type="plan", data={"steps": ["理解问题", "作答"]})
        await asyncio.sleep(0.05)

        s1 = uuid.uuid4().hex[:8]
        yield AgentEvent(type="step_start", step_id=s1, data={"title": "理解问题"})
        yield AgentEvent(
            type="thinking",
            parent_id=s1,
            data={"text": f"问题要点：{question[:80]}"},
        )
        yield AgentEvent(type="step_end", step_id=s1, data={"status": "ok"})

        s2 = uuid.uuid4().hex[:8]
        yield AgentEvent(type="step_start", step_id=s2, data={"title": "作答"})
        parts = [
            f"**问**：{question}\n\n",
            "**答**：这是一个简洁的 Q&A 演示回复。",
            "若需更深入分析，可切换到 research 或 screener 技能。",
        ]
        for p in parts:
            yield AgentEvent(type="delta", parent_id=s2, data={"text": p})
            await asyncio.sleep(0.04)
        yield AgentEvent(type="step_end", step_id=s2, data={"status": "ok"})

        yield AgentEvent(type="usage", data={"input_tokens": 40, "output_tokens": 90})
