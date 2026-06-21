"""uteki — the main agent / intent router (Phase B.1).

Sits in front of all the leaf skills + pipelines. Takes a user's one-liner,
decides which sub-skill is the right tool for the job, and either answers
inline (simple Q&A) or delegates to that sub-skill — running it through
the same harness contract so all the M1.x infrastructure (budget, source
catalog, artifact facade, self-evolution proposals) still applies.

Two modes:

1. ``intent="direct"`` — simple Q&A. The router itself runs an LLM
   tool-use loop with the platform tools (market_quote, news_search,
   web_search). No sub-skill spawned.
2. ``intent in {research, company, earnings, research_pipeline}`` —
   wraps the user's message in a ``subagent_start`` event, runs the
   matching registered sub-skill, then ``subagent_end``. Same shape
   research_pipeline uses to call planner/research/evaluator.

Mock-llm mode: simple keyword classifier instead of an LLM call.
Real-llm mode: a strict-JSON classification LLM call first, then the
chosen path.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

from uteki_api.agents.base import BaseAgent
from uteki_api.agents.harness import HarnessLimits
from uteki_api.core.config import settings
from uteki_api.llm.router import default_router
from uteki_api.llm.usage import ToolCallFulfilled, ToolCallRequested, UsageDelta
from uteki_api.schemas.chat import ChatMessage
from uteki_api.schemas.events import AgentEvent
from uteki_api.skills.loader import load_skill_prompt
from uteki_api.tools import default_registry

Intent = Literal[
    "direct",
    "research",
    "company",
    "earnings",
    "research_pipeline",
]

# Sub-skill names registered in default_skills. Kept as a constant so
# tests + ops can read which sub-skills the router knows about.
SUBSKILL_MAP: dict[str, str] = {
    "research": "research",
    "company": "company_research_pipeline",
    "earnings": "earnings",
    "research_pipeline": "research_pipeline",
}


class UtekiRouter(BaseAgent):
    """The main agent. Reads user intent, dispatches to a leaf skill or
    answers inline."""

    name = "uteki"

    # The router itself may call light tools when answering directly. It
    # never invokes data-heavy / multi-step tools; those belong to the
    # sub-skills it delegates to.
    DEFAULT_TOOLS = ["market_quote", "news_search", "web_search"]
    DEFAULT_MODEL = "deepseek/deepseek-chat"

    def __init__(self, model: str | None = None) -> None:
        self.model = model
        self.system_prompt, self.refs = load_skill_prompt("uteki")
        tools_prefix = self.tools_allowlist_prefix(self.DEFAULT_TOOLS)
        if tools_prefix:
            self.system_prompt = f"{tools_prefix}\n\n---\n\n{self.system_prompt}"

    def recommended_limits(self) -> HarnessLimits:
        # Generous limits: the router itself is cheap, but a delegated
        # sub-skill (especially company_research_pipeline) can spend
        # ~$0.30 + 600s. Inherit the company pipeline shape.
        return HarnessLimits(
            max_steps=40,
            max_tool_calls=25,
            wall_time_seconds=600.0,
            max_input_tokens=500_000,
            max_output_tokens=40_000,
            max_cost_usd=1.0,
        )

    def current_signature(self) -> dict[str, Any]:
        return {
            # Full composed SKILL.md text — any edit auto-bumps version
            # AND the version-history UI can render it verbatim.
            "prompt": self.system_prompt,
            "tool_names": list(self.DEFAULT_TOOLS),
            "model": self.model or self.DEFAULT_MODEL,
            "params": {"subskills": sorted(SUBSKILL_MAP.values())},
        }

    # ── Entry point ────────────────────────────────────────────────────

    async def run(
        self, messages: list[ChatMessage]
    ) -> AsyncIterator[AgentEvent]:
        user_text = self._latest_user(messages)

        # ── Step 1: classify intent ───────────────────────────────────
        decision = await self._classify(user_text)
        intent: Intent = decision["intent"]
        reasoning: str = decision.get("reasoning", "")

        yield AgentEvent(
            type="plan",
            data={
                "steps": [
                    f"识别意图：{intent}",
                    (
                        f"分派到 sub-skill {SUBSKILL_MAP[intent]!r}"
                        if intent in SUBSKILL_MAP
                        else "直接回答（不分派）"
                    ),
                ],
                "intent": intent,
                "reasoning": reasoning,
            },
        )

        # ── Step 2: dispatch ──────────────────────────────────────────
        if intent == "direct":
            async for ev in self._answer_directly(messages):
                yield ev
            return

        subskill_name = SUBSKILL_MAP[intent]
        async for ev in self._delegate(subskill_name, messages):
            yield ev

    # ── Classification ─────────────────────────────────────────────────

    async def _classify(self, user_text: str) -> dict[str, Any]:
        """Decide which intent bucket the user message falls in.

        Mock-mode / unconfigured: keyword heuristic on ticker patterns +
        Chinese sector / earnings cues. Real-mode: a single strict-JSON
        LLM call. The keyword path also serves as a fallback when the
        LLM returns malformed JSON.
        """
        heuristic = self._heuristic_classify(user_text)
        llm = default_router.resolve(self.model)
        if settings.use_mock_llm or not llm.configured:
            return heuristic

        prompt = self._classify_prompt(user_text)
        chunks: list[str] = []
        async for chunk in llm.stream_chat(
            [ChatMessage(role="user", content=prompt)]
        ):
            if isinstance(chunk, UsageDelta):
                continue
            chunks.append(chunk)
        raw = "".join(chunks).strip()
        parsed = self._parse_classify_json(raw)
        return parsed or heuristic

    def _classify_prompt(self, user_text: str) -> str:
        return f"""你是 uteki 的意图分类器。读用户消息，决定该把它路由到哪个 sub-skill。

【intent 定义】
- "direct"             用户问的是概念 / 行情快查 / 闲聊。在 router 里直接回。
- "research"           行业 / 主题 / 板块研究，或多 ticker 对比。**默认的"研究"档**。
- "company"            消息里**有且仅有一个**美股 ticker，且明显要做投资判断 / 估值 / 怎么看。
- "earnings"           消息里**已经包含**电话会 transcript 或具体财务数字（Revenue / 毛利 / 净利等），要点评季度业绩。
- "research_pipeline"  用户**明确**说要"完整 pipeline"、"高质量"、"反复迭代"。比 research 重，要谨慎。

【关键消歧规则】
1. 单 ticker + 投研动词 → company（不要再 fallback 到 research）
2. 两个或更多 ticker（不论有没有"对比"） → research，不是 company
3. earnings **必须**消息里已经有 transcript / 财务数字；只是"AAPL 财报怎么看"还没粘数据 → company
4. research_pipeline 是 research 的"高规格版"。**用户没明确点名 pipeline / 高质量 / 迭代 就不要选它**——它贵。
5. 概念题（"什么是 X"）、市场快查（"今天大盘"）、闲聊 → direct

【few-shot 示例】
- "什么是 PE-TTM？" → {{"intent":"direct","reasoning":"概念题"}}
- "上证今天怎么样" → {{"intent":"direct","reasoning":"行情快查"}}
- "分析 NVDA" → {{"intent":"company","reasoning":"单 ticker + 投研动词"}}
- "TSLA 怎么看" → {{"intent":"company","reasoning":"单 ticker + 怎么看"}}
- "对比 NVDA 和 AMD" → {{"intent":"research","reasoning":"两个 ticker，多公司对比走 research"}}
- "半导体设备板块研究框架" → {{"intent":"research","reasoning":"板块主题"}}
- "我想要一份完整 pipeline 的板块研报" → {{"intent":"research_pipeline","reasoning":"明确点名 pipeline"}}
- "NVDA Q3：Revenue $35.1B，毛利 75%，点评一下" → {{"intent":"earnings","reasoning":"消息里有具体财务数字"}}
- "AAPL 财报怎么看" → {{"intent":"company","reasoning":"没粘 transcript，先走公司深研"}}

【用户消息】
{user_text}

【严格输出规则】
1. 只输出一个合法 JSON，禁止 markdown / 代码块 / 解释
2. 以 {{ 开始，以 }} 结束，无前导空白

【JSON 结构】
{{"intent": "direct|research|company|earnings|research_pipeline", "reasoning": "1-2 句为什么选这个"}}
"""

    def _parse_classify_json(self, raw: str) -> dict[str, Any] | None:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        first = text.find("{")
        last = text.rfind("}")
        if first < 0 or last <= first:
            return None
        try:
            obj = json.loads(text[first : last + 1])
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict):
            return None
        intent = obj.get("intent")
        if intent not in {"direct", "research", "company", "earnings", "research_pipeline"}:
            return None
        return {"intent": intent, "reasoning": str(obj.get("reasoning") or "")}

    # Common English/financial acronyms that look like tickers but aren't.
    _BAD_TICKERS = frozenset({
        "PE", "PB", "PS", "ROE", "ROA", "FCF", "TAM", "SAM", "AI", "AR", "VR",
        "EV", "ETF", "IPO", "GAAP", "EPS", "PEG", "PEGY", "DCF", "WACC",
        "EBIT", "EBITDA", "CAGR", "YOY", "QOQ", "CFO", "CEO", "COO", "CTO",
        "USD", "CNY", "EUR", "GBP", "OK", "FAQ",
    })

    @staticmethod
    def _extract_tickers(text: str) -> list[str]:
        """Pull 2-5 letter all-caps tokens, filtering common acronyms."""
        candidates = re.findall(r"\b[A-Z]{2,5}\b", text)
        return [t for t in candidates if t not in UtekiRouter._BAD_TICKERS]

    @staticmethod
    def _heuristic_classify(user_text: str) -> dict[str, Any]:
        """Keyword + regex heuristic. Used in mock-mode and as a parse-
        failure fallback in real-mode.

        Priority order:
        1. earnings — pasted transcript or specific financial numbers
        2. research_pipeline — explicit ask for high quality / iteration
        3. company — exactly one US ticker + investor-research verb
        4. research — multi-ticker comparison OR sector / theme cues
        5. direct — concept question / market quick-check / no signal
        """
        text = user_text.strip()
        lower = text.lower()
        real_tickers = UtekiRouter._extract_tickers(text)

        # 1. earnings — must have BOTH a report keyword AND concrete signal
        #    (either real length suggesting a transcript paste, OR specific
        #    financial-number keywords). A bare "AAPL 财报怎么看" — no
        #    pasted data — should fall through to company, not earnings.
        earnings_kw = any(
            kw in text for kw in ("电话会", "earnings call", "transcript", "财报电话会")
        ) or ("财报" in text and any(kw in text for kw in ("Revenue", "毛利", "净利", "营收", "EPS", "$")))
        if earnings_kw and (
            len(text) > 150 or any(kw in text for kw in ("Revenue", "毛利率", "净利率", "$"))
        ):
            return {
                "intent": "earnings",
                "reasoning": "消息包含财报关键词 + 具体财务数字，疑似已粘 transcript",
            }

        # 2. research_pipeline — explicit ask for "pipeline" / "high quality" / iteration
        pipeline_signals = (
            "research_pipeline", "research pipeline", "完整 pipeline",
            "完整的 pipeline", "完整 planner",
        )
        quality_signals = ("高质量研报", "反复迭代", "iterate", "严谨的研究", "深入研究 pipeline")
        if any(kw in lower for kw in pipeline_signals) or any(
            kw in text for kw in quality_signals
        ):
            return {
                "intent": "research_pipeline",
                "reasoning": "用户明确点名完整 pipeline / 高质量 / 反复迭代",
            }

        # 3. company — exactly one US ticker + investor-research verb.
        #    Multiple tickers fall through to step 4 (research).
        verbs = (
            "分析", "估值", "投资", "怎么看", "评估", "深研", "深度", "看法",
            "research", "review", "valuation",
        )
        if len(real_tickers) == 1 and any(kw in text for kw in verbs):
            return {
                "intent": "company",
                "reasoning": f"消息含单一 ticker {real_tickers[0]} 和投研动词",
            }

        # 4. research — multi-ticker comparison OR sector / industry / theme cues
        compare_signals = ("对比", "比较", "vs ", " vs", "compare", "差异")
        sector_signals = ("板块", "行业", "赛道", "主题", "sector", "industry", "theme")
        if len(real_tickers) >= 2 or any(kw in text for kw in compare_signals + sector_signals):
            if len(real_tickers) >= 2:
                reasoning = f"消息含多个 ticker ({', '.join(real_tickers[:3])})，多公司对比走 research"
            else:
                reasoning = "消息涉及板块 / 行业 / 主题"
            return {"intent": "research", "reasoning": reasoning}

        # 5. direct — concept question / market quick-check / no signal
        return {
            "intent": "direct",
            "reasoning": "消息简短或无明显研究信号，直接回答",
        }

    # ── Direct-answer path ────────────────────────────────────────────

    async def _answer_directly(
        self, messages: list[ChatMessage]
    ) -> AsyncIterator[AgentEvent]:
        """Run an LLM tool-use loop in-place. Same shape as ResearchAgent's
        real path but without the artifact persistence — router answers
        are conversational, not deliverables."""
        llm = default_router.resolve(self.model)
        sid = uuid.uuid4().hex[:8]
        yield AgentEvent(
            type="step_start", step_id=sid, data={"title": "直接回答"}
        )

        if settings.use_mock_llm or not llm.configured:
            mock_text = (
                f"[mock] router 直接回答：{messages[-1].content[:80]}。"
                "真模式将调用 LLM + 必要工具给出答复。"
            )
            yield AgentEvent(type="delta", data={"text": mock_text})
            yield AgentEvent(type="step_end", step_id=sid, data={"status": "ok"})
            return

        try:
            payload = [
                ChatMessage(role="system", content=self.system_prompt or ""),
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
                    yield AgentEvent(type="delta", data={"text": chunk})
        finally:
            yield AgentEvent(type="step_end", step_id=sid, data={"status": "ok"})

    # ── Sub-skill delegation ──────────────────────────────────────────

    async def _delegate(
        self, skill_name: str, messages: list[ChatMessage]
    ) -> AsyncIterator[AgentEvent]:
        """Spawn a registered sub-skill, sharing run-scoped state (tool
        executor, artifact facade, source catalog) so the harness sees
        one unified run.

        Mirrors ResearchPipeline._delegate. Wraps the sub-skill events
        in subagent_start / subagent_end so the trace renders the
        hierarchy cleanly.
        """
        from uteki_api.skills import default_skills  # local import to dodge cycle

        meta: dict[str, Any] = {"name": skill_name}
        yield AgentEvent(
            type="subagent_start",
            step_id=uuid.uuid4().hex[:8],
            data=meta,
        )

        try:
            # create() not get() — see SkillRegistry.create docstring; the
            # singleton would race per-run artifacts under concurrent uteki
            # router invocations.
            sub = default_skills.create(skill_name)
        except KeyError:
            yield AgentEvent(
                type="error",
                data={"reason": f"router: unknown sub-skill {skill_name!r}"},
            )
            yield AgentEvent(type="subagent_end", data=meta)
            return

        # Share run-scoped injectables (same as pipeline pattern).
        sub._tool_executor = self._tool_executor
        sub.artifacts = self.artifacts
        sub.sources = self.sources

        try:
            async for ev in sub.run(messages):
                yield ev
        except Exception as e:  # noqa: BLE001 — surface, never re-raise
            yield AgentEvent(
                type="error",
                data={"reason": f"router: sub-skill {skill_name!r} crashed: {e}"},
            )

        yield AgentEvent(type="subagent_end", data=meta)

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _latest_user(messages: list[ChatMessage]) -> str:
        for m in reversed(messages):
            if m.role == "user":
                return m.content or ""
        return ""
