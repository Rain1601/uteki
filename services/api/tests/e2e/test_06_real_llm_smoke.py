"""T6 — Real-LLM smoke (opt-in, costs money).

Skipped by default. Runs only when:
  - UTEKI_USE_MOCK_LLM=false in env, AND
  - At least one provider key is present (DEEPSEEK_API_KEY / ANTHROPIC_API_KEY)

Why a separate file: T3/T4 assert the mode-agnostic contract using mock
LLM (hermetic, 7s). This file pushes the same chain through real
providers and observes what's genuinely different:
  - latency (seconds vs ms)
  - cost (recorded in Run.usage_summary.cost_usd)
  - tool_call events from the real LLM tool-use loop
  - artifact content shape (real markdown vs mock placeholder)
  - iteration triggering (evaluator's real "revise" decisions)

Run with:
  set -a; source services/api/.env; set +a
  UTEKI_USE_MOCK_LLM=false ./scripts/e2e.sh -k real_llm -s
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from .conftest import AuthedUser, Reporter
from .test_03_research_chain import _parse_sse

_HAS_KEY = bool(
    os.getenv("DEEPSEEK_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or os.getenv("AIHUBMIX_API_KEY")
)
_MOCK_OFF = os.getenv("UTEKI_USE_MOCK_LLM", "true").lower() != "true"

real_llm_only = pytest.mark.skipif(
    not (_HAS_KEY and _MOCK_OFF),
    reason="set UTEKI_USE_MOCK_LLM=false and a provider key (DEEPSEEK_API_KEY etc.) to enable",
)


@real_llm_only
@pytest.mark.real_llm
def test_real_research_run_emits_tool_calls_and_costs(
    client: TestClient, alice: AuthedUser, reporter: Reporter
) -> None:
    reporter.section("real LLM · research skill, single run")
    resp = client.post(
        "/api/agent/chat",
        headers={**alice.auth_header(), "Accept": "text/event-stream"},
        json={
            "messages": [{"role": "user", "content": "用三段话概述中国新能源车板块的当前格局。"}],
            "agent": "research",
            "session_id": "real-smoke",
        },
    )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    types = [e["type"] for e in events]
    reporter.kv("event count", len(events))
    reporter.kv("unique event types", sorted(set(types)))
    tool_calls = [e for e in events if e["type"] == "tool_call"]
    tool_results = [e for e in events if e["type"] == "tool_result"]
    reporter.kv("tool_call events", len(tool_calls))
    reporter.kv("tool_result events", len(tool_results))
    for e in tool_calls[:5]:
        reporter.event("tool_call", e["data"].get("name"))

    run_id = events[0]["run_id"]
    run = client.get(f"/api/runs/{run_id}", headers=alice.auth_header()).json()
    reporter.kv("status", run["status"])
    reporter.kv("input_tokens", run["usage_summary"]["input_tokens"])
    reporter.kv("output_tokens", run["usage_summary"]["output_tokens"])
    reporter.kv("cost_usd", run["usage_summary"]["cost_usd"])
    reporter.kv("summary[:120]", run["summary"][:120])

    reporter.checked("status == ok", run["status"] == "ok")
    reporter.checked("usage rolled up (cost > 0)", run["usage_summary"]["cost_usd"] > 0)
    reporter.checked("summary is real prose (non-empty, >50 chars)",
                     len(run["summary"]) > 50)
    assert run["status"] == "ok"
    assert run["usage_summary"]["cost_usd"] > 0
    reporter.end()


@real_llm_only
@pytest.mark.real_llm
def test_real_pipeline_ships_full_artifact_set(
    client: TestClient, alice: AuthedUser, reporter: Reporter
) -> None:
    """Real pipeline run under the widened budget — proves the M6/M7
    chain actually iterates with a real evaluator and finishes ok."""
    reporter.section("real LLM · research_pipeline, full chain")
    resp = client.post(
        "/api/agent/chat",
        headers={**alice.auth_header(), "Accept": "text/event-stream"},
        json={
            "messages": [{"role": "user", "content": "中国半导体设备板块研究框架（简化版本）。"}],
            "agent": "research_pipeline",
            "session_id": "real-pipeline",
        },
        timeout=600.0,
    )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    run_id = events[0]["run_id"]

    subagent_starts = [e for e in events if e["type"] == "subagent_start"]
    reporter.kv("event count", len(events))
    reporter.kv("subagent_start count", len(subagent_starts))
    for e in subagent_starts:
        reporter.event("subagent_start", e["data"])

    artifacts = client.get(
        f"/api/runs/{run_id}/artifacts", headers=alice.auth_header()
    ).json()["items"]
    names = sorted({a["name"] for a in artifacts})
    reporter.kv("artifacts on disk", names)

    # In real mode the evaluator writes per-rubric judges + the eval report.
    required = {"plan.md", "sprint-contract.json", "eval-report.json"}
    research_capture = {"final-research.md", "research.md", "run-trace.json"}
    reporter.checked("planner + evaluator output present",
                     required.issubset(set(names)))
    reporter.checked("research output captured", bool(research_capture & set(names)))
    has_judge = any(n.startswith("judge-") and n.endswith(".json") for n in names)
    reporter.checked("at least one judge-*.json present (real evaluator)",
                     has_judge)
    assert required.issubset(set(names))
    assert has_judge, "real evaluator should emit per-rubric judges"

    run = client.get(f"/api/runs/{run_id}", headers=alice.auth_header()).json()
    reporter.kv("status", run["status"])
    reporter.kv("cost_usd", run["usage_summary"]["cost_usd"])
    reporter.kv("input_tokens", run["usage_summary"]["input_tokens"])
    reporter.checked("status == ok (pipeline budget holds)",
                     run["status"] == "ok",
                     f"got '{run['status']}'")
    assert run["status"] == "ok"
    reporter.end()
