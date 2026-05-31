"""T12 — cc_runner end-to-end (M1.3).

Drives a proposal from ``triggered`` → ``pending_review`` via
``POST /api/admin/proposals/{id}/run-cc`` with the mock CC backend
(UTEKI_USE_MOCK_CC follows UTEKI_USE_MOCK_LLM, true by default in tests).

What this asserts:
- Background task completes and the proposal lands at pending_review
- On-disk layout matches design/02 §VII (snapshot/, brief.md, cc_run/*)
- cc_run/ contains all four canonical files (invocation.json, transcript.jsonl,
  critique.md, patch.diff)
- meta.json transitions list contains every state the pipeline walked through
- 409 on attempting to re-run cc on an already-advanced proposal
- 404 on unknown proposal_id

What this DOESN'T test (deferred):
- Real claude CLI invocation (mock mode only — real path is exercised
  manually + by drift_monitor smoke in M1.11)
- Apply / A-B / G2 (M1.6 / M1.7 / M1.8)
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
    """Same shape as T9's fixture, plus the cc_runner rebind.

    cc_runner imports default_proposal_store by name — so the API handler
    and the background task have to see the same swapped instance, or
    the API will create a proposal in store A and the task will look it
    up in store B and 404 itself."""
    from uteki_api.api import admin as api_admin
    from uteki_api.evolution import cc_runner as cc_runner_mod
    from uteki_api.evolution.proposals import store as proposal_store_mod

    fresh_dir = tmp_path / "proposals"
    fresh_store = proposal_store_mod.ProposalStore(fresh_dir)

    monkeypatch.setattr(proposal_store_mod, "default_proposal_store", fresh_store)
    monkeypatch.setattr(api_admin, "default_proposal_store", fresh_store)
    monkeypatch.setattr(cc_runner_mod, "default_proposal_store", fresh_store)

    return fresh_store


def _seed_run_with_artifact(user_id: str, label: str = "test") -> str:
    """Seed a Run + one artifact so cc_runner has something to snapshot."""
    from uteki_api.artifacts import default_artifact_store
    from uteki_api.runs import Run, default_run_store
    from uteki_api.schemas.events import AgentEvent

    rid = f"t12-{label}"

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
            rid, AgentEvent(type="delta", run_id=rid, data={"text": "research output"})
        )
        # cc_runner snapshots whatever the artifact store has for this run.
        await default_artifact_store.write(
            run_id=rid,
            user_id=user_id,
            name="final-report.md",
            content=(
                "# Mock research report\n\n"
                "Line A claims X without citation.\n"
                "Line B references [^1] which doesn't exist in sources.json.\n"
            ),
            kind="markdown",
            written_by="research",
            description="seeded for T12",
        )
        await default_run_store.finish(rid, "ok", "seeded for T12")
        return rid

    return asyncio.run(go())


def _wait_for_status(
    client: TestClient,
    auth: dict[str, str],
    proposal_id: str,
    target_statuses: set[str],
    timeout_s: float = 5.0,
    poll_s: float = 0.05,
) -> dict:
    """Poll GET /api/admin/proposals/{id} until status ∈ target_statuses.

    Mock cc_runner finishes synchronously enough that this usually returns
    on the first poll, but a hard wall-time keeps a regression from hanging
    the suite indefinitely."""
    deadline = time.time() + timeout_s
    last: dict = {}
    while time.time() < deadline:
        r = client.get(f"/api/admin/proposals/{proposal_id}", headers=auth)
        if r.status_code != 200:
            time.sleep(poll_s)
            continue
        last = r.json()
        if last.get("status") in target_statuses:
            return last
        time.sleep(poll_s)
    raise AssertionError(
        f"proposal {proposal_id} stuck at {last.get('status')!r} after {timeout_s}s; "
        f"transitions={[t.get('to') for t in last.get('transitions', [])]}"
    )


def test_cc_review_pipeline_end_to_end(
    client: TestClient,
    alice: AuthedUser,
    proposal_store_tmp,
    reporter: Reporter,
) -> None:
    reporter.section("seed a run + artifact for alice")
    rid = _seed_run_with_artifact(alice.id, label="alice")
    reporter.kv("run_id", rid)

    reporter.section("POST /api/admin/review/{run_id} — create proposal")
    r = client.post(
        f"/api/admin/review/{rid}?reason=t12+smoke",
        headers=alice.auth_header(),
    )
    assert r.status_code == 200
    p_id = r.json()["proposal_id"]
    reporter.kv("proposal_id", p_id)
    reporter.kv("status", r.json()["status"])
    assert r.json()["status"] == "triggered"

    reporter.section("POST /api/admin/proposals/{id}/run-cc — kick off cc_runner")
    r2 = client.post(
        f"/api/admin/proposals/{p_id}/run-cc",
        headers=alice.auth_header(),
    )
    reporter.kv("HTTP", r2.status_code)
    reporter.kv("body", r2.json())
    assert r2.status_code == 200
    assert r2.json()["status"] == "spawning"

    reporter.section("wait for pipeline to settle")
    final = _wait_for_status(
        client,
        alice.auth_header(),
        p_id,
        target_statuses={"pending_review", "invalidated"},
        timeout_s=10.0,
    )
    reporter.kv("final status", final["status"])
    reporter.kv(
        "transition path",
        [t["to"] for t in final["transitions"]],
    )
    assert final["status"] == "pending_review", (
        f"expected pending_review, got {final['status']} — "
        f"transitions={[t.get('to') for t in final.get('transitions', [])]}"
    )

    reporter.section("state machine walked every expected vertex")
    walked = {t["to"] for t in final["transitions"]}
    expected_walk = {
        "triggered",
        "snapshotting",
        "briefing",
        "spawning",
        "generating",
        "validating",
        "pending_review",
    }
    missing = expected_walk - walked
    reporter.checked("all expected vertices visited", not missing, f"missing: {missing}")
    assert not missing, f"missing transitions: {missing}"

    reporter.section("snapshot/ and cc_run/ files on disk")
    pdir = proposal_store_tmp._dir(p_id)
    snapshot_skill = pdir / "snapshot" / "skill" / "SKILL.md"
    snapshot_artifact = pdir / "snapshot" / "run_artifacts" / "final-report.md"
    brief = pdir / "brief.md"
    cc_dir = pdir / "cc_run"
    for f in (snapshot_skill, snapshot_artifact, brief):
        reporter.event("snapshot file", str(f.relative_to(pdir)))
        reporter.checked(f"{f.name} exists", f.exists())
        assert f.exists(), f"missing: {f}"

    cc_files = {
        "invocation.json",
        "transcript.jsonl",
        "critique.md",
        "patch.diff",
    }
    actual_cc_files = {p.name for p in cc_dir.iterdir() if p.is_file()}
    reporter.kv("cc_run files", sorted(actual_cc_files))
    missing_cc = cc_files - actual_cc_files
    reporter.checked("cc_run has every canonical file", not missing_cc, f"missing: {missing_cc}")
    assert not missing_cc

    reporter.section("invocation.json + critique.md content sanity")
    import json as _json
    invocation = _json.loads((cc_dir / "invocation.json").read_text())
    reporter.kv("invocation.cli", invocation.get("cli"))
    reporter.kv("invocation.mode", invocation.get("mode"))
    reporter.checked("invocation has exit_code", "exit_code" in invocation)
    reporter.checked("invocation has duration_s", "duration_s" in invocation)
    assert invocation["cli"] == "mock"
    assert invocation["exit_code"] == 0
    critique_text = (cc_dir / "critique.md").read_text()
    reporter.checked("critique mentions snapshotted artifact",
                     "final-report.md" in critique_text)

    reporter.section("snapshot_skill_signature recorded on proposal")
    reporter.kv("snapshot_skill_signature", final.get("snapshot_skill_signature"))
    assert final.get("snapshot_skill_signature"), \
        "expected snapshot_skill_signature to be set after snapshotting"

    reporter.section("validation.json — M1.4 acceptance artifact")
    validation_path = pdir / "validation.json"
    reporter.checked("validation.json exists", validation_path.exists())
    assert validation_path.exists()
    validation = _json.loads(validation_path.read_text())
    reporter.kv("ok", validation["ok"])
    reporter.kv("reasons", validation["reasons"])
    reporter.kv("stats.patch_applies", validation["stats"].get("patch_applies"))
    reporter.kv("stats.critique_finding_count",
                validation["stats"].get("critique_finding_count"))
    assert validation["ok"] is True
    assert validation["reasons"] == []
    # Mock mode: empty patch → trivially applies. Critique has at least one finding.
    assert validation["stats"]["patch_applies"] is True
    assert validation["stats"]["patch_lines_total"] == 0
    assert validation["stats"]["critique_finding_count"] >= 1

    reporter.section("idempotency: re-running cc on pending_review → 409")
    r3 = client.post(
        f"/api/admin/proposals/{p_id}/run-cc",
        headers=alice.auth_header(),
    )
    reporter.kv("HTTP", r3.status_code)
    assert r3.status_code == 409

    reporter.end()


def test_run_cc_on_unknown_proposal_404(
    client: TestClient,
    alice: AuthedUser,
    proposal_store_tmp,
    reporter: Reporter,
) -> None:
    reporter.section("POST /api/admin/proposals/P-does-not-exist/run-cc")
    r = client.post(
        "/api/admin/proposals/P-does-not-exist/run-cc",
        headers=alice.auth_header(),
    )
    reporter.kv("HTTP", r.status_code)
    assert r.status_code == 404

    reporter.section("GET /api/admin/proposals/P-does-not-exist")
    r2 = client.get(
        "/api/admin/proposals/P-does-not-exist",
        headers=alice.auth_header(),
    )
    reporter.kv("HTTP", r2.status_code)
    assert r2.status_code == 404
    reporter.end()
