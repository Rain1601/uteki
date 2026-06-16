"""T21 — Run feedback chain (013).

Walks the human-annotation surface end-to-end:

  a) bob (reader) calls POST /api/runs/{id}/feedback → 403 (lacks
     ``runs:annotate``)
  b) alice (admin) creates a run via the run store; the run carries
     ``auto_score=4.2`` and a ``score_breakdown`` populated by the (here-
     simulated) async judge.
  c) alice GETs the run BEFORE labelling — the API masks ``auto_score``
     and ``score_breakdown`` to NULL (reveal-after-label).
  d) alice POSTs feedback {rating:"up"} — response includes the auto-
     score (label-revealed).
  e) alice GETs the run AFTER labelling — auto_score is visible.
  f) alice re-POSTs feedback {rating:"down", flagged:True} — upsert
     in-place, no second row.
  g) alice GETs the run with ?flagged=1 → contains the flagged run.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import uteki_api.runs as runs_pkg
from uteki_api.runs.models import Run

from .conftest import AuthedUser, Reporter


@pytest.mark.asyncio
async def test_run_feedback_chain(
    client: TestClient,
    alice: AuthedUser,
    bob: AuthedUser,
    reporter: Reporter,
) -> None:
    # Seed a run owned by alice with a fake judge score baked in. The
    # async dispatcher (PR β) will populate these fields for real; we
    # just need *something* present so we can verify the
    # reveal-after-label masking actually masks.
    #
    # Read the store off the package to pick up the per-test rebind
    # the conftest fixture installs (see conftest._reset_state).
    run_store = runs_pkg.default_run_store
    run_id = "t21-A"
    await run_store.create(
        Run(
            id=run_id,
            user_id=alice.id,
            skill="research",
            triggered_by="user",
            started_at=time.time(),
            user_input="please research aapl",
            auto_score=4.2,
            score_breakdown={"outcome": 4.2, "cost": 5.0},
        )
    )

    reporter.section("a) bob (reader) → POST /feedback → 403")
    r = client.post(
        f"/api/runs/{run_id}/feedback",
        headers=bob.auth_header(),
        json={"rating": "up"},
    )
    reporter.kv("status", r.status_code)
    reporter.checked("403 forbidden", r.status_code == 403)
    assert r.status_code == 403

    # Alice owns the run AND has runs:annotate (granted via admin role).
    # Note: bob can't even see this run by ID — it's user-scoped — but
    # the 403 above is the permission check, which happens before the
    # ownership check would.

    reporter.section("c) alice GET /runs/{id} pre-label → score masked")
    r = client.get(f"/api/runs/{run_id}", headers=alice.auth_header())
    body = r.json()
    reporter.kv("auto_score (pre-label)", body.get("auto_score"))
    reporter.kv("score_breakdown (pre-label)", body.get("score_breakdown"))
    reporter.checked("auto_score is None", body["auto_score"] is None)
    reporter.checked("score_breakdown is None", body["score_breakdown"] is None)
    assert body["auto_score"] is None
    assert body["score_breakdown"] is None

    reporter.section("c') alice GET /feedback pre-label → empty row, score masked")
    r = client.get(f"/api/runs/{run_id}/feedback", headers=alice.auth_header())
    body = r.json()
    reporter.checked("rating empty", body["rating"] == "")
    reporter.checked("auto_score is None", body["auto_score"] is None)
    assert body["rating"] == ""
    assert body["auto_score"] is None

    reporter.section("d) alice POST /feedback {up} → response reveals auto_score")
    r = client.post(
        f"/api/runs/{run_id}/feedback",
        headers=alice.auth_header(),
        json={"rating": "up", "notes": "looks reasonable"},
    )
    body = r.json()
    reporter.kv("status", r.status_code)
    reporter.kv("auto_score (post-label)", body.get("auto_score"))
    reporter.kv("rating", body["rating"])
    reporter.checked("200", r.status_code == 200)
    reporter.checked("rating=up", body["rating"] == "up")
    reporter.checked("notes preserved", body["notes"] == "looks reasonable")
    reporter.checked("auto_score revealed", body["auto_score"] == 4.2)
    assert r.status_code == 200
    assert body["rating"] == "up"
    assert body["auto_score"] == 4.2

    reporter.section("e) alice GET /runs/{id} post-label → score visible")
    r = client.get(f"/api/runs/{run_id}", headers=alice.auth_header())
    body = r.json()
    reporter.kv("auto_score (post-label, on Run)", body.get("auto_score"))
    reporter.checked("auto_score visible", body["auto_score"] == 4.2)
    reporter.checked(
        "score_breakdown carried",
        body["score_breakdown"] == {"outcome": 4.2, "cost": 5.0},
    )
    assert body["auto_score"] == 4.2

    reporter.section("f) alice re-POSTs {down, flagged:True} → upserts in place")
    r = client.post(
        f"/api/runs/{run_id}/feedback",
        headers=alice.auth_header(),
        json={"rating": "down", "notes": "actually it's wrong", "flagged": True},
    )
    body = r.json()
    reporter.checked("rating now down", body["rating"] == "down")
    reporter.checked("notes overwritten", body["notes"] == "actually it's wrong")
    reporter.checked("flagged=true", body["flagged"] is True)
    assert body["rating"] == "down"
    assert body["flagged"] is True

    reporter.section("g) alice list /runs?flagged=1 contains this run")
    r = client.get("/api/runs?flagged=1", headers=alice.auth_header())
    body = r.json()
    ids = {item["id"] for item in body["items"]}
    reporter.kv("flagged ids", ids)
    reporter.checked(f"contains {run_id}", run_id in ids)
    assert run_id in ids

    reporter.end()
