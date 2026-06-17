"""T23 — Review-mode annotation (013 δ.1).

Adds the review-mode counterpart to T21 (blind mode). Verifies:

  a) GET /feedback?mode=review on an unrated run REVEALS the auto-score
     immediately (annotator declared intent, no anchoring guard needed).
  b) GET /feedback (default mode=blind) on the same unrated run still
     MASKS the score — the calibration default holds.
  c) POST {rating, rating_mode:"review"} stores the row with
     rating_mode='review'; response carries it back.
  d) After a review-mode submission, GET /feedback echoes mode='review'
     and keeps the score visible (already labelled).
  e) Re-POST {rating_mode:"blind"} on the same row UPSERTS the mode
     field — a row can switch annotation mode on edit.

These are pure annotation-surface tests; they don't drive the harness.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import uteki_api.runs as runs_pkg
from uteki_api.runs.models import Run

from .conftest import AuthedUser, Reporter


@pytest.mark.asyncio
async def test_run_feedback_review_mode(
    client: TestClient,
    alice: AuthedUser,
    reporter: Reporter,
) -> None:
    # Seed a run with auto-score already written (PR β/γ dispatcher result).
    run_id = "t23-A"
    await runs_pkg.default_run_store.create(
        Run(
            id=run_id,
            user_id=alice.id,
            skill="research",
            triggered_by="user",
            started_at=time.time(),
            user_input="please research aapl",
            summary="my final take",
            auto_score=3.7,
            score_breakdown={"outcome": 8.0, "cost": 3.0},
        )
    )

    reporter.section("a) GET /feedback?mode=review → reveals score on unrated run")
    r = client.get(
        f"/api/runs/{run_id}/feedback?mode=review",
        headers=alice.auth_header(),
    )
    body = r.json()
    reporter.kv("status", r.status_code)
    reporter.kv("rating_mode", body["rating_mode"])
    reporter.kv("auto_score", body["auto_score"])
    reporter.checked("200", r.status_code == 200)
    reporter.checked("rating empty (not labelled yet)", body["rating"] == "")
    reporter.checked("mode='review' echoed", body["rating_mode"] == "review")
    reporter.checked("auto_score visible (3.7)", body["auto_score"] == 3.7)
    reporter.checked(
        "breakdown carried",
        body["score_breakdown"] == {"outcome": 8.0, "cost": 3.0},
    )
    assert body["auto_score"] == 3.7
    assert body["rating_mode"] == "review"

    reporter.section("b) GET /feedback (default blind) → masks score on same unrated run")
    r = client.get(f"/api/runs/{run_id}/feedback", headers=alice.auth_header())
    body = r.json()
    reporter.kv("rating_mode", body["rating_mode"])
    reporter.kv("auto_score", body["auto_score"])
    reporter.checked("mode='blind' default", body["rating_mode"] == "blind")
    reporter.checked("auto_score masked", body["auto_score"] is None)
    reporter.checked("breakdown masked", body["score_breakdown"] is None)
    assert body["auto_score"] is None
    assert body["rating_mode"] == "blind"

    reporter.section("c) POST {rating:up, mode:review} → stores mode")
    r = client.post(
        f"/api/runs/{run_id}/feedback",
        headers=alice.auth_header(),
        json={"rating": "up", "notes": "judge looks right", "rating_mode": "review"},
    )
    body = r.json()
    reporter.kv("status", r.status_code)
    reporter.kv("rating_mode", body["rating_mode"])
    reporter.kv("auto_score", body["auto_score"])
    reporter.checked("200", r.status_code == 200)
    reporter.checked("rating_mode='review'", body["rating_mode"] == "review")
    reporter.checked("auto_score visible", body["auto_score"] == 3.7)
    assert body["rating_mode"] == "review"

    reporter.section("d) GET /feedback after review-mode submission echoes mode + score")
    r = client.get(f"/api/runs/{run_id}/feedback", headers=alice.auth_header())
    body = r.json()
    reporter.kv("rating_mode", body["rating_mode"])
    reporter.kv("auto_score", body["auto_score"])
    # Even without the ?mode= param, the stored row's mode wins.
    reporter.checked("mode from row='review'", body["rating_mode"] == "review")
    reporter.checked("auto_score visible", body["auto_score"] == 3.7)
    assert body["rating_mode"] == "review"
    assert body["auto_score"] == 3.7

    reporter.section("e) re-POST switching to blind mode → row updates in place")
    r = client.post(
        f"/api/runs/{run_id}/feedback",
        headers=alice.auth_header(),
        json={"rating": "down", "notes": "actually no", "rating_mode": "blind"},
    )
    body = r.json()
    reporter.kv("rating_mode", body["rating_mode"])
    reporter.kv("rating", body["rating"])
    reporter.checked("rating switched", body["rating"] == "down")
    reporter.checked("mode switched to blind", body["rating_mode"] == "blind")
    # Auto-score still revealed — the row is labelled now, so the
    # anchoring concern is moot.
    reporter.checked("auto_score still visible (labelled)", body["auto_score"] == 3.7)
    assert body["rating_mode"] == "blind"

    reporter.end()
