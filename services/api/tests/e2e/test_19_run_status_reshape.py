"""T19 — Run.status reshape (M1.9).

Verifies the three independent signals split out of the legacy single
``status`` field carry the right values across four representative paths:

  harness_ok + no evaluator   → ok_no_judge          (leaf research run)
  harness_ok + approve        → passed                (pipeline approve)
  harness_ok + revise         → below_quality_bar     (pipeline revise)
  harness_timeout             → failed                (regardless of evaluator)

Plus:
- Legacy ``status`` field still equals harness_status for back-compat
- API serializer surfaces all 3 new fields
- derive_overall_assessment is a pure function (unit-style coverage)

Mock-llm mode produces deterministic decisions when a pipeline runs, so
the approve/revise cases are simulated by seeding eval-report.json
directly into the run's artifact store (the canonical path that the
harness reads).
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from .conftest import AuthedUser, Reporter

# ── Unit tests for the derive helper ────────────────────────────────


def test_derive_overall_assessment_pure_mapping() -> None:
    from uteki_api.runs.models import derive_overall_assessment

    # Infrastructure failures dominate everything.
    assert derive_overall_assessment("error", None) == "failed"
    assert derive_overall_assessment("error", "approve") == "failed"
    assert derive_overall_assessment("timeout", "approve") == "failed"

    # Still in progress.
    assert derive_overall_assessment("running", None) == "running"

    # Happy paths.
    assert derive_overall_assessment("ok", "approve") == "passed"
    assert derive_overall_assessment("ok", "revise") == "below_quality_bar"
    assert derive_overall_assessment("ok", "reject") == "below_quality_bar"
    assert derive_overall_assessment("ok", None) == "ok_no_judge"


# ── Round-trip + API surface ────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_round_trip_carries_three_fields(client, reporter: Reporter) -> None:
    """Direct Run/RunStore round-trip — all three fields land on disk and
    come back identical."""
    from uteki_api.runs import Run, default_run_store

    rid = "t19-roundtrip"
    await default_run_store.create(
        Run(
            id=rid, user_id="system", skill="research",
            triggered_by="user", started_at=time.time(),
            harness_status="ok",
            evaluator_decision="revise",
            overall_assessment="below_quality_bar",
        )
    )
    await default_run_store.finish(rid, "ok", "round-trip test")

    fetched = await default_run_store.get(rid)
    reporter.kv("harness_status", fetched.harness_status)
    reporter.kv("evaluator_decision", fetched.evaluator_decision)
    reporter.kv("overall_assessment", fetched.overall_assessment)
    assert fetched.harness_status == "ok"
    # finish() also writes status="ok" to legacy field; the explicit
    # evaluator_decision/overall_assessment we set on create survive.
    assert fetched.evaluator_decision == "revise"
    assert fetched.overall_assessment == "below_quality_bar"
    # Legacy alias still works.
    assert fetched.status == "ok"
    reporter.end()


def test_api_runs_endpoint_surfaces_three_fields(
    client, alice: AuthedUser, reporter: Reporter
) -> None:
    """Hit /api/agent/chat then GET /api/runs/{id}; assert the response
    JSON includes all three new fields."""
    from fastapi.testclient import TestClient
    c: TestClient = client

    reporter.section("trigger a mock research run")
    resp = c.post(
        "/api/agent/chat",
        headers={**alice.auth_header(), "Accept": "text/event-stream"},
        json={
            "messages": [{"role": "user", "content": "T19 chat"}],
            "agent": "research",
            "session_id": "t19",
        },
    )
    assert resp.status_code == 200
    # SSE: first data: line is run_start with the id.
    run_id = None
    for line in resp.text.replace("\r\n", "\n").split("\n"):
        if line.startswith("data:"):
            obj = json.loads(line[5:].strip())
            run_id = obj.get("run_id")
            break
    assert run_id, "no run_id in SSE stream"

    reporter.section(f"GET /api/runs/{run_id} surfaces new fields")
    r = c.get(f"/api/runs/{run_id}", headers=alice.auth_header())
    assert r.status_code == 200
    body = r.json()
    for f in ("status", "harness_status", "evaluator_decision", "overall_assessment"):
        reporter.kv(f, body.get(f))
        assert f in body, f"/api/runs missing field {f!r}"
    # A vanilla research run goes harness_ok + no evaluator → ok_no_judge.
    assert body["harness_status"] == "ok"
    assert body["evaluator_decision"] is None
    assert body["overall_assessment"] == "ok_no_judge"
    # Legacy alias still in sync.
    assert body["status"] == body["harness_status"]
    reporter.end()


# ── Harness populates fields from eval-report.json ──────────────────


@pytest.mark.asyncio
async def test_harness_extracts_evaluator_decision_from_artifact(
    client, reporter: Reporter
) -> None:
    """Seed an eval-report.json + run a no-op skill; harness should pull
    'decision' off it into Run.evaluator_decision and derive the
    overall_assessment."""
    from collections.abc import AsyncIterator

    from uteki_api.agents.base import BaseAgent
    from uteki_api.agents.harness import AgentHarness
    from uteki_api.runs import default_run_store
    from uteki_api.schemas.chat import ChatMessage
    from uteki_api.schemas.events import AgentEvent

    class _FakePipelineSkill(BaseAgent):
        """No-op skill that writes a fake eval-report.json into the run's
        artifacts before yielding done. Mirrors what ResearchPipeline does
        in real runs without dragging in the whole pipeline graph."""

        name = "_t19_fake_pipeline"

        def __init__(self, decision: str) -> None:
            self.decision = decision

        async def run(  # type: ignore[override]
            self, messages: list[ChatMessage]
        ) -> AsyncIterator[AgentEvent]:
            yield AgentEvent(type="step_start", data={"step": 1})
            # Write eval-report.json via the harness-injected facade.
            await self.artifacts.write(  # type: ignore[union-attr]
                name="eval-report.json",
                content=json.dumps({"decision": self.decision, "verdicts": {}}),
                kind="json",
                description="t19 seed",
            )
            yield AgentEvent(type="delta", data={"text": "noop"})

    async def _run_with(decision: str) -> str:
        harness = AgentHarness(
            skill=_FakePipelineSkill(decision),
            user_id="system",
            run_store=default_run_store,
        )
        last_run_id = None
        async for ev in harness.run([ChatMessage(role="user", content="x")]):
            if ev.type == "run_start":
                last_run_id = ev.run_id
        assert last_run_id is not None
        return last_run_id

    reporter.section("decision='approve' → overall_assessment='passed'")
    rid = await _run_with("approve")
    run = await default_run_store.get(rid)
    reporter.kv("evaluator_decision", run.evaluator_decision)
    reporter.kv("overall_assessment", run.overall_assessment)
    assert run.harness_status == "ok"
    assert run.evaluator_decision == "approve"
    assert run.overall_assessment == "passed"

    reporter.section("decision='revise' → overall_assessment='below_quality_bar'")
    rid = await _run_with("revise")
    run = await default_run_store.get(rid)
    assert run.evaluator_decision == "revise"
    assert run.overall_assessment == "below_quality_bar"

    reporter.section("decision='reject' → overall_assessment='below_quality_bar'")
    rid = await _run_with("reject")
    run = await default_run_store.get(rid)
    assert run.evaluator_decision == "reject"
    assert run.overall_assessment == "below_quality_bar"

    reporter.end()


# Keep asyncio import live in case the framework prunes it.
_ = asyncio
_ = Path
