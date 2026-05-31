"""Company research pipeline migrated from uteki.open's 7-gate flow."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from uteki_api.agents.base import BaseAgent
from uteki_api.agents.harness import HarnessLimits
from uteki_api.core.config import settings
from uteki_api.llm.router import default_router
from uteki_api.llm.usage import ToolCallFulfilled, UsageDelta
from uteki_api.schemas.chat import ChatMessage
from uteki_api.schemas.events import AgentEvent


@dataclass(frozen=True)
class CompanyGate:
    number: int
    name: str
    display_name: str
    focus: str


COMPANY_GATES: tuple[CompanyGate, ...] = (
    CompanyGate(1, "business_analysis", "业务解析", "靠什么赚钱、收入结构、生意质量、可持续性"),
    CompanyGate(2, "fisher_qa", "成长质量分析", "Fisher 15问、成长空间、研发、销售、管理深度"),
    CompanyGate(3, "moat_assessment", "护城河评估", "品牌、网络效应、切换成本、成本优势、规模、IP"),
    CompanyGate(4, "management_assessment", "管理层评估", "诚信、资本配置、股东导向、接班和薪酬"),
    CompanyGate(5, "reverse_test", "逆向检验", "毁灭场景、红旗、韧性和认知偏差"),
    CompanyGate(6, "valuation", "估值与时机", "PE/PB/PS、FCF yield、同行估值、安全边际"),
)


class CompanyResearchPipeline(BaseAgent):
    """Harness-native 7-gate company investment research pipeline.

    The older `uteki.open` implementation stored gate state in a company
    domain service. This version keeps the agentic shape inside a single run:
    evidence artifacts first, six gate artifacts next, then a primary
    investment memo plus a structured decision artifact.
    """

    name = "company_research_pipeline"

    DEFAULT_TOOLS = ["market_quote", "financials", "news_search"]
    DEFAULT_MODEL = "deepseek/deepseek-chat"

    def __init__(self, model: str | None = None) -> None:
        self.model = model

    def recommended_limits(self) -> HarnessLimits:
        return HarnessLimits(
            max_steps=40,
            max_tool_calls=20,
            wall_time_seconds=600.0,
            max_input_tokens=500_000,
            max_output_tokens=40_000,
            max_cost_usd=1.0,
        )

    def current_signature(self) -> dict[str, Any]:
        return {
            "prompt": "company-research-7gate-peer-capital:v2",
            "tool_names": list(self.DEFAULT_TOOLS),
            "model": self.model or self.DEFAULT_MODEL,
            "params": {
                "gates": [g.name for g in COMPANY_GATES],
                "max_peers": 3,
                "capital_plan": True,
                "real_order_execution": False,
            },
        }

    async def run(self, messages: list[ChatMessage]) -> AsyncIterator[AgentEvent]:
        question = self._latest_user_message(messages)
        symbol, peers = self._extract_symbols(question)
        reviews: list[dict[str, Any]] = []

        yield AgentEvent(
            type="plan",
            data={
                "steps": [
                    f"Collect evidence for {symbol} and peers {', '.join(peers) or 'auto-filled peers'}",
                    "Write company-profile.json, financials.json, news-brief.json",
                    "Run six migrated company gates",
                    "Build peer-comparison.json, ranking.json, capital-plan.json",
                    "Review autonomy, observability, traceability, self-iteration",
                    "Synthesize final-report.md + decision.json",
                ]
            },
        )

        evidence = await self._collect_evidence(symbol, peers)
        for event in evidence["events"]:
            yield event
        await self._write_evidence_artifacts(symbol, evidence)
        review_art = await self._record_capability_review(
            reviews,
            stage="evidence",
            artifacts=["company-profile.json", "financials.json", "news-brief.json"],
            notes=f"Collected read-only evidence for {symbol} plus {len(peers)} peers.",
            source_ids=self._source_ids(evidence),
        )
        if review_art is not None:
            yield self._artifact_event(review_art)

        gate_outputs: list[dict[str, str]] = []
        for gate in COMPANY_GATES:
            sid = uuid.uuid4().hex[:8]
            yield AgentEvent(
                type="subagent_start",
                step_id=sid,
                data={"name": gate.name, "gate": gate.number, "display_name": gate.display_name},
            )
            text = await self._run_gate(gate, symbol, question, evidence, gate_outputs)
            gate_outputs.append({"name": gate.name, "display_name": gate.display_name, "text": text})
            if self.artifacts is not None:
                art = await self.artifacts.write(
                    name=f"gate-{gate.number:02d}-{gate.name}.md",
                    content=text,
                    kind="markdown",
                    description=f"Company research gate {gate.number}: {gate.display_name}",
                    role="draft",
                    display_name=f"Gate {gate.number}: {gate.display_name}",
                    source_refs=self._source_ids(evidence),
                )
                yield self._artifact_event(art)
            review_art = await self._record_capability_review(
                reviews,
                stage=gate.name,
                artifacts=[f"gate-{gate.number:02d}-{gate.name}.md"],
                notes=f"Completed target-company gate: {gate.display_name}.",
                source_ids=self._source_ids(evidence),
            )
            if review_art is not None:
                yield self._artifact_event(review_art)
            yield AgentEvent(
                type="subagent_end",
                data={"name": gate.name, "gate": gate.number, "display_name": gate.display_name},
            )

        peer_comparison = self._build_peer_comparison(symbol, peers, evidence, gate_outputs)
        ranking = self._build_ranking(peer_comparison)
        if self.artifacts is not None:
            peer_art = await self.artifacts.write(
                name="peer-comparison.json",
                content=json.dumps(peer_comparison, ensure_ascii=False, indent=2, default=str),
                kind="json",
                description="Target and peer company comparison",
                role="evaluation",
                display_name="Peer comparison",
                source_refs=self._source_ids(evidence),
            )
            yield self._artifact_event(peer_art)
            ranking_art = await self.artifacts.write(
                name="ranking.json",
                content=json.dumps(ranking, ensure_ascii=False, indent=2, default=str),
                kind="json",
                description="Ranked investment candidates",
                role="evaluation",
                display_name="Company ranking",
                source_refs=self._source_ids(evidence),
            )
            yield self._artifact_event(ranking_art)
        review_art = await self._record_capability_review(
            reviews,
            stage="peer_comparison",
            artifacts=["peer-comparison.json", "ranking.json"],
            notes="Ranked target and peers using deterministic evidence-backed scorecard.",
            source_ids=self._source_ids(evidence),
        )
        if review_art is not None:
            yield self._artifact_event(review_art)

        capital_plan = self._build_capital_plan(symbol, ranking)
        if self.artifacts is not None:
            capital_art = await self.artifacts.write(
                name="capital-plan.json",
                content=json.dumps(capital_plan, ensure_ascii=False, indent=2, default=str),
                kind="json",
                description="Bounded capital allocation and risk plan",
                role="evaluation",
                display_name="Capital plan",
                source_refs=self._source_ids(evidence),
            )
            yield self._artifact_event(capital_art)
        review_art = await self._record_capability_review(
            reviews,
            stage="capital_plan",
            artifacts=["capital-plan.json"],
            notes="Converted ranking into bounded sizing guidance without order execution.",
            source_ids=self._source_ids(evidence),
        )
        if review_art is not None:
            yield self._artifact_event(review_art)

        memo, decision = await self._synthesize(
            symbol, question, evidence, gate_outputs, ranking, capital_plan
        )
        review_art = await self._record_capability_review(
            reviews,
            stage="synthesis",
            artifacts=["final-report.md", "decision.json"],
            notes="Synthesized final memo from gates, peer ranking, and capital plan.",
            source_ids=self._source_ids(evidence),
        )
        if review_art is not None:
            yield self._artifact_event(review_art)
        if self.artifacts is not None:
            report = await self.artifacts.write(
                name="final-report.md",
                content=memo,
                kind="markdown",
                description="Primary company investment memo",
                role="primary",
                display_name="Investment memo",
                source_refs=self._source_ids(evidence),
            )
            yield self._artifact_event(report)
            decision_art = await self.artifacts.write(
                name="decision.json",
                content=json.dumps(decision, ensure_ascii=False, indent=2),
                kind="json",
                description="Structured investment decision",
                role="evaluation",
                display_name="Investment decision",
                source_refs=self._source_ids(evidence),
            )
            yield self._artifact_event(decision_art)

        yield AgentEvent(type="delta", data={"text": memo})

    async def _collect_evidence(self, symbol: str, peers: list[str]) -> dict[str, Any]:
        events: list[AgentEvent] = []
        symbols = [symbol, *peers[:3]]
        evidence: dict[str, Any] = {
            "target_symbol": symbol,
            "peer_symbols": peers[:3],
            "market": "US",
            "events": events,
            "companies": {},
        }
        for company_symbol in symbols:
            company: dict[str, Any] = {}
            calls = [
                ("market_quote", {"symbol": company_symbol}),
                ("financials", {"symbol": company_symbol}),
                (
                    "news_search",
                    {"query": f"{company_symbol} company earnings moat valuation", "limit": 3},
                ),
            ]
            for name, args in calls:
                call_id = uuid.uuid4().hex[:8]
                events.append(
                    AgentEvent(
                        type="tool_call",
                        step_id=call_id,
                        data={"name": name, "args": args, "_already_executed": True},
                    )
                )
                result = await self._execute_tool(name, args)
                events.append(
                    AgentEvent(
                        type="tool_result",
                        step_id=call_id,
                        data={
                            "name": name,
                            "ok": result.ok,
                            "summary": result.summary,
                            "preview": result.preview,
                            "error": result.error,
                        },
                    )
                )
                company[name] = {
                    "ok": result.ok,
                    "summary": result.summary,
                    "preview": result.preview,
                    "error": result.error,
                }
            evidence["companies"][company_symbol] = company
        return evidence

    async def _execute_tool(self, name: str, args: dict[str, Any]) -> ToolCallFulfilled:
        if self._tool_executor is None:
            return ToolCallFulfilled(
                call_id=uuid.uuid4().hex[:8],
                name=name,
                ok=False,
                summary="",
                error="tool executor missing",
            )
        return await self._tool_executor(name, args)

    async def _write_evidence_artifacts(self, symbol: str, evidence: dict[str, Any]) -> None:
        if self.artifacts is None:
            return
        companies = evidence.get("companies", {})
        target = companies.get(symbol, {}) if isinstance(companies, dict) else {}
        profile = {
            "symbol": symbol,
            "market": evidence.get("market", "US"),
            "peer_symbols": evidence.get("peer_symbols", []),
            "quote": target.get("market_quote", {}),
            "source_ids": self._source_ids(evidence),
        }
        financials = {
            company_symbol: company.get("financials", {})
            for company_symbol, company in companies.items()
            if isinstance(company, dict)
        }
        news = {
            company_symbol: company.get("news_search", {})
            for company_symbol, company in companies.items()
            if isinstance(company, dict)
        }
        files = [
            ("company-profile.json", profile, "Company profile and quote snapshot", "Company profile"),
            ("financials.json", financials, "Financial snapshots for target and peers", "Financials"),
            ("news-brief.json", news, "Recent news evidence for target and peers", "News brief"),
        ]
        for name, payload, description, display in files:
            await self.artifacts.write(
                name=name,
                content=json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                kind="json",
                description=description,
                role="auxiliary",
                display_name=display,
                source_refs=self._source_ids(evidence),
            )

    async def _run_gate(
        self,
        gate: CompanyGate,
        symbol: str,
        question: str,
        evidence: dict[str, Any],
        previous: list[dict[str, str]],
    ) -> str:
        if settings.use_mock_llm:
            return self._mock_gate(gate, symbol, evidence)
        llm = default_router.resolve(self.model)
        if not llm.configured:
            return self._mock_gate(gate, symbol, evidence)

        prompt = self._gate_prompt(gate, symbol, question, evidence, previous)
        chunks: list[str] = []
        async for chunk in llm.stream_chat([ChatMessage(role="user", content=prompt)]):
            if isinstance(chunk, UsageDelta):
                continue
            chunks.append(chunk)
        text = "".join(chunks).strip()
        return text or self._mock_gate(gate, symbol, evidence)

    async def _synthesize(
        self,
        symbol: str,
        question: str,
        evidence: dict[str, Any],
        gate_outputs: list[dict[str, str]],
        ranking: dict[str, Any],
        capital_plan: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        if settings.use_mock_llm:
            memo = self._mock_memo(symbol, gate_outputs, ranking, capital_plan)
            return memo, self._decision_from_text(symbol, memo, ranking, capital_plan)
        llm = default_router.resolve(self.model)
        if not llm.configured:
            memo = self._mock_memo(symbol, gate_outputs, ranking, capital_plan)
            return memo, self._decision_from_text(symbol, memo, ranking, capital_plan)

        prompt = self._synthesis_prompt(symbol, question, evidence, gate_outputs, ranking, capital_plan)
        chunks: list[str] = []
        async for chunk in llm.stream_chat([ChatMessage(role="user", content=prompt)]):
            if isinstance(chunk, UsageDelta):
                continue
            chunks.append(chunk)
        memo = "".join(chunks).strip() or self._mock_memo(
            symbol, gate_outputs, ranking, capital_plan
        )
        memo = self._sanitize_citations(memo)
        return memo, self._decision_from_text(symbol, memo, ranking, capital_plan)

    def _gate_prompt(
        self,
        gate: CompanyGate,
        symbol: str,
        question: str,
        evidence: dict[str, Any],
        previous: list[dict[str, str]],
    ) -> str:
        prior = "\n\n".join(f"## {p['display_name']}\n{p['text'][:900]}" for p in previous)
        source_block = self.sources.catalog.to_llm_block() if self.sources is not None else ""
        return f"""你是公司投研 7-gate pipeline 的第 {gate.number} 关：{gate.display_name}。

目标公司：{symbol}
用户问题：{question}
当前维度：{gate.focus}

要求：
- 只分析当前维度，不重复前序 gate。
- 每个关键判断必须带 [src:N]；没有来源时写 [src:none]。
- 输出 markdown，包含 `## Key findings`、`## Analysis`、`## Gate conclusion`。
- Gate conclusion 用 80-120 字给出本维度最重要判断。

【数据来源目录】
{source_block or "[src:none] 当前只有工具摘要，缺少可引用来源。"}

【证据摘要】
{json.dumps({k: v for k, v in evidence.items() if k != "events"}, ensure_ascii=False, default=str)[:3500]}

【前序 gate 摘要】
{prior or "无"}
"""

    def _synthesis_prompt(
        self,
        symbol: str,
        question: str,
        evidence: dict[str, Any],
        gate_outputs: list[dict[str, str]],
        ranking: dict[str, Any],
        capital_plan: dict[str, Any],
    ) -> str:
        source_block = self.sources.catalog.to_llm_block() if self.sources is not None else ""
        gates = "\n\n".join(f"## {g['display_name']}\n{g['text'][:900]}" for g in gate_outputs)
        return f"""你是综合巴菲特、费雪、芒格框架的公司投研负责人。

目标公司：{symbol}
用户问题：{question}

请基于六个 gate 产出一份最终投资备忘录，markdown 格式，控制在 1800-2600 字：
# {symbol} Investment Memo
## Verdict
必须给出 BUY / WATCH / AVOID、conviction、position size。
## Business Quality
## Growth Quality
## Moat
## Management
## Reverse Test
## Valuation
## Peer Ranking
解释目标公司相对最多 3 家同行的排序与关键差异。
## Capital Plan
说明建议初始仓位、最大仓位、加仓/减仓/卖出触发条件；不得建议真实下单。
## Key Risks
## Monitoring Triggers

每个 section 至少一个 [src:N] 或 [src:none] 引用，严禁编造来源编号。

【数据来源目录】
{source_block or "[src:none]"}

【证据摘要】
{json.dumps({k: v for k, v in evidence.items() if k != "events"}, ensure_ascii=False, default=str)[:3000]}

【六个 gate 输出】
{gates}

【同行排序】
{json.dumps(ranking, ensure_ascii=False, default=str)[:1800]}

【资金管理计划】
{json.dumps(capital_plan, ensure_ascii=False, default=str)[:1800]}
"""

    def _build_peer_comparison(
        self,
        symbol: str,
        peers: list[str],
        evidence: dict[str, Any],
        gate_outputs: list[dict[str, str]],
    ) -> dict[str, Any]:
        companies = evidence.get("companies", {})
        rows: list[dict[str, Any]] = []
        gate_signal = min(1.0, len(gate_outputs) / max(1, len(COMPANY_GATES)))
        for idx, company_symbol in enumerate([symbol, *peers[:3]]):
            company = companies.get(company_symbol, {}) if isinstance(companies, dict) else {}
            quote = self._preview_data(company.get("market_quote", {}))
            financials = self._preview_data(company.get("financials", {}))
            news = self._preview_data(company.get("news_search", {}))
            latest_financial = self._latest_financial_row(financials)

            roe = self._as_float(latest_financial.get("roe"))
            gross_margin = self._as_float(latest_financial.get("gross_margin"))
            revenue_yoy = self._as_float(latest_financial.get("revenue_yoy"))
            pe = self._as_float(quote.get("pe_ttm") or quote.get("pe"))
            market_cap = self._as_float(quote.get("market_cap_usd_b") or quote.get("market_cap_b"))

            quality = self._bounded_score(50 + roe * 0.8 + gross_margin * 0.25)
            growth = self._bounded_score(50 + revenue_yoy * 0.9)
            moat = self._bounded_score(55 + min(market_cap, 3000) / 120 + gate_signal * 10)
            valuation = self._bounded_score(72 - max(pe - 18, 0) * 0.8 if pe else 55)
            risk = self._bounded_score(45 + len(str(news)) / 2000)
            total = round(
                quality * 0.28 + growth * 0.22 + moat * 0.24 + valuation * 0.18 - risk * 0.08,
                2,
            )
            rows.append(
                {
                    "symbol": company_symbol,
                    "role": "target" if company_symbol == symbol else "peer",
                    "scores": {
                        "quality": round(quality, 2),
                        "growth": round(growth, 2),
                        "moat": round(moat, 2),
                        "valuation": round(valuation, 2),
                        "risk": round(risk, 2),
                        "total": total,
                    },
                    "evidence_summary": {
                        "quote": company.get("market_quote", {}).get("summary", ""),
                        "financials": company.get("financials", {}).get("summary", ""),
                        "news": company.get("news_search", {}).get("summary", ""),
                    },
                    "notes": self._comparison_notes(company_symbol, idx, pe, roe, revenue_yoy),
                }
            )
        return {
            "target_symbol": symbol,
            "peer_symbols": peers[:3],
            "method": "deterministic scorecard: quality/growth/moat/valuation/risk",
            "rows": rows,
            "source_ids": self._source_ids(evidence),
        }

    @staticmethod
    def _build_ranking(peer_comparison: dict[str, Any]) -> dict[str, Any]:
        ranked = sorted(
            peer_comparison.get("rows", []),
            key=lambda row: row.get("scores", {}).get("total", 0),
            reverse=True,
        )
        for rank, row in enumerate(ranked, start=1):
            row["rank"] = rank
        target_symbol = peer_comparison.get("target_symbol", "")
        target_row = next((row for row in ranked if row.get("symbol") == target_symbol), {})
        target_rank = target_row.get("rank")
        if target_rank == 1:
            action = "BUY"
        elif target_rank in (2, 3):
            action = "WATCH"
        else:
            action = "AVOID"
        return {
            "target_symbol": target_symbol,
            "action": action,
            "target_rank": target_rank,
            "ranked_companies": ranked[:4],
            "max_companies": 4,
        }

    @staticmethod
    def _build_capital_plan(symbol: str, ranking: dict[str, Any]) -> dict[str, Any]:
        action = ranking.get("action", "WATCH")
        target_rank = ranking.get("target_rank")
        if action == "BUY" and target_rank == 1:
            max_position_pct = 10.0
            initial_position_pct = 4.0
        elif action == "WATCH":
            max_position_pct = 5.0
            initial_position_pct = 1.5
        else:
            max_position_pct = 0.0
            initial_position_pct = 0.0
        return {
            "symbol": symbol,
            "action": action,
            "real_order_execution": False,
            "initial_position_pct": initial_position_pct,
            "max_position_pct": max_position_pct,
            "risk_budget": {
                "max_single_name_pct": 10.0,
                "max_initial_position_pct": 4.0,
                "review_drawdown_pct": -20.0,
                "thesis_break_loss_pct": -30.0,
                "cash_buffer_required": True,
            },
            "add_triggers": [
                "next filing confirms revenue growth and margin quality",
                "valuation moves into the required margin-of-safety band",
                "peer ranking remains top quartile after updated evidence",
            ],
            "trim_triggers": [
                "position exceeds max_position_pct after price appreciation",
                "valuation score deteriorates while fundamentals do not improve",
                "new evidence lowers moat or management assessment",
            ],
            "sell_triggers": [
                "thesis-breaking accounting, governance, or competitive evidence appears",
                "durable growth assumptions fail for two consecutive reporting periods",
                "risk budget breach is not cured by trimming",
            ],
            "notes": (
                "This is sizing guidance only. The pipeline deliberately does not place orders "
                "or connect to a broker."
            ),
        }

    async def _record_capability_review(
        self,
        reviews: list[dict[str, Any]],
        *,
        stage: str,
        artifacts: list[str],
        notes: str,
        source_ids: list[int],
    ) -> Any | None:
        reviews.append(
            {
                "stage": stage,
                "autonomy": "stage completed without user intervention",
                "observability": {
                    "artifacts": artifacts,
                    "events": ["tool_call", "tool_result"]
                    if stage == "evidence"
                    else ["subagent_start", "artifact_written", "subagent_end"],
                },
                "traceability": {"source_ids": source_ids, "persisted_artifacts": artifacts},
                "self_iteration": (
                    "later runs can compare this artifact with updated evidence and revise the memo"
                ),
                "notes": notes,
            }
        )
        if self.artifacts is None:
            return None
        return await self.artifacts.write(
            name="agent-capability-review.json",
            content=json.dumps({"stages": reviews}, ensure_ascii=False, indent=2, default=str),
            kind="json",
            description="Stage-level agent autonomy, observability, traceability, and iteration review",
            role="evaluation",
            display_name="Agent capability review",
            source_refs=source_ids,
        )

    @staticmethod
    def _preview_data(tool_payload: dict[str, Any]) -> dict[str, Any]:
        preview = tool_payload.get("preview") if isinstance(tool_payload, dict) else None
        if isinstance(preview, dict):
            return preview
        return {}

    @staticmethod
    def _latest_financial_row(financials: dict[str, Any]) -> dict[str, Any]:
        rows = financials.get("rows", [])
        if isinstance(rows, list) and rows:
            latest = rows[-1]
            return latest if isinstance(latest, dict) else {}
        return {}

    @staticmethod
    def _as_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _bounded_score(value: float) -> float:
        return max(0.0, min(100.0, value))

    @staticmethod
    def _comparison_notes(symbol: str, idx: int, pe: float, roe: float, revenue_yoy: float) -> list[str]:
        notes = [f"{symbol} ranked with evidence-backed scorecard."]
        if idx > 0:
            notes.append("Peer score is used as a relative yardstick, not a full thesis.")
        if pe:
            notes.append(f"Valuation check uses observed PE around {pe:.1f}.")
        if roe:
            notes.append(f"Quality check uses observed ROE around {roe:.1f}.")
        if revenue_yoy:
            notes.append(f"Growth check uses observed revenue YoY around {revenue_yoy:.1f}.")
        return notes

    @staticmethod
    def _mock_gate(gate: CompanyGate, symbol: str, evidence: dict[str, Any]) -> str:
        source_ids = CompanyResearchPipeline._source_ids(evidence)
        cite = f"[src:{source_ids[0]}]" if source_ids else "[src:none]"
        return (
            f"# Gate {gate.number}: {gate.display_name}\n\n"
            f"## Key findings\n- {symbol} 的{gate.focus}需要结合财务和新闻继续验证 {cite}\n\n"
            f"## Analysis\n当前为 mock gate 输出，保留 uteki.open 7-gate 的维度边界。\n\n"
            f"## Gate conclusion\n{symbol} 在「{gate.display_name}」维度暂无硬性否决项，但需要真实数据进一步确认 {cite}\n"
        )

    @staticmethod
    def _mock_memo(
        symbol: str,
        gate_outputs: list[dict[str, str]],
        ranking: dict[str, Any],
        capital_plan: dict[str, Any],
    ) -> str:
        sections = "\n".join(f"- {g['display_name']}: 已完成" for g in gate_outputs)
        action = ranking.get("action", "WATCH")
        max_position = capital_plan.get("max_position_pct", 0)
        return (
            f"# {symbol} Investment Memo\n\n"
            f"## Verdict\n{action}，最大建议仓位 {max_position}%；该建议不执行真实下单 [src:none]\n\n"
            "## Gate Coverage\n"
            f"{sections}\n\n"
            "## Peer Ranking\n"
            f"{json.dumps(ranking.get('ranked_companies', []), ensure_ascii=False, default=str)} [src:none]\n\n"
            "## Capital Plan\n"
            f"初始仓位 {capital_plan.get('initial_position_pct', 0)}%，"
            f"最大仓位 {capital_plan.get('max_position_pct', 0)}%。严格按风险触发条件复核 [src:none]\n\n"
            "## Monitoring Triggers\n- 财报增速、利润率、管理层动作、估值区间 [src:none]\n"
        )

    @staticmethod
    def _sanitize_citations(text: str) -> str:
        """Keep final deliverables citation-compatible with SourceCatalog ids."""

        def replace(match: re.Match[str]) -> str:
            value = match.group(1).strip()
            if value == "none" or value.isdigit():
                return match.group(0)
            return "[src:none]"

        return re.sub(r"\[src:([^\]]+)\]", replace, text)

    @staticmethod
    def _decision_from_text(
        symbol: str,
        memo: str,
        ranking: dict[str, Any] | None = None,
        capital_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        upper = memo.upper()
        if "BUY" in upper:
            action = "BUY"
        elif "AVOID" in upper or "SELL" in upper:
            action = "AVOID"
        else:
            action = "WATCH"
        if ranking and ranking.get("action"):
            action = str(ranking["action"])
        return {
            "symbol": symbol,
            "action": action,
            "conviction": 0.6 if action == "BUY" else 0.4,
            "target_rank": ranking.get("target_rank") if ranking else None,
            "initial_position_pct": capital_plan.get("initial_position_pct") if capital_plan else None,
            "max_position_pct": capital_plan.get("max_position_pct") if capital_plan else None,
            "real_order_execution": False,
            "quality_verdict": "UNKNOWN",
            "source": "final-report.md",
        }

    @staticmethod
    def _source_ids(evidence: dict[str, Any]) -> list[int]:
        ids: list[int] = []
        stack: list[Any] = [evidence]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                preview = item.get("preview")
                if isinstance(preview, dict):
                    raw = preview.get("_source_ids")
                    if isinstance(raw, list):
                        ids.extend(i for i in raw if isinstance(i, int))
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
        return sorted(set(ids))

    @classmethod
    def _extract_symbols(cls, text: str) -> tuple[str, list[str]]:
        candidates = re.findall(r"\b[A-Z]{1,5}(?:\.[A-Z]{2})?\b|\b\d{6}\.(?:SH|SZ)\b", text)
        stop = {"BUY", "WATCH", "AVOID", "PE", "PB", "PS", "FCF", "MAX", "US"}
        ordered: list[str] = []
        for candidate in candidates:
            if candidate in stop or candidate in ordered:
                continue
            ordered.append(candidate)
        symbol = ordered[0] if ordered else "AAPL"
        explicit_peers = [candidate for candidate in ordered[1:] if candidate != symbol][:3]
        peers = explicit_peers or cls._default_peers(symbol)
        return symbol, peers[:3]

    @staticmethod
    def _default_peers(symbol: str) -> list[str]:
        peer_map = {
            "AAPL": ["MSFT", "GOOGL", "META"],
            "MSFT": ["GOOGL", "AMZN", "ORCL"],
            "NVDA": ["AMD", "AVGO", "INTC"],
            "GOOGL": ["META", "MSFT", "AMZN"],
            "AMZN": ["WMT", "MSFT", "GOOGL"],
            "TSLA": ["GM", "F", "RIVN"],
            "META": ["GOOGL", "SNAP", "PINS"],
        }
        return peer_map.get(symbol, ["MSFT", "GOOGL", "AMZN"])

    @staticmethod
    def _latest_user_message(messages: list[ChatMessage]) -> str:
        for message in reversed(messages):
            if message.role == "user":
                return message.content
        return ""

    @staticmethod
    def _extract_symbol(text: str) -> str:
        return CompanyResearchPipeline._extract_symbols(text)[0]

    @staticmethod
    def _artifact_event(art: Any) -> AgentEvent:
        return AgentEvent(
            type="artifact_written",
            data={
                "name": art.name,
                "kind": art.kind,
                "size_bytes": art.size_bytes,
                "written_by": art.written_by,
                "description": art.description,
                "url": f"/api/runs/{art.run_id}/artifacts/{art.name}",
                "role": art.role,
                "display_name": art.display_name,
            },
        )


__all__ = ["CompanyResearchPipeline", "COMPANY_GATES", "CompanyGate"]
