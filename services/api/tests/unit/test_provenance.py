from __future__ import annotations

import json
from collections.abc import AsyncIterator

from uteki_api.agents.base import BaseAgent
from uteki_api.agents.harness import AgentHarness
from uteki_api.artifacts.store import LocalFileArtifactStore
from uteki_api.memory.in_memory import InMemoryStore
from uteki_api.provenance import SourceCatalog, extract_citations
from uteki_api.runs.store import InMemoryRunStore
from uteki_api.schemas.chat import ChatMessage
from uteki_api.schemas.events import AgentEvent
from uteki_api.skills.evaluator.verifiers import citation_ids_exist
from uteki_api.tools.base import Tool, ToolRegistry, ToolResult


def test_source_catalog_dedupes_url_key_and_renders_llm_block() -> None:
    catalog = SourceCatalog(run_id="run1")
    first = catalog.add(
        {
            "key": "revenue_2024",
            "value": 123.4,
            "source_type": "financials",
            "source_url": "https://example.com/report",
            "publisher": "Example",
            "fetched_at": "2026-05-31T00:00:00+00:00",
            "confidence": "high",
            "excerpt": "Revenue was 123.4.",
        }
    )
    second = catalog.add(
        {
            "key": "revenue_2024",
            "value": 123.4,
            "source_type": "financials",
            "source_url": "https://example.com/report",
            "publisher": "Example",
            "fetched_at": "2026-05-31T00:01:00+00:00",
        }
    )

    assert first == 1
    assert second == first
    assert len(catalog) == 1
    assert "[src:1]" in catalog.to_llm_block()
    assert catalog.to_dict()["items"]["1"]["key"] == "revenue_2024"


def test_source_catalog_dedupes_key_value_without_url() -> None:
    catalog = SourceCatalog(run_id="run1")
    payload = {
        "key": "mock_quote:AAPL",
        "value": {"symbol": "AAPL", "price": 123.45},
        "source_type": "tool_result",
        "publisher": "mock",
        "confidence": "low",
    }

    first = catalog.add({**payload, "fetched_at": "2026-05-31T00:00:00+00:00"})
    second = catalog.add({**payload, "fetched_at": "2026-05-31T00:01:00+00:00"})

    assert first == second
    assert len(catalog) == 1


def test_extract_citations_detects_orphans_and_cleans_text() -> None:
    text = "Revenue grew 12% [src:1, 99]. Margin is inferred [src:none]."
    extracted = extract_citations(text, valid_ids={1, 2})

    assert extracted.all_cited_ids() == {1}
    assert extracted.orphan_ids == [99]
    assert extracted.no_source_count == 1
    assert extracted.cleaned({1, 2}) == "Revenue grew 12% [src:1]. Margin is inferred [src:none]."


def test_extract_citations_accepts_bare_ledger_markers() -> None:
    text = "Revenue grew [1][2]. Risk was stale [99]."
    extracted = extract_citations(text, valid_ids={1, 2})

    assert extracted.all_cited_ids() == {1, 2}
    assert extracted.orphan_ids == [99]
    assert extracted.cleaned({1, 2}) == "Revenue grew [src:1][src:2]. Risk was stale [src:none]."


async def test_citation_ids_exist_verifier() -> None:
    catalog = {
        "run_id": "r1",
        "items": {
            "1": {"id": 1},
            "2": {"id": 2},
        },
    }

    ok, notes = await citation_ids_exist("A [src:1] B [src:none]", catalog)
    assert ok is True
    assert "citation marker" in notes

    ok, notes = await citation_ids_exist("A [src:9]", catalog)
    assert ok is False
    assert "orphan" in notes


class SourceTool(Tool):
    name = "source_tool"
    description = "returns one sourced datum"
    parameters = {"type": "object", "properties": {}}

    async def run(self, **kwargs) -> ToolResult:  # noqa: ANN003
        return ToolResult(
            ok=True,
            summary="one result",
            data={"answer": 42},
            sources=[
                {
                    "key": "answer",
                    "value": 42,
                    "source_type": "tool_result",
                    "publisher": "unit-test",
                    "confidence": "high",
                    "excerpt": "The answer is 42.",
                }
            ],
        )


class HighRiskTool(Tool):
    name = "place_order"
    description = "places an order"
    parameters = {"type": "object", "properties": {}}
    risk_level = "high"

    def __init__(self) -> None:
        self.executed = False

    async def run(self, **kwargs) -> ToolResult:  # noqa: ANN003
        self.executed = True
        return ToolResult(ok=True, summary="executed")


class SourceSkill(BaseAgent):
    name = "source_skill"

    async def run(self, messages: list[ChatMessage]) -> AsyncIterator[AgentEvent]:
        yield AgentEvent(type="tool_call", data={"name": "source_tool", "args": {}})
        yield AgentEvent(type="delta", data={"text": "Answer is 42 [src:1]."})


class HighRiskSkill(BaseAgent):
    name = "high_risk_skill"

    async def run(self, messages: list[ChatMessage]) -> AsyncIterator[AgentEvent]:
        yield AgentEvent(type="tool_call", data={"name": "place_order", "args": {"symbol": "AAPL"}})
        yield AgentEvent(type="delta", data={"text": "order requested"})


async def test_harness_registers_tool_sources_and_writes_catalog(
    tmp_path,
    monkeypatch,
) -> None:
    import uteki_api.agents.harness as harness_mod

    monkeypatch.setattr(
        harness_mod,
        "default_artifact_store",
        LocalFileArtifactStore(tmp_path / "artifacts"),
    )
    registry = ToolRegistry()
    registry.register(SourceTool())
    run_store = InMemoryRunStore()

    harness = AgentHarness(
        SourceSkill(),
        memory=InMemoryStore(),
        tools=registry,
        run_store=run_store,
        user_id="u1",
    )

    events = [
        ev
        async for ev in harness.run(
            [ChatMessage(role="user", content="run source skill")],
            session_id="s1",
        )
    ]

    run_id = events[0].run_id
    assert run_id is not None
    artifact_events = [
        ev
        for ev in events
        if ev.type == "artifact_written" and ev.data.get("name") == "source-catalog.json"
    ]
    assert artifact_events

    run = await run_store.get(run_id)
    tool_results = [ev for ev in run.events if ev.type == "tool_result"]
    assert tool_results[0].data["preview"]["_source_ids"] == [1]

    meta, body = await harness_mod.default_artifact_store.read(
        run_id,
        "source-catalog.json",
        "u1",
    )
    assert meta.kind == "json"
    payload = json.loads(body.decode("utf-8"))
    assert payload["items"]["1"]["key"] == "answer"


async def test_harness_writes_primary_final_report_artifact(
    tmp_path,
    monkeypatch,
) -> None:
    import uteki_api.agents.harness as harness_mod

    monkeypatch.setattr(
        harness_mod,
        "default_artifact_store",
        LocalFileArtifactStore(tmp_path / "artifacts"),
    )
    harness = AgentHarness(
        SourceSkill(),
        memory=InMemoryStore(),
        tools=ToolRegistry(),
        run_store=InMemoryRunStore(),
        user_id="u1",
    )

    events = [
        ev
        async for ev in harness.run(
            [ChatMessage(role="user", content="write final report")],
            session_id="s1",
        )
    ]

    run_id = events[0].run_id
    assert run_id is not None
    final_events = [
        ev
        for ev in events
        if ev.type == "artifact_written" and ev.data.get("name") == "final-report.md"
    ]
    assert final_events
    meta, body = await harness_mod.default_artifact_store.read(run_id, "final-report.md", "u1")
    assert meta.role == "primary"
    assert meta.display_name == "Final report"
    assert "Answer is 42" in body.decode("utf-8")

    diag_meta, diag_body = await harness_mod.default_artifact_store.read(
        run_id,
        "trace-diagnosis.json",
        "u1",
    )
    assert diag_meta.role == "diagnosis"
    diagnosis = json.loads(diag_body.decode("utf-8"))
    assert diagnosis["event_counts"]["delta"] == 1
    assert diagnosis["artifacts"] == ["final-report.md"]


async def test_harness_blocks_high_risk_tools_without_execution() -> None:
    tool = HighRiskTool()
    registry = ToolRegistry()
    registry.register(tool)
    harness = AgentHarness(
        HighRiskSkill(),
        memory=InMemoryStore(),
        tools=registry,
        run_store=InMemoryRunStore(),
        user_id="u1",
    )

    events = [
        ev
        async for ev in harness.run(
            [ChatMessage(role="user", content="buy AAPL")],
            session_id="s1",
        )
    ]

    assert tool.executed is False
    reviews = [ev for ev in events if ev.type == "await_review"]
    assert reviews
    assert reviews[0].data["checkpoint"] == "high_risk_tool"
    results = [ev for ev in events if ev.type == "tool_result"]
    assert results[0].data["ok"] is False
    assert results[0].data["error"] == "high_risk_tool_requires_review"
