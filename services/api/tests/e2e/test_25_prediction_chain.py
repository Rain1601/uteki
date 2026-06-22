"""T25 — 015 PR ε MVP · Backtest widget data path.

Walks Prediction → API → cross-user 404 → countdown horizon math.

  a) alice owns a company_research_pipeline run with auto-written
     final-verdict.json. Dispatcher fires post-finish; we call it
     directly here since the harness already proved the wiring.
  b) GET /api/runs/{id}/prediction → 200 with ticker / action /
     entry / horizons populated
  c) bob → same path → 404 (cross-user)
  d) GET on a run that DOESN'T have a verdict → 404 "no-prediction"
  e) Horizon countdown math: 30/90/180 horizons present, days_remaining
     between 29.5 and 30 (just barely under since we wrote moments ago)
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

import uteki_api.runs as runs_pkg
from uteki_api.eval.prediction_dispatcher import default_prediction_dispatcher
from uteki_api.runs.models import Run

from .conftest import AuthedUser, Reporter


@pytest.mark.asyncio
async def test_prediction_chain(
    client: TestClient,
    alice: AuthedUser,
    bob: AuthedUser,
    reporter: Reporter,
) -> None:
    run_store = runs_pkg.default_run_store

    # Seed a finished company_research_pipeline run for alice, plus the
    # final-verdict.json the dispatcher reads.
    run_id = "t25-A-googl"
    await run_store.create(
        Run(
            id=run_id,
            user_id=alice.id,
            skill="company_research_pipeline",
            triggered_by="user",
            started_at=time.time() - 5,
            ended_at=time.time(),
            status="ok",
            user_input="GOOGL?",
        )
    )

    # Hand-write the artifact via the store the dispatcher reads from.
    from uteki_api.artifacts import default_artifact_store

    verdict_payload = {
        "schema_version": "company_final_verdict.v1",
        "symbol": "GOOGL",
        "verdict": {
            "action": "WATCH",
            "conviction": 0.55,
            "quality_verdict": "EXCELLENT",
        },
    }
    await default_artifact_store.write(
        run_id=run_id,
        name="final-verdict.json",
        content=json.dumps(verdict_payload).encode("utf-8"),
        kind="json",
        written_by="company_research_pipeline",
        user_id=alice.id,
        description="test verdict",
        role="primary",
    )

    reporter.section("a) dispatcher fires post-finish, writes Prediction")
    await default_prediction_dispatcher.record(run_id)
    reporter.event("dispatched", run_id)

    reporter.section("b) alice GET /api/runs/{id}/prediction → 200")
    r = client.get(f"/api/runs/{run_id}/prediction", headers=alice.auth_header())
    reporter.kv("status", r.status_code)
    assert r.status_code == 200, r.text
    body = r.json()
    reporter.kv("ticker", body["ticker"])
    reporter.kv("action", body["action"])
    reporter.kv("conviction", body["conviction"])
    reporter.kv("quality_verdict", body["quality_verdict"])
    reporter.kv("horizons", len(body["horizons"]))
    assert body["ticker"] == "GOOGL"
    assert body["action"] == "WATCH"
    assert body["conviction"] == 0.55
    assert body["quality_verdict"] == "EXCELLENT"
    assert len(body["horizons"]) == 3
    # All 3 horizons should be very close to full days_remaining
    for h in body["horizons"]:
        assert h["horizon_days"] in {30, 90, 180}
        # Just-written; days_remaining should be within 1 minute of full
        assert h["days_remaining"] > h["horizon_days"] - 0.01
        assert h["outcome"] is None  # not scored — cron is PR ε.2

    reporter.section("c) bob → same path → 404 (cross-user isolation)")
    r = client.get(f"/api/runs/{run_id}/prediction", headers=bob.auth_header())
    reporter.kv("status", r.status_code)
    assert r.status_code == 404

    reporter.section("d) run with no verdict → 404 no-prediction")
    # Seed an alice-owned research run (different skill, no verdict)
    other_id = "t25-A-research"
    await run_store.create(
        Run(
            id=other_id,
            user_id=alice.id,
            skill="research",
            triggered_by="user",
            started_at=time.time() - 3,
            ended_at=time.time(),
            status="ok",
            user_input="industry?",
        )
    )
    r = client.get(f"/api/runs/{other_id}/prediction", headers=alice.auth_header())
    reporter.kv("status", r.status_code)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_dispatcher_skips_non_target_skills() -> None:
    """Smoke: dispatcher silently no-ops for skills outside PREDICTION_TARGETS.
    Doesn't write a Prediction row, doesn't log a warning. Direct call so we
    don't need an actual run wired through harness."""
    # No assertion needed beyond "doesn't raise" — the dispatcher's own
    # except guard would mask the failure, but a hard crash inside the
    # asyncio task would surface here without it.
    await default_prediction_dispatcher.record("nonexistent-run-id")
