"""T9 — Proposal store + POST /api/admin/review/{run_id}.

M1.1 self-evolution loop bookkeeping. Verifies:
- A run can be marked for review via the admin endpoint
- The Proposal record lands on disk with the canonical layout
- State transitions append to ``decisions/`` AND rewrite ``meta.json``
- Terminal status protection prevents post-mortem mutation
- Multi-tenant: Alice can't trigger review on Bob's run (404 shape)

What this DOESN'T test (out of M1.1 scope):
- CC subprocess spawning (M1.3)
- Patch validation (M1.4)
- G1 review UI (M1.5)
- Apply pipeline (M1.6)
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from .conftest import AuthedUser, Reporter


@pytest.fixture
def proposal_store_tmp(monkeypatch, tmp_path: Path):
    """Point the module-level default_proposal_store at a per-test dir
    so proposals from one test don't leak into the next.

    Pattern: same as conftest's run/memory rebinding — the API and the
    store live in the same process here, so swapping the singleton on
    every importing module is sufficient."""
    from uteki_api.api import admin as api_admin
    from uteki_api.evolution.proposals import store as proposal_store_mod

    fresh_dir = tmp_path / "proposals"
    fresh_store = proposal_store_mod.ProposalStore(fresh_dir)

    monkeypatch.setattr(proposal_store_mod, "default_proposal_store", fresh_store)
    monkeypatch.setattr(api_admin, "default_proposal_store", fresh_store)

    return fresh_store


def _seed_run(user_id: str, label: str = "test") -> str:
    """Quick helper: seed a Run in the in-process RunStore."""
    from uteki_api.runs import Run, default_run_store
    from uteki_api.schemas.events import AgentEvent

    rid = f"t09-{label}"

    async def go() -> str:
        await default_run_store.create(
            Run(
                id=rid,
                user_id=user_id,
                skill="research",
                triggered_by="user",
                started_at=time.time(),
            )
        )
        await default_run_store.append_event(
            rid, AgentEvent(type="delta", run_id=rid, data={"text": "x"})
        )
        await default_run_store.finish(rid, "ok", "test summary")
        return rid

    return asyncio.run(go())


def test_proposal_store_create_round_trip(proposal_store_tmp, reporter: Reporter) -> None:
    """Direct store calls — no HTTP. Tests the model + persistence layer."""
    reporter.section("create a proposal")
    p = proposal_store_tmp.create(
        source_run_id="r1",
        source_skill="research",
        source_user_id="alice_id",
        triggered_by="system:manual",
        trigger_reason="smoke",
    )
    reporter.kv("proposal_id", p.proposal_id)
    reporter.kv("status", p.status)
    reporter.kv("transitions count", len(p.transitions))
    reporter.checked("id matches P-YYYY-NNN format", p.proposal_id.startswith("P-2026-"))
    reporter.checked("status=triggered", p.status == "triggered")
    reporter.checked("transitions has the create record", len(p.transitions) == 1)
    assert p.status == "triggered"

    reporter.section("on-disk layout")
    pdir = proposal_store_tmp._dir(p.proposal_id)
    files = sorted(pdir.rglob("*"))
    for f in files:
        if f.is_file():
            reporter.event("file", str(f.relative_to(pdir)))
    expected = {"meta.json", "trigger.json", "decisions/001-triggered.json"}
    actual = {str(f.relative_to(pdir)) for f in pdir.rglob("*") if f.is_file()}
    reporter.checked("all expected files present", expected.issubset(actual),
                     f"missing: {expected - actual}")
    assert expected.issubset(actual)

    reporter.section("transition to snapshotting")
    p2 = proposal_store_tmp.transition(p.proposal_id, "snapshotting", by="system")
    reporter.kv("new status", p2.status)
    reporter.checked("status updated", p2.status == "snapshotting")
    reporter.checked("transitions appended", len(p2.transitions) == 2)
    decisions_dir = pdir / "decisions"
    reporter.checked("decisions/002-snapshotting.json exists",
                     (decisions_dir / "002-snapshotting.json").exists())
    assert (decisions_dir / "002-snapshotting.json").exists()

    reporter.section("can transition through full happy path")
    for s in ("briefing", "spawning", "generating", "validating", "pending_review",
              "accepted", "applying", "a_b_eval", "adopted"):
        proposal_store_tmp.transition(p.proposal_id, s, by="test")  # type: ignore[arg-type]
    final = proposal_store_tmp.get(p.proposal_id)
    reporter.kv("final status", final.status)
    reporter.checked("ended at adopted (terminal)", final.status == "adopted")
    reporter.checked("transitions count = 11", len(final.transitions) == 11)
    reporter.checked("is_terminal flag set", final.is_terminal)
    assert final.is_terminal

    reporter.section("terminal protection: can't transition out of adopted")
    with pytest.raises(ValueError, match="terminal"):
        proposal_store_tmp.transition(p.proposal_id, "applying", by="test")
    reporter.checked("ValueError raised", True)

    reporter.end()


def test_review_endpoint_creates_proposal(
    client: TestClient,
    alice: AuthedUser,
    proposal_store_tmp,
    reporter: Reporter,
) -> None:
    """Through the HTTP API: POST /api/admin/review/<run_id> end-to-end."""
    reporter.section("seed a run for alice")
    rid = _seed_run(alice.id, label="alice")
    reporter.kv("run_id", rid)

    reporter.section("POST /api/admin/review/{run_id}")
    r = client.post(
        f"/api/admin/review/{rid}?reason=manual+smoke",
        headers=alice.auth_header(),
    )
    reporter.kv("HTTP", r.status_code)
    reporter.kv("body", r.json())
    assert r.status_code == 200
    body = r.json()

    reporter.checked("proposal_id returned", "proposal_id" in body)
    reporter.checked("status=triggered", body["status"] == "triggered")
    reporter.checked("source_run_id matches", body["source_run_id"] == rid)
    reporter.checked("source_skill==research", body["source_skill"] == "research")

    reporter.section("proposal exists on disk")
    p_id = body["proposal_id"]
    p = proposal_store_tmp.get(p_id)
    reporter.kv("on-disk status", p.status)
    reporter.kv("on-disk source_user_id", p.source_user_id)
    reporter.checked("source_user_id == alice.id", p.source_user_id == alice.id)
    reporter.checked("triggered_by includes alice.id",
                     f"user:{alice.id}" in p.transitions[0].by)
    reporter.checked("trigger_reason captured",
                     "manual smoke" in p.transitions[0].reason or "smoke" in p.transitions[0].reason)

    reporter.section("listing — alice can find her proposal")
    items = proposal_store_tmp.list(source_user_id=alice.id)
    reporter.kv("items", [p.proposal_id for p in items])
    reporter.checked("at least one proposal listed", len(items) >= 1)
    reporter.checked("alice's proposal in list", p_id in [p.proposal_id for p in items])

    reporter.end()


def test_review_cross_user_isolation(
    client: TestClient,
    alice: AuthedUser,
    bob: AuthedUser,
    proposal_store_tmp,
    reporter: Reporter,
) -> None:
    """Alice can't trigger review on Bob's run."""
    reporter.section("seed bob's run")
    rid_b = _seed_run(bob.id, label="bob-secret")

    reporter.section("alice tries to review bob's run")
    r = client.post(
        f"/api/admin/review/{rid_b}",
        headers=alice.auth_header(),
    )
    reporter.kv("status", r.status_code)
    reporter.checked("→ 404 (same shape as not-exist, no existence leak)",
                     r.status_code == 404)
    assert r.status_code == 404

    reporter.section("bob can review his own run")
    r2 = client.post(
        f"/api/admin/review/{rid_b}",
        headers=bob.auth_header(),
    )
    reporter.checked("→ 200", r2.status_code == 200)
    assert r2.status_code == 200

    reporter.end()


def test_review_unknown_run_404(
    client: TestClient,
    alice: AuthedUser,
    proposal_store_tmp,
    reporter: Reporter,
) -> None:
    """Bogus run_id → 404 (same shape as cross-user)."""
    reporter.section("POST /api/admin/review/does-not-exist")
    r = client.post("/api/admin/review/does-not-exist", headers=alice.auth_header())
    reporter.kv("status", r.status_code)
    reporter.checked("→ 404", r.status_code == 404)
    assert r.status_code == 404
    reporter.end()
