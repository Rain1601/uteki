"""Company research pipeline migrated from uteki.open's 7-gate flow."""

from __future__ import annotations

import asyncio
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
from uteki_api.provenance import extract_citations
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

COMPANY_SCHEMA_VERSION = "company_research_pipeline.v1"
CLAIM_SCHEMA_VERSION = "company_claim_audit.v1"
SOURCE_QUALITY_SCHEMA_VERSION = "company_source_quality.v1"

CORE_FINAL_SECTIONS = {"Verdict", "Capital Plan", "Key Risks"}
REQUIRED_GATE_SECTIONS = ("Key findings", "Analysis", "Gate conclusion")
PROCESS_LEAK_PATTERNS = (
    r"<tool_call",
    r"</tool_call>",
    r"\bweb_search\b",
    r"\btool_result\b",
    r"^\s*(\*\*)?思考(\*\*)?\s*[:：]",
    r"^\s*(\*\*)?行动(\*\*)?\s*[:：]",
    r"^\s*(\*\*)?observation(\*\*)?\s*[:：]",
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
            "prompt": "company-research-7gate-peer-capital-claim-audit:v3",
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
                    "Synthesize final-report.md + decision.json + company-run-diagnosis.json",
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
            text = self._sanitize_deliverable_text(text)
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
        source_quality = self._build_source_quality()
        claim_audit = self._build_claim_audit(
            symbol=symbol,
            gate_outputs=gate_outputs,
            memo=memo,
            source_quality=source_quality,
        )
        review_art = await self._record_capability_review(
            reviews,
            stage="synthesis",
            artifacts=[
                "final-report.md",
                "decision.json",
                "company-claims.json",
                "company-source-quality.json",
            ],
            notes="Synthesized final memo and audited claim/source quality.",
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
            claims_art = await self.artifacts.write(
                name="company-claims.json",
                content=json.dumps(claim_audit, ensure_ascii=False, indent=2, default=str),
                kind="json",
                description="Structured claim support audit for company research output",
                role="evaluation",
                display_name="Company claims",
                source_refs=self._source_ids(evidence),
            )
            yield self._artifact_event(claims_art)
            source_quality_art = await self.artifacts.write(
                name="company-source-quality.json",
                content=json.dumps(source_quality, ensure_ascii=False, indent=2, default=str),
                kind="json",
                description="Source tier and trust-quality assessment",
                role="diagnosis",
                display_name="Source quality",
                source_refs=self._source_ids(evidence),
            )
            yield self._artifact_event(source_quality_art)
            diagnosis = self._build_run_diagnosis(
                symbol=symbol,
                evidence=evidence,
                gate_outputs=gate_outputs,
                ranking=ranking,
                capital_plan=capital_plan,
                memo=memo,
                decision=decision,
                claim_audit=claim_audit,
                source_quality=source_quality,
            )
            diagnosis_art = await self.artifacts.write(
                name="company-run-diagnosis.json",
                content=json.dumps(diagnosis, ensure_ascii=False, indent=2, default=str),
                kind="json",
                description="Company run artifact contract and citation quality diagnosis",
                role="diagnosis",
                display_name="Company run diagnosis",
                source_refs=self._source_ids(evidence),
            )
            yield self._artifact_event(diagnosis_art)

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
        jobs: list[tuple[str, str, dict[str, Any], str]] = []
        for company_symbol in symbols:
            evidence["companies"][company_symbol] = {}
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
                jobs.append((company_symbol, name, args, call_id))
                events.append(
                    AgentEvent(
                        type="tool_call",
                        step_id=call_id,
                        data={"name": name, "args": args, "_already_executed": True},
                    )
                )
        results = await asyncio.gather(
            *(self._execute_tool(name, args) for _company_symbol, name, args, _call_id in jobs),
            return_exceptions=True,
        )
        for (company_symbol, name, _args, call_id), result in zip(jobs, results, strict=True):
            if isinstance(result, Exception):
                result = ToolCallFulfilled(
                    call_id=call_id,
                    name=name,
                    ok=False,
                    summary="",
                    error=str(result),
                )
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
            company = evidence["companies"].setdefault(company_symbol, {})
            company[name] = {
                "ok": result.ok,
                "summary": result.summary,
                "preview": result.preview,
                "error": result.error,
            }
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
            "schema_version": COMPANY_SCHEMA_VERSION,
            "symbol": symbol,
            "market": evidence.get("market", "US"),
            "peer_symbols": evidence.get("peer_symbols", []),
            "quote": target.get("market_quote", {}),
            "source_ids": self._source_ids(evidence),
        }
        financials = {
            "schema_version": COMPANY_SCHEMA_VERSION,
            "target_symbol": symbol,
        }
        financials.update(
            {
                company_symbol: company.get("financials", {})
                for company_symbol, company in companies.items()
                if isinstance(company, dict)
            }
        )
        news = {
            "schema_version": COMPANY_SCHEMA_VERSION,
            "target_symbol": symbol,
        }
        news.update(
            {
                company_symbol: company.get("news_search", {})
                for company_symbol, company in companies.items()
                if isinstance(company, dict)
            }
        )
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
        memo = self._sanitize_deliverable_text(memo)
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
            "schema_version": COMPANY_SCHEMA_VERSION,
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
            "schema_version": COMPANY_SCHEMA_VERSION,
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
            "schema_version": COMPANY_SCHEMA_VERSION,
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
            content=json.dumps(
                {"schema_version": COMPANY_SCHEMA_VERSION, "stages": reviews},
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            kind="json",
            description="Stage-level agent autonomy, observability, traceability, and iteration review",
            role="evaluation",
            display_name="Agent capability review",
            source_refs=source_ids,
        )

    def _build_source_quality(self) -> dict[str, Any]:
        points = self._catalog_points()
        by_tier = {1: 0, 2: 0, 3: 0, 4: 0}
        by_type: dict[str, int] = {}
        by_confidence = {"high": 0, "medium": 0, "low": 0}
        tiered_sources: list[dict[str, Any]] = []
        low_confidence_ids: list[int] = []
        ungrounded_ids: list[int] = []
        search_snippet_ids: list[int] = []

        for point in points:
            tier, tier_label, reason = self._source_tier(point)
            source_type = str(point.get("source_type") or "unknown")
            confidence = str(point.get("confidence") or "medium")
            point_id = int(point.get("id", 0) or 0)
            by_tier[tier] += 1
            by_type[source_type] = by_type.get(source_type, 0) + 1
            if confidence in by_confidence:
                by_confidence[confidence] += 1
            if confidence == "low":
                low_confidence_ids.append(point_id)
            if not self._point_is_grounded(point):
                ungrounded_ids.append(point_id)
            if source_type == "web_search":
                search_snippet_ids.append(point_id)
            tiered_sources.append(
                {
                    "id": point_id,
                    "key": point.get("key"),
                    "source_type": source_type,
                    "publisher": point.get("publisher"),
                    "confidence": confidence,
                    "tier": tier,
                    "tier_label": tier_label,
                    "reason": reason,
                }
            )

        total = len(points)
        tier4_ratio = (by_tier[4] / total) if total else 1.0
        status = "pass"
        if total == 0:
            status = "fail"
        elif by_tier[1] + by_tier[2] == 0 or tier4_ratio > 0.5:
            status = "warn"
        return {
            "schema_version": SOURCE_QUALITY_SCHEMA_VERSION,
            "status": status,
            "metrics": {
                "source_count": total,
                "tier_1_count": by_tier[1],
                "tier_2_count": by_tier[2],
                "tier_3_count": by_tier[3],
                "tier_4_count": by_tier[4],
                "tier_4_ratio": round(tier4_ratio, 4),
                "high_confidence_count": by_confidence["high"],
                "medium_confidence_count": by_confidence["medium"],
                "low_confidence_count": by_confidence["low"],
                "ungrounded_count": len(ungrounded_ids),
                "search_snippet_count": len(search_snippet_ids),
            },
            "by_type": by_type,
            "low_confidence_source_ids": low_confidence_ids,
            "ungrounded_source_ids": ungrounded_ids,
            "search_snippet_source_ids": search_snippet_ids,
            "tiered_sources": tiered_sources,
            "policy": {
                "tier_1": "filings, structured financials, and official/company evidence",
                "tier_2": "market data and reputable news",
                "tier_3": "aggregators or secondary analysis",
                "tier_4": "search snippets, mock fixtures, unsupported or ungrounded sources",
            },
        }

    def _build_claim_audit(
        self,
        *,
        symbol: str,
        gate_outputs: list[dict[str, str]],
        memo: str,
        source_quality: dict[str, Any],
    ) -> dict[str, Any]:
        valid_ids = set(self._source_ids({"gate_outputs": gate_outputs, "memo": memo}))
        if self.sources is not None:
            valid_ids.update(self.sources.valid_ids())
        source_index = {int(item["id"]): item for item in source_quality.get("tiered_sources", [])}

        claims: list[dict[str, Any]] = []

        def add_claim(stage: str, kind: str, text: str, *, core: bool = False) -> None:
            clean = self._compact_claim_text(text)
            if not clean:
                return
            extracted = extract_citations(clean, valid_ids=valid_ids)
            source_ids = sorted(extracted.all_cited_ids())
            tiers = [
                int(source_index[source_id]["tier"])
                for source_id in source_ids
                if source_id in source_index and source_index[source_id].get("tier") is not None
            ]
            numbers = self._extract_numbers(extracted.stripped())
            has_financial_source = any(
                str((self._catalog_point(source_id) or {}).get("source_type"))
                in {"financials", "market_data", "filing", "computed"}
                for source_id in source_ids
            )
            weak_source = bool(tiers and min(tiers) >= 4)
            unsupported = not source_ids
            number_unbacked = bool(numbers and not source_ids)
            number_weak = bool(numbers and source_ids and not has_financial_source)
            claims.append(
                {
                    "id": f"C{len(claims) + 1:03d}",
                    "symbol": symbol,
                    "stage": stage,
                    "kind": kind,
                    "core": core,
                    "text": clean,
                    "source_ids": source_ids,
                    "source_tiers": tiers,
                    "unsupported": unsupported,
                    "weak_source": weak_source,
                    "no_source_markers": extracted.no_source_count,
                    "orphan_source_ids": extracted.orphan_ids,
                    "numbers": numbers,
                    "number_unbacked": number_unbacked,
                    "number_weakly_sourced": number_weak,
                }
            )

        for gate in gate_outputs:
            stage = str(gate.get("name") or gate.get("display_name") or "gate")
            text = str(gate.get("text") or "")
            for line in self._markdown_section(text, "Key findings").splitlines():
                add_claim(stage, "key_finding", line)
            conclusion = self._markdown_section(text, "Gate conclusion")
            add_claim(stage, "gate_conclusion", conclusion, core=True)

        for heading in ("Verdict", "Capital Plan", "Key Risks", "Valuation", "Peer Ranking"):
            section = self._markdown_section(memo, heading)
            if section:
                add_claim("final_memo", heading.lower().replace(" ", "_"), section, core=heading in CORE_FINAL_SECTIONS)

        unsupported = [claim for claim in claims if claim["unsupported"]]
        unsupported_core = [claim for claim in unsupported if claim["core"]]
        weak_core = [claim for claim in claims if claim["core"] and claim["weak_source"]]
        unbacked_numbers = [claim for claim in claims if claim["number_unbacked"]]
        weak_numbers = [claim for claim in claims if claim["number_weakly_sourced"]]
        orphan_claims = [claim for claim in claims if claim["orphan_source_ids"]]
        process_leaks = self._process_leak_hits("\n\n".join(claim["text"] for claim in claims))

        return {
            "schema_version": CLAIM_SCHEMA_VERSION,
            "symbol": symbol,
            "claims": claims,
            "summary": {
                "claim_count": len(claims),
                "core_claim_count": sum(1 for claim in claims if claim["core"]),
                "unsupported_claim_count": len(unsupported),
                "unsupported_core_claim_count": len(unsupported_core),
                "weak_core_claim_count": len(weak_core),
                "unbacked_number_claim_count": len(unbacked_numbers),
                "weak_number_claim_count": len(weak_numbers),
                "orphan_claim_count": len(orphan_claims),
                "process_leak_count": len(process_leaks),
            },
            "unsupported_claim_ids": [claim["id"] for claim in unsupported],
            "unsupported_core_claim_ids": [claim["id"] for claim in unsupported_core],
            "weak_core_claim_ids": [claim["id"] for claim in weak_core],
            "unbacked_number_claim_ids": [claim["id"] for claim in unbacked_numbers],
            "weak_number_claim_ids": [claim["id"] for claim in weak_numbers],
            "process_leaks": process_leaks,
        }

    def _build_run_diagnosis(
        self,
        *,
        symbol: str,
        evidence: dict[str, Any],
        gate_outputs: list[dict[str, str]],
        ranking: dict[str, Any],
        capital_plan: dict[str, Any],
        memo: str,
        decision: dict[str, Any],
        claim_audit: dict[str, Any] | None = None,
        source_quality: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        claim_audit = claim_audit or self._build_claim_audit(
            symbol=symbol,
            gate_outputs=gate_outputs,
            memo=memo,
            source_quality=source_quality or self._build_source_quality(),
        )
        source_quality = source_quality or self._build_source_quality()
        valid_ids = set(self._source_ids(evidence))
        gate_text = "\n\n".join(gate.get("text", "") for gate in gate_outputs)
        memo_citations = extract_citations(memo, valid_ids=valid_ids)
        gate_citations = extract_citations(gate_text, valid_ids=valid_ids)
        orphan_ids = sorted(set(memo_citations.orphan_ids + gate_citations.orphan_ids))
        citation_markers = len(memo_citations.citations) + len(gate_citations.citations)
        no_source_count = memo_citations.no_source_count + gate_citations.no_source_count
        numeric_citation_count = sum(
            len(citation.ids) for citation in memo_citations.citations + gate_citations.citations
        )

        checks: list[dict[str, Any]] = []

        def add_check(name: str, status: str, severity: str, detail: str) -> None:
            checks.append(
                {
                    "name": name,
                    "status": status,
                    "severity": severity,
                    "detail": detail,
                }
            )

        gate_count = len(gate_outputs)
        add_check(
            "gate_coverage",
            "pass" if gate_count == len(COMPANY_GATES) else "fail",
            "error" if gate_count != len(COMPANY_GATES) else "info",
            f"{gate_count}/{len(COMPANY_GATES)} company gates completed.",
        )
        add_check(
            "source_catalog",
            "pass" if valid_ids else "warn",
            "warning" if not valid_ids else "info",
            f"{len(valid_ids)} source ids attached to company evidence.",
        )

        gate_contract_errors = self._gate_contract_errors(gate_outputs)
        add_check(
            "gate_contract",
            "pass" if not gate_contract_errors else "fail",
            "error" if gate_contract_errors else "info",
            (
                "All gates include required sections and citations."
                if not gate_contract_errors
                else "; ".join(gate_contract_errors[:4])
            ),
        )

        if orphan_ids:
            citation_status = "fail"
            citation_severity = "error"
            citation_detail = f"Invalid citation ids detected: {orphan_ids}."
        elif citation_markers == 0:
            citation_status = "warn"
            citation_severity = "warning"
            citation_detail = "No citation markers were found in gate outputs or final memo."
        elif numeric_citation_count == 0:
            citation_status = "warn"
            citation_severity = "warning"
            citation_detail = "Only [src:none] markers were found; run is traceable but unsourced."
        else:
            citation_status = "pass"
            citation_severity = "info"
            citation_detail = f"{numeric_citation_count} valid numeric citation references found."
        add_check("citation_integrity", citation_status, citation_severity, citation_detail)

        source_metrics = source_quality.get("metrics", {})
        source_status = str(source_quality.get("status", "warn"))
        tier12_count = int(source_metrics.get("tier_1_count", 0)) + int(
            source_metrics.get("tier_2_count", 0)
        )
        add_check(
            "source_quality",
            source_status if source_status in {"pass", "warn", "fail"} else "warn",
            "error" if source_status == "fail" else "warning" if source_status == "warn" else "info",
            (
                f"tier1+2={tier12_count}, tier4={source_metrics.get('tier_4_count', 0)}, "
                f"low_confidence={source_metrics.get('low_confidence_count', 0)}."
            ),
        )

        claims_summary = claim_audit.get("summary", {})
        unsupported_core = int(claims_summary.get("unsupported_core_claim_count", 0))
        unsupported_total = int(claims_summary.get("unsupported_claim_count", 0))
        weak_core = int(claims_summary.get("weak_core_claim_count", 0))
        claim_status = "pass"
        claim_severity = "info"
        if unsupported_core:
            claim_status = "fail"
            claim_severity = "error"
        elif unsupported_total or weak_core:
            claim_status = "warn"
            claim_severity = "warning"
        add_check(
            "claim_support",
            claim_status,
            claim_severity,
            (
                f"unsupported_core={unsupported_core}, unsupported_total={unsupported_total}, "
                f"weak_core={weak_core}."
            ),
        )

        unbacked_numbers = int(claims_summary.get("unbacked_number_claim_count", 0))
        weak_numbers = int(claims_summary.get("weak_number_claim_count", 0))
        number_status = "pass"
        number_severity = "info"
        if unbacked_numbers:
            number_status = "fail"
            number_severity = "error"
        elif weak_numbers:
            number_status = "warn"
            number_severity = "warning"
        add_check(
            "number_traceability",
            number_status,
            number_severity,
            f"unbacked_number_claims={unbacked_numbers}, weak_number_claims={weak_numbers}.",
        )

        decision_action = str(decision.get("action", ""))
        decision_ok = (
            decision.get("symbol") == symbol
            and decision_action in {"BUY", "WATCH", "AVOID"}
            and decision.get("real_order_execution") is False
        )
        add_check(
            "decision_contract",
            "pass" if decision_ok else "fail",
            "error" if not decision_ok else "info",
            "Decision has symbol, allowed action, and no real order execution.",
        )

        action_values = [
            str(value)
            for value in (ranking.get("action"), capital_plan.get("action"), decision.get("action"))
            if value
        ]
        action_consistent = len(set(action_values)) <= 1
        rank_consistent = decision.get("target_rank") == ranking.get("target_rank")
        initial_consistent = abs(
            self._as_float(decision.get("initial_position_pct"))
            - self._as_float(capital_plan.get("initial_position_pct"))
        ) < 0.001
        max_consistent = abs(
            self._as_float(decision.get("max_position_pct"))
            - self._as_float(capital_plan.get("max_position_pct"))
        ) < 0.001
        structured_consistent = (
            action_consistent and rank_consistent and initial_consistent and max_consistent
        )
        add_check(
            "structured_consistency",
            "pass" if structured_consistent else "fail",
            "error" if not structured_consistent else "info",
            (
                f"actions={action_values}, target_rank decision/ranking="
                f"{decision.get('target_rank')}/{ranking.get('target_rank')}, "
                f"initial/max positions consistent={initial_consistent}/{max_consistent}."
            ),
        )

        risk_budget = capital_plan.get("risk_budget", {})
        max_position = self._as_float(capital_plan.get("max_position_pct"))
        initial_position = self._as_float(capital_plan.get("initial_position_pct"))
        max_single_name = self._as_float(risk_budget.get("max_single_name_pct"))
        position_ok = (
            initial_position <= max_position
            and max_position <= max_single_name
            and max_single_name <= 10.0
        )
        add_check(
            "position_boundary",
            "pass" if position_ok else "fail",
            "error" if not position_ok else "info",
            (
                f"initial={initial_position}, max={max_position}, "
                f"max_single_name={max_single_name}."
            ),
        )

        read_only_ok = (
            capital_plan.get("real_order_execution") is False
            and decision.get("real_order_execution") is False
        )
        add_check(
            "research_boundary",
            "pass" if read_only_ok else "fail",
            "error" if not read_only_ok else "info",
            "Company pipeline produces research and sizing guidance only.",
        )

        versioned = all(
            payload.get("schema_version") == COMPANY_SCHEMA_VERSION
            for payload in (ranking, capital_plan, decision)
        )
        add_check(
            "schema_version",
            "pass" if versioned else "fail",
            "error" if not versioned else "info",
            f"Structured company artifacts use {COMPANY_SCHEMA_VERSION}.",
        )

        process_leaks = self._process_leak_hits("\n\n".join([memo, gate_text]))
        add_check(
            "deliverable_hygiene",
            "pass" if not process_leaks else "fail",
            "error" if process_leaks else "info",
            (
                "No tool/reasoning process text detected in user-facing deliverables."
                if not process_leaks
                else f"Process text patterns detected: {process_leaks[:4]}."
            ),
        )

        status = "pass"
        if any(check["status"] == "fail" for check in checks):
            status = "fail"
        elif any(check["status"] == "warn" for check in checks):
            status = "warn"

        canonical_outputs = [
            "company-profile.json",
            "financials.json",
            "news-brief.json",
            *[f"gate-{gate.number:02d}-{gate.name}.md" for gate in COMPANY_GATES],
            "peer-comparison.json",
            "ranking.json",
            "capital-plan.json",
            "agent-capability-review.json",
            "final-report.md",
            "decision.json",
            "company-claims.json",
            "company-source-quality.json",
            "company-run-diagnosis.json",
        ]
        return {
            "schema_version": COMPANY_SCHEMA_VERSION,
            "symbol": symbol,
            "status": status,
            "checks": checks,
            "metrics": {
                "gate_count": gate_count,
                "source_count": len(valid_ids),
                "citation_markers": citation_markers,
                "numeric_citation_count": numeric_citation_count,
                "no_source_count": no_source_count,
                "orphan_citation_ids": orphan_ids,
                "ranked_company_count": len(ranking.get("ranked_companies", [])),
                "unsupported_claim_count": unsupported_total,
                "unsupported_core_claim_count": unsupported_core,
                "unbacked_number_claim_count": unbacked_numbers,
                "weak_number_claim_count": weak_numbers,
                "tier_1_source_count": source_metrics.get("tier_1_count", 0),
                "tier_2_source_count": source_metrics.get("tier_2_count", 0),
                "tier_3_source_count": source_metrics.get("tier_3_count", 0),
                "tier_4_source_count": source_metrics.get("tier_4_count", 0),
                "artifact_contract": canonical_outputs,
            },
            "source_quality": source_quality,
            "claim_audit_summary": claims_summary,
            "canonical_outputs": canonical_outputs,
            "notes": [
                "status=warn is acceptable for mock or low-source runs.",
                "status=fail means a contract, citation, or research-boundary check broke.",
            ],
        }

    def _catalog_points(self) -> list[dict[str, Any]]:
        if self.sources is None:
            return []
        return [point.model_dump() for point in self.sources.catalog]

    def _catalog_point(self, source_id: int) -> dict[str, Any] | None:
        if self.sources is None:
            return None
        point = self.sources.catalog.get(source_id)
        return point.model_dump() if point is not None else None

    @staticmethod
    def _source_tier(point: dict[str, Any]) -> tuple[int, str, str]:
        source_type = str(point.get("source_type") or "").lower()
        publisher = str(point.get("publisher") or "").lower()
        source_url = str(point.get("source_url") or "").lower()
        confidence = str(point.get("confidence") or "medium").lower()
        if "mock" in publisher or "mock" in source_url:
            return 4, "mock fixture", "mock or fixture data is useful for tests but not investment evidence"
        if source_type == "web_search":
            return 4, "search snippet", "search result snippets are discovery leads, not primary evidence"
        if not CompanyResearchPipeline._point_is_grounded(point):
            return 4, "ungrounded", "source lacks a verifiable publisher or URL"
        if source_type == "filing" or "sec.gov" in source_url:
            return 1, "primary filing", "regulatory filing or primary disclosure"
        if source_type == "financials":
            if confidence == "low":
                return 3, "low confidence financial data", "structured financial data marked low confidence"
            return 1, "structured financial data", "financial facts from a structured provider"
        if source_type == "market_data":
            return 2, "market data", "quote or market data provider"
        if source_type == "news":
            if any(
                token in publisher
                for token in ("reuters", "cnbc", "wsj", "wall street journal", "ft", "financial times")
            ):
                return 2, "reputable news", "reputable news source"
            if any(token in publisher for token in ("yahoo", "seeking alpha", "investopedia")):
                return 3, "secondary publisher", "aggregated or secondary analysis source"
            return 2, "news", "news source with URL"
        if source_type == "computed":
            return 2 if point.get("derived_from") else 4, "computed", "computed fact"
        if confidence == "low":
            return 3, "low confidence source", "source explicitly marked low confidence"
        return 3, "secondary source", "source is usable but not primary evidence"

    @staticmethod
    def _point_is_grounded(point: dict[str, Any]) -> bool:
        source_type = point.get("source_type")
        if source_type == "computed":
            return bool(point.get("derived_from"))
        if source_type == "user_input":
            return True
        return bool(point.get("source_url")) or bool(point.get("publisher"))

    @staticmethod
    def _compact_claim_text(text: str) -> str:
        clean = re.sub(r"^\s*[-*]\s+", "", text.strip())
        clean = re.sub(r"\s+", " ", clean)
        clean = clean.strip(" -")
        if not clean or clean.startswith("#"):
            return ""
        return clean[:700]

    @staticmethod
    def _extract_numbers(text: str) -> list[str]:
        return sorted(
            set(
                match.group(0)
                for match in re.finditer(
                    r"(?<![A-Za-z])\$?\d+(?:,\d{3})*(?:\.\d+)?\s*(?:%|x|倍|B|M|bn|mm)?",
                    text,
                    re.IGNORECASE,
                )
            )
        )

    @staticmethod
    def _markdown_section(text: str, heading: str) -> str:
        normalized = heading.strip().lower()
        lines = text.splitlines()
        start = -1
        heading_level = 0
        for index, line in enumerate(lines):
            match = re.match(r"^(#{1,4})\s+(.+?)\s*$", line.strip())
            if match and match.group(2).strip().lower() == normalized:
                start = index + 1
                heading_level = len(match.group(1))
                break
        if start == -1:
            return ""
        body: list[str] = []
        for line in lines[start:]:
            match = re.match(r"^(#{1,4})\s+(.+?)\s*$", line.strip())
            if match and len(match.group(1)) <= heading_level:
                break
            body.append(line)
        return "\n".join(body).strip()

    @staticmethod
    def _process_leak_hits(text: str) -> list[str]:
        hits: list[str] = []
        for pattern in PROCESS_LEAK_PATTERNS:
            if re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE):
                hits.append(pattern)
        return hits

    @classmethod
    def _gate_contract_errors(cls, gate_outputs: list[dict[str, str]]) -> list[str]:
        errors: list[str] = []
        for gate in gate_outputs:
            name = str(gate.get("name") or gate.get("display_name") or "gate")
            text = str(gate.get("text") or "")
            missing = [
                section for section in REQUIRED_GATE_SECTIONS if not cls._markdown_section(text, section)
            ]
            if missing:
                errors.append(f"{name} missing sections: {', '.join(missing)}")
            citations = extract_citations(text)
            if not citations.citations:
                errors.append(f"{name} has no citation markers")
        return errors

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
    def _sanitize_deliverable_text(text: str) -> str:
        """Remove model/tool process chatter from user-facing artifacts."""
        if not text:
            return ""
        cleaned_lines: list[str] = []
        skip_fenced_tool = False
        for line in text.splitlines():
            stripped = line.strip()
            if re.search(r"<tool_call|</tool_call>|<tool_result|</tool_result>", stripped, re.I):
                continue
            if re.match(r"^```(?:json)?\s*$", stripped) and skip_fenced_tool:
                skip_fenced_tool = False
                continue
            if re.match(r"^```", stripped) and any(token in stripped.lower() for token in ("tool", "web_search")):
                skip_fenced_tool = True
                continue
            if skip_fenced_tool:
                continue
            if any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in PROCESS_LEAK_PATTERNS):
                continue
            cleaned_lines.append(line)
        return "\n".join(cleaned_lines).strip()

    @staticmethod
    def _sanitize_citations(text: str) -> str:
        """Keep final deliverables citation-compatible with SourceCatalog ids."""

        def replace(match: re.Match[str]) -> str:
            value = match.group(1).strip().lower()
            if value == "none":
                return match.group(0)
            parts = [part.strip() for part in value.split(",") if part.strip()]
            if parts and all(part.isdigit() for part in parts):
                return f"[src:{','.join(parts)}]"
            return "[src:none]"

        return re.sub(r"\[src:([^\]]+)\]", replace, text)

    @staticmethod
    def _decision_from_text(
        symbol: str,
        memo: str,
        ranking: dict[str, Any] | None = None,
        capital_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a deterministic decision contract.

        The memo can explain the decision, but it must not be the source of
        truth for action or sizing. This keeps final LLM prose from drifting
        away from the peer ranking and risk-budget policy.
        """
        action = str(ranking.get("action", "WATCH")) if ranking else "WATCH"
        target_rank = ranking.get("target_rank") if ranking else None
        target_row = {}
        if ranking:
            target_row = next(
                (
                    row
                    for row in ranking.get("ranked_companies", [])
                    if row.get("symbol") == symbol
                ),
                {},
            )
        scores = target_row.get("scores", {}) if isinstance(target_row, dict) else {}
        total_score = CompanyResearchPipeline._as_float(scores.get("total"))
        quality_score = CompanyResearchPipeline._as_float(scores.get("quality"))
        moat_score = CompanyResearchPipeline._as_float(scores.get("moat"))
        valuation_score = CompanyResearchPipeline._as_float(scores.get("valuation"))
        if action == "BUY":
            conviction = max(0.55, min(0.9, round(total_score / 100, 2))) if total_score else 0.6
        elif action == "WATCH":
            conviction = 0.45
        else:
            conviction = 0.25
        if quality_score >= 80 and moat_score >= 75:
            quality_verdict = "EXCELLENT"
        elif quality_score >= 65:
            quality_verdict = "GOOD"
        elif quality_score > 0:
            quality_verdict = "MIXED"
        else:
            quality_verdict = "UNKNOWN"
        return {
            "schema_version": COMPANY_SCHEMA_VERSION,
            "symbol": symbol,
            "action": action,
            "conviction": conviction,
            "target_rank": target_rank,
            "initial_position_pct": capital_plan.get("initial_position_pct") if capital_plan else None,
            "max_position_pct": capital_plan.get("max_position_pct") if capital_plan else None,
            "real_order_execution": False,
            "quality_verdict": quality_verdict,
            "source": "deterministic_policy",
            "policy_inputs": {
                "ranking_action": action,
                "target_rank": target_rank,
                "target_total_score": total_score,
                "quality_score": quality_score,
                "moat_score": moat_score,
                "valuation_score": valuation_score,
                "capital_plan_action": capital_plan.get("action") if capital_plan else None,
                "memo_used_for_explanation_only": bool(memo),
            },
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
