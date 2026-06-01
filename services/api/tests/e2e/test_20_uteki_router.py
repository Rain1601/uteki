"""T20 — Phase B.1 uteki router skill (intent dispatch).

Verifies the main agent's two paths:

  intent="direct"  — router answers inline (no subagent_start)
  intent="research"/"company"/"earnings" — wraps a registered sub-skill
                                            in subagent_start/_end and
                                            forwards its events

Mock-llm mode uses the keyword heuristic classifier, which is exactly
what we want for hermetic E2E: deterministic routing, no real LLM call.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from .conftest import AuthedUser, Reporter


def _parse_sse(body: str) -> list[dict[str, Any]]:
    import contextlib
    events: list[dict[str, Any]] = []
    normalised = body.replace("\r\n", "\n")
    for raw in re.split(r"\n\n+", normalised):
        data_lines = [line[5:].strip() for line in raw.split("\n") if line.startswith("data:")]
        if not data_lines:
            continue
        with contextlib.suppress(json.JSONDecodeError):
            events.append(json.loads("".join(data_lines)))
    return events


def _post_uteki(client: TestClient, alice: AuthedUser, message: str) -> list[dict]:
    resp = client.post(
        "/api/agent/chat",
        headers={**alice.auth_header(), "Accept": "text/event-stream"},
        json={
            "messages": [{"role": "user", "content": message}],
            "agent": "uteki",
            "session_id": "t20",
        },
    )
    assert resp.status_code == 200, f"chat failed: {resp.text}"
    return _parse_sse(resp.text)


# ── direct path ──────────────────────────────────────────────────────


def test_uteki_router_direct_answers_short_question(
    client: TestClient, alice: AuthedUser, reporter: Reporter
) -> None:
    """Short conceptual question → intent='direct' → no subagent spawn."""
    reporter.section("POST /api/agent/chat agent=uteki, short Q")
    events = _post_uteki(client, alice, "什么是 PE-TTM？")
    types = [e["type"] for e in events]
    reporter.kv("event types", types[:10])
    reporter.kv("total events", len(events))

    # router must emit a plan describing the chosen intent
    plan = next((e for e in events if e["type"] == "plan"), None)
    reporter.kv("plan.intent", plan["data"].get("intent") if plan else None)
    assert plan is not None, "router must yield a plan event"
    assert plan["data"]["intent"] == "direct", (
        f"expected direct intent for '什么是 PE-TTM？'; got {plan['data']['intent']}"
    )

    # direct path = no subagent_start
    assert all(e["type"] != "subagent_start" for e in events), (
        "direct intent must not spawn a subagent; trace="
        f"{[e['type'] for e in events]}"
    )
    # but must produce at least one delta (the answer)
    assert any(e["type"] == "delta" for e in events), "direct path must yield delta"
    reporter.end()


# ── delegated paths ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "message,expected_intent,expected_subskill",
    [
        # B.1 — original coverage
        ("分析 NVDA 当前估值", "company", "company_research_pipeline"),
        ("中国半导体设备板块研究框架", "research", "research"),
        # B.4 — extended coverage for refined router (B.3 prompt updates)
        # "怎么看" must reach company even without "分析" verb
        ("NVDA 怎么看", "company", "company_research_pipeline"),
        # Two tickers must go to research, NOT company, regardless of verb
        ("对比 NVDA 和 AMD 的估值", "research", "research"),
        # Explicit pipeline ask
        (
            "我想要一份完整 pipeline 的板块研报",
            "research_pipeline",
            "research_pipeline",
        ),
    ],
    ids=[
        "company-NVDA-estimation",
        "research-sector",
        "company-zenmeyikan",
        "research-multi-ticker-compare",
        "pipeline-explicit",
    ],
)
def test_uteki_router_dispatches_to_subskill(
    client: TestClient, alice: AuthedUser, reporter: Reporter,
    message: str, expected_intent: str, expected_subskill: str,
) -> None:
    """Ticker + analysis verb routes to company; sector keyword routes to
    research. Both should wrap the sub-skill in subagent_start/_end."""
    reporter.section(f"POST /api/agent/chat agent=uteki, msg={message!r}")
    events = _post_uteki(client, alice, message)
    types = [e["type"] for e in events]
    reporter.kv("event type counts", {t: types.count(t) for t in set(types)})

    plan = next((e for e in events if e["type"] == "plan"), None)
    reporter.kv("plan.intent", plan["data"].get("intent") if plan else None)
    reporter.kv("plan.reasoning", plan["data"].get("reasoning") if plan else None)
    assert plan is not None
    assert plan["data"]["intent"] == expected_intent

    # subagent envelope present + correct sub-skill name
    starts = [e for e in events if e["type"] == "subagent_start"]
    ends = [e for e in events if e["type"] == "subagent_end"]
    reporter.kv("subagent_start count", len(starts))
    reporter.kv("subagent_end count", len(ends))
    assert len(starts) >= 1, f"dispatch path must yield subagent_start; types={types}"
    assert starts[0]["data"]["name"] == expected_subskill
    assert len(ends) >= 1

    # ensure the sub-skill actually ran (at least one delta event between
    # start and end — the sub-skill's output)
    found_delta = any(e["type"] == "delta" for e in events)
    assert found_delta, "sub-skill should produce delta output"

    reporter.end()


# ── classification edge cases ────────────────────────────────────────


def test_uteki_router_heuristic_classifier_unit() -> None:
    """Direct unit coverage of the heuristic classifier so the parametric
    test above isn't the only regression net.

    B.3 — extended with edge-case rows that the refined classifier must
    handle: multi-ticker comparison, "怎么看" without "分析", bare
    "AAPL 财报" without a pasted transcript (still company, not earnings).
    """
    from uteki_api.skills.uteki import UtekiRouter

    cases = [
        # ── concept / market quick-check ──
        ("什么是 ROE？", "direct"),
        ("市场今天怎么样？", "direct"),
        ("PE 和 PB 哪个更适合估值？", "direct"),   # acronym filter — no real ticker
        ("上证今天怎么样", "direct"),
        # ── single ticker → company ──
        ("分析 NVDA", "company"),
        ("评估 AAPL 估值", "company"),
        ("NVDA 怎么看", "company"),              # B.3 — "怎么看" alone now a verb
        ("TSLA 投资价值", "company"),
        # B.3 — bare "AAPL 财报怎么看" has no pasted transcript →
        # must go to company, NOT earnings.
        ("AAPL 财报怎么看", "company"),
        # ── sector / multi-ticker → research ──
        ("半导体设备板块研究框架", "research"),
        ("AI 基建赛道", "research"),
        ("对比 NVDA 和 AMD", "research"),         # B.3 — multi-ticker → research
        ("NVDA vs AMD 谁的护城河更深", "research"),  # vs disambiguator
        # ── explicit pipeline ask → research_pipeline ──
        ("请用 research_pipeline 出一份完整 pipeline 研报", "research_pipeline"),
        ("我想要一份完整 pipeline 的板块研报", "research_pipeline"),
        # ── earnings: keyword + concrete financial signal ──
        (
            "NVDA Q3 财报电话会要点：Revenue $35.1B 毛利率 75%，"
            "管理层指引 Q4 强劲，CFO 提到 Blackwell 产能爬坡顺利。"
            "请帮我点评关键变化和潜在影响。",
            "earnings",
        ),
    ]
    for msg, expected in cases:
        got = UtekiRouter._heuristic_classify(msg)
        assert got["intent"] == expected, (
            f"classify({msg!r}) → {got['intent']!r}, expected {expected!r}"
        )
        # Reasoning must be a non-empty string (operators read it in the trace)
        assert got["reasoning"], f"classify({msg!r}) returned empty reasoning"


def test_uteki_router_company_dispatch_produces_deliverable(
    client: TestClient, alice: AuthedUser, reporter: Reporter
) -> None:
    """B.4 — full loop check: 'NVDA 怎么看' → company pipeline must not
    only emit subagent_start/_end, but also actually run far enough to
    produce delta content AND a usage/done signal. Catches the silent
    failure where dispatch fires but the sub-skill bails immediately.
    """
    reporter.section("POST /api/agent/chat — 'NVDA 怎么看' end-to-end")
    events = _post_uteki(client, alice, "NVDA 怎么看")
    types = [e["type"] for e in events]
    counts = {t: types.count(t) for t in set(types)}
    reporter.kv("event counts", counts)

    plan = next((e for e in events if e["type"] == "plan"), None)
    assert plan is not None
    assert plan["data"]["intent"] == "company", plan["data"]
    reporter.kv("plan.intent", "company")

    # Envelope present
    starts = [e for e in events if e["type"] == "subagent_start"]
    ends = [e for e in events if e["type"] == "subagent_end"]
    assert starts and starts[0]["data"]["name"] == "company_research_pipeline"
    assert ends, "subagent_end must close the envelope"

    # Sub-skill actually emitted deltas between start and end (i.e. it
    # ran past its prelude — not an immediate bail).
    start_idx = events.index(starts[0])
    end_idx = events.index(ends[-1])
    deltas_inside = [
        e for e in events[start_idx + 1 : end_idx] if e["type"] == "delta"
    ]
    reporter.kv("deltas inside subagent", len(deltas_inside))
    assert deltas_inside, "company pipeline must yield at least one delta"

    # Concatenated delta text must be non-trivial (not just whitespace)
    body = "".join(str(e["data"].get("text") or "") for e in deltas_inside)
    reporter.kv("body length", len(body))
    assert len(body.strip()) > 20, f"sub-skill output too short: {body!r}"

    # The full run must terminate with a `done` event (harness contract)
    assert any(e["type"] == "done" for e in events), (
        "harness must emit a final done event"
    )
    reporter.end()


def test_uteki_router_in_skill_registry(client: TestClient, alice: AuthedUser) -> None:
    """uteki is registered + discoverable via /api/agents."""
    resp = client.get("/api/agents", headers=alice.auth_header())
    assert resp.status_code == 200, resp.text
    names = {a["name"] for a in resp.json().get("items", [])}
    assert "uteki" in names, f"uteki not in registry; got {sorted(names)}"
