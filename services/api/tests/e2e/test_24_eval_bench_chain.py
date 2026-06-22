"""T24 — Eval workbench suite CRUD chain (015 PR α).

Walks the admin-only eval bench surface end-to-end:

  a) bob (reader) → list suites → 403
  b) alice (admin) → create suite → 200, id returned
  c) alice → list suites → contains the new one
  d) alice → get by id → matches what we created
  e) alice → patch (rename + edit queries + add cron) → 200, fields updated
  f) alice → patch with new field but omit cron_schedule → cron survives
  g) alice → list bench runs for that suite → empty (no runs yet, PR γ adds them)
  h) alice → patch decision on nonexistent bench run → 404
  i) alice → archive (DELETE) suite → 200
  j) alice → list (default) → no longer contains it
  k) alice → list (?include_archived=1) → contains it

Bench-run runner (Mode A/B fan-out) is not part of PR α — that's PR γ.
This chain only validates the CRUD surface, the decision endpoint shape,
and the not-found paths.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .conftest import AuthedUser, Reporter


SUITE_CREATE_BODY = {
    "name": "T24 test suite",
    "skill_name": "company_research_pipeline",
    "description": "T24 e2e — verify CRUD surface",
    "queries": [
        {"ticker": "GOOGL", "peers": ["MSFT", "META"], "question": "long-term?"},
        {"ticker": "NVDA", "peers": ["AMD"], "question": "AI moat?"},
    ],
}


@pytest.mark.asyncio
async def test_eval_bench_chain(
    client: TestClient,
    alice: AuthedUser,
    bob: AuthedUser,
    reporter: Reporter,
) -> None:
    reporter.section("a) bob (reader) → list suites → 403")
    r = client.get("/api/admin/eval/suites", headers=bob.auth_header())
    reporter.kv("status", r.status_code)
    reporter.checked("403 forbidden", r.status_code == 403)
    assert r.status_code == 403

    reporter.section("b) alice (admin) → create suite → 200")
    r = client.post(
        "/api/admin/eval/suites",
        headers=alice.auth_header(),
        json=SUITE_CREATE_BODY,
    )
    reporter.kv("status", r.status_code)
    assert r.status_code == 200, r.text
    suite = r.json()
    suite_id = suite["id"]
    reporter.kv("suite_id", suite_id)
    reporter.kv("name", suite["name"])
    reporter.kv("queries", len(suite["queries"]))
    assert suite["name"] == "T24 test suite"
    assert suite["skill_name"] == "company_research_pipeline"
    assert len(suite["queries"]) == 2
    assert suite["archived"] is False
    assert suite["cron_schedule"] is None

    reporter.section("c) alice → list suites → contains new one")
    r = client.get("/api/admin/eval/suites", headers=alice.auth_header())
    suites = r.json()
    ids = [s["id"] for s in suites]
    reporter.kv("count", len(suites))
    reporter.checked("includes new suite", suite_id in ids)
    assert suite_id in ids

    reporter.section("d) alice → get by id → matches creation")
    r = client.get(
        f"/api/admin/eval/suites/{suite_id}", headers=alice.auth_header()
    )
    fetched = r.json()
    reporter.checked("name match", fetched["name"] == suite["name"])
    assert r.status_code == 200
    assert fetched["id"] == suite_id

    reporter.section("e) alice → patch (rename + edit queries + add cron)")
    r = client.patch(
        f"/api/admin/eval/suites/{suite_id}",
        headers=alice.auth_header(),
        json={
            "name": "T24 renamed",
            "queries": [
                {"ticker": "TSLA", "peers": ["GM"], "question": "EV moat?"},
            ],
            "cron_schedule": "0 6 * * *",
        },
    )
    reporter.kv("status", r.status_code)
    updated = r.json()
    reporter.kv("name", updated["name"])
    reporter.kv("queries", len(updated["queries"]))
    reporter.kv("cron", updated["cron_schedule"])
    assert r.status_code == 200
    assert updated["name"] == "T24 renamed"
    assert len(updated["queries"]) == 1
    assert updated["queries"][0]["ticker"] == "TSLA"
    assert updated["cron_schedule"] == "0 6 * * *"

    reporter.section("f) alice → patch description only → cron survives")
    r = client.patch(
        f"/api/admin/eval/suites/{suite_id}",
        headers=alice.auth_header(),
        json={"description": "updated description"},
    )
    updated = r.json()
    reporter.kv("cron survived", updated["cron_schedule"])
    assert updated["description"] == "updated description"
    assert updated["cron_schedule"] == "0 6 * * *"

    reporter.section("g) alice → list bench runs for suite → empty (PR γ wires the runner)")
    r = client.get(
        f"/api/admin/eval/runs?suite_id={suite_id}", headers=alice.auth_header()
    )
    runs = r.json()
    reporter.kv("count", len(runs))
    reporter.checked("empty", runs == [])
    assert r.status_code == 200
    assert runs == []

    reporter.section("h) alice → decide a nonexistent bench run → 404")
    r = client.patch(
        "/api/admin/eval/runs/does-not-exist/decision",
        headers=alice.auth_header(),
        json={"decision": "approve"},
    )
    reporter.kv("status", r.status_code)
    reporter.checked("404 not found", r.status_code == 404)
    assert r.status_code == 404

    reporter.section("h') alice → reject without reason → 400")
    r = client.patch(
        "/api/admin/eval/runs/does-not-exist/decision",
        headers=alice.auth_header(),
        json={"decision": "reject", "reason": "   "},
    )
    reporter.kv("status", r.status_code)
    reporter.checked("400 bad request", r.status_code == 400)
    assert r.status_code == 400

    reporter.section("i) alice → archive (DELETE) suite")
    r = client.delete(
        f"/api/admin/eval/suites/{suite_id}", headers=alice.auth_header()
    )
    reporter.kv("status", r.status_code)
    body = r.json()
    reporter.checked("archived=True", body.get("archived") is True)
    assert r.status_code == 200

    reporter.section("j) alice → list (default) → does not contain archived")
    r = client.get("/api/admin/eval/suites", headers=alice.auth_header())
    ids = [s["id"] for s in r.json()]
    reporter.checked("not in default list", suite_id not in ids)
    assert suite_id not in ids

    reporter.section("k) alice → list ?include_archived=1 → contains it")
    r = client.get(
        "/api/admin/eval/suites?include_archived=1", headers=alice.auth_header()
    )
    ids = [s["id"] for s in r.json()]
    reporter.checked("in include_archived list", suite_id in ids)
    assert suite_id in ids


@pytest.mark.asyncio
async def test_seed_suite_present_on_startup(
    client: TestClient,
    alice: AuthedUser,
    reporter: Reporter,
) -> None:
    """The lifespan ``_seed_default_bench_suite`` should have run at app
    startup. Verify the ``mega-cap baseline`` suite exists with 10
    queries against company_research_pipeline."""
    reporter.section("seed: mega-cap baseline suite present")
    r = client.get("/api/admin/eval/suites", headers=alice.auth_header())
    suites = r.json()
    seed = next((s for s in suites if s["name"] == "mega-cap baseline"), None)
    reporter.kv("found", seed is not None)
    assert seed is not None, f"seed suite not present; got names={[s['name'] for s in suites]}"
    reporter.kv("skill_name", seed["skill_name"])
    reporter.kv("queries", len(seed["queries"]))
    reporter.kv("tickers", sorted({q["ticker"] for q in seed["queries"]}))
    assert seed["skill_name"] == "company_research_pipeline"
    assert len(seed["queries"]) == 10
    expected_tickers = {"GOOGL", "MSFT", "NVDA", "AAPL", "META",
                        "AMZN", "TSLA", "AMD", "AVGO", "NFLX"}
    assert {q["ticker"] for q in seed["queries"]} == expected_tickers
