"""Unit tests for company research pipeline helpers."""

from __future__ import annotations

from types import SimpleNamespace

from uteki_api.provenance import SourceCatalog
from uteki_api.skills.company import CompanyResearchPipeline


def test_extract_symbols_user_supplied_peers() -> None:
    symbol, peers = CompanyResearchPipeline._extract_symbols(
        "分析 AAPL，并对比 MSFT, GOOGL, META，给出排序和仓位建议。"
    )

    assert symbol == "AAPL"
    assert peers == ["MSFT", "GOOGL", "META"]


def test_extract_symbols_auto_fills_us_peers() -> None:
    symbol, peers = CompanyResearchPipeline._extract_symbols("分析 NVDA 的长期投资价值。")

    assert symbol == "NVDA"
    assert peers == ["AMD", "AVGO", "INTC"]


def test_sanitize_citations_replaces_non_catalog_refs() -> None:
    text = (
        "valid [src:1], multi [src:1, 2,3], spaced [src: 4 ], "
        "none [src:none], invalid [src:quote], bad [src:资金管理计划]"
    )

    assert CompanyResearchPipeline._sanitize_citations(text) == (
        "valid [src:1], multi [src:1,2,3], spaced [src:4], "
        "none [src:none], invalid [src:none], bad [src:none]"
    )


def test_sanitize_deliverable_text_removes_process_chatter() -> None:
    text = "## Verdict\nBUY [src:1]\n**思考**: I need web_search.\n<tool_call>{}</tool_call>"

    assert CompanyResearchPipeline._sanitize_deliverable_text(text) == "## Verdict\nBUY [src:1]"


def test_decision_contract_ignores_freeform_memo_action() -> None:
    decision = CompanyResearchPipeline._decision_from_text(
        "AAPL",
        "The memo says BUY, but ranking contract controls.",
        ranking={
            "action": "AVOID",
            "target_rank": 4,
            "ranked_companies": [
                {"symbol": "AAPL", "scores": {"total": 42, "quality": 55, "moat": 50, "valuation": 40}}
            ],
        },
        capital_plan={"action": "AVOID", "initial_position_pct": 0.0, "max_position_pct": 0.0},
    )

    assert decision["action"] == "AVOID"
    assert decision["source"] == "deterministic_policy"
    assert decision["policy_inputs"]["memo_used_for_explanation_only"] is True


def test_source_quality_and_claim_audit_surface_core_gaps() -> None:
    agent = CompanyResearchPipeline()
    catalog = SourceCatalog(run_id="r1")
    catalog.add(
        {
            "key": "financials:AAPL:FY2025",
            "value": {"revenue": 100},
            "source_type": "financials",
            "source_url": "https://finance.yahoo.com/quote/AAPL/financials",
            "publisher": "Yahoo Finance",
            "fetched_at": "2026-05-31T00:00:00+00:00",
            "confidence": "high",
        }
    )
    catalog.add(
        {
            "key": "web_search:AAPL:1",
            "value": {"snippet": "AAPL risk"},
            "source_type": "web_search",
            "source_url": "https://example.com/search/1",
            "publisher": "mock-web-search",
            "fetched_at": "2026-05-31T00:00:00+00:00",
            "confidence": "low",
        }
    )
    agent.sources = SimpleNamespace(catalog=catalog, valid_ids=catalog.valid_ids)

    quality = agent._build_source_quality()
    claims = agent._build_claim_audit(
        symbol="AAPL",
        gate_outputs=[
            {
                "name": "business_analysis",
                "display_name": "业务解析",
                "text": (
                    "# Gate 1\n## Key findings\n- Revenue reached 100 [src:1]\n"
                    "## Analysis\nOK [src:1]\n## Gate conclusion\nQuality is good [src:1]"
                ),
            }
        ],
        memo=(
            "# AAPL Investment Memo\n## Verdict\nBUY with 5% position [src:none]\n"
            "## Capital Plan\nMax 10% [src:1]\n## Key Risks\nSearch risk [src:2]"
        ),
        source_quality=quality,
    )

    assert quality["metrics"]["tier_1_count"] == 1
    assert quality["metrics"]["tier_4_count"] == 1
    assert claims["summary"]["unsupported_core_claim_count"] == 1
    assert claims["summary"]["weak_core_claim_count"] == 1
    assert claims["summary"]["unbacked_number_claim_count"] == 1
