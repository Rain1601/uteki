"""Unit tests for company research pipeline helpers."""

from __future__ import annotations

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
    text = "valid [src:1], none [src:none], invalid [src:quote], bad [src:资金管理计划]"

    assert CompanyResearchPipeline._sanitize_citations(text) == (
        "valid [src:1], none [src:none], invalid [src:none], bad [src:none]"
    )
