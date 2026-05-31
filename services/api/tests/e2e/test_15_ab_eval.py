"""T15 — A/B eval pipeline (M1.7).

Walks accepted → applying → a_b_eval → ab_summary populated, both via
direct ``run_ab_eval`` invocation and through the CLI's ``proposals
accept`` (auto-fires apply + ab_eval).

What this asserts:
- ab_summary lands on Proposal with the canonical schema
- A heartbeat transition (status stays at a_b_eval) carries
  ``ab_summary`` in its extra, so decisions/<NNN>-a_b_eval.json captures
  the data for M1.8's G2 view
- Live SKILL.md is restored to the *proposed* prompt after A/B (the
  baseline-swap is internal and reverted)
- run_ab_eval refuses non-a_b_eval status, and refuses re-run when
  ab_summary already exists
- CLI `accept` chains apply + ab_eval; `accept --no-ab` skips the A/B;
  `proposals ab-eval <P-id>` is a re-run entry point

What this DOESN'T test:
- Real-LLM A/B numbers (mock-mode is deterministic enough for shape)
- G2 adopt/rollback (M1.8)
- Concurrency: this assumes single-process operator-driven flow
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import pytest

from .conftest import Reporter
from .test_13_proposals_cli import REPO_ROOT, _seed_pending


def _seed_with_snapshot(root: Path, pid_label: str = "alice") -> str:
    """T13's `_seed_pending` doesn't populate `snapshot/skill/SKILL.md`
    because T12 covers the cc_runner snapshot path. ab_eval needs the
    baseline to swap to, so we write a synthetic snapshot here.

    The baseline content is intentionally identical to the current live
    research SKILL.md so the mock-llm A/B's pass_rate_delta is 0 — A/B
    is shape-tested, not numeric-value-tested.
    """
    proposal_id = _seed_pending(root, pid_label=pid_label)
    from uteki_api.evolution.apply import _default_skill_root
    live_skill = _default_skill_root() / "research" / "SKILL.md"
    snapshot_dir = root / proposal_id / "snapshot" / "skill"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "SKILL.md").write_text(
        live_skill.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return proposal_id


def _accept(root: Path, proposal_id: str, *, by: str = "test") -> None:
    from uteki_api.evolution.proposals.store import ProposalStore
    ProposalStore(root).transition(proposal_id, "accepted", by=by, reason="t15 seed")


async def _apply_only(root: Path, proposal_id: str) -> None:
    from uteki_api.evolution.apply import apply_proposal
    from uteki_api.evolution.proposals.store import ProposalStore
    from uteki_api.evolution.store import InMemoryEvolutionStore

    await apply_proposal(
        proposal_id,
        store=ProposalStore(root),
        evolution_store=InMemoryEvolutionStore(),
    )


@pytest.mark.asyncio
async def test_run_ab_eval_populates_ab_summary(
    client, tmp_path: Path, reporter: Reporter
) -> None:
    from uteki_api.evolution.ab_eval import run_ab_eval
    from uteki_api.evolution.proposals.store import ProposalStore

    root = tmp_path / "proposals"
    p1 = _seed_with_snapshot(root, pid_label="alice")
    _accept(root, p1, by="cli:alice")
    await _apply_only(root, p1)

    store = ProposalStore(root)
    assert store.get(p1).status == "a_b_eval"
    assert store.get(p1).ab_summary is None

    reporter.section("run_ab_eval(...) — mock-llm fast path")
    result = await run_ab_eval(p1, store=store)
    reporter.kv("ok", result.ok)
    reporter.kv("duration_s", round(result.duration_s, 2))
    reporter.kv("ab_summary", result.ab_summary)
    assert result.ok, f"ab_eval failed: {result.error}"

    s = result.ab_summary
    reporter.section("ab_summary schema")
    for k in (
        "cases_run", "pass_rate_baseline", "pass_rate_proposed",
        "delta_pp", "latency_ms_baseline_mean", "latency_ms_proposed_mean",
        "judge_score_baseline", "judge_score_proposed", "ran_at", "mode",
    ):
        reporter.checked(f"ab_summary[{k}]", k in s)
        assert k in s, f"ab_summary missing key {k}"
    assert s["cases_run"] >= 1, "no eval cases ran — fixture issue?"
    assert s["mode"] == "mock-llm"

    reporter.section("ab_summary persisted onto Proposal")
    final = store.get(p1)
    assert final.ab_summary == s
    assert final.status == "a_b_eval"  # heartbeat, not advanced past it

    reporter.section("heartbeat transition recorded for M1.8 G2 view")
    last = final.transitions[-1]
    reporter.kv("last transition to", last.to)
    reporter.kv("last transition by", last.by)
    reporter.kv("last transition reason (first 80)", last.reason[:80])
    assert last.to == "a_b_eval"
    assert last.by == "system:ab_eval"
    assert "pass_rate" in last.reason
    assert "ab_summary" in last.extra

    reporter.section("decisions/<NNN>-a_b_eval.json captures the summary")
    # Latest transition's serialized decision file should be the ab_eval one.
    decisions = sorted((root / p1 / "decisions").glob("*.json"))
    latest_decision = decisions[-1]
    reporter.kv("latest decision file", latest_decision.name)
    import json as _json
    body = _json.loads(latest_decision.read_text())
    assert body["to"] == "a_b_eval"
    assert "ab_summary" in body.get("extra", {})
    reporter.end()


@pytest.mark.asyncio
async def test_run_ab_eval_restores_live_skill_md(
    client, tmp_path: Path, reporter: Reporter
) -> None:
    """A/B's internal baseline-swap MUST restore the proposed file on exit."""
    from uteki_api.evolution.ab_eval import run_ab_eval
    from uteki_api.evolution.apply import _default_skill_root
    from uteki_api.evolution.proposals.store import ProposalStore

    root = tmp_path / "proposals"
    p1 = _seed_with_snapshot(root, pid_label="alice")
    _accept(root, p1, by="cli:alice")
    await _apply_only(root, p1)

    live = _default_skill_root() / "research" / "SKILL.md"
    before = live.read_text(encoding="utf-8")
    reporter.kv("live SKILL.md len before A/B", len(before))

    await run_ab_eval(p1, store=ProposalStore(root))

    after = live.read_text(encoding="utf-8")
    reporter.kv("live SKILL.md len after A/B", len(after))
    assert after == before, "ab_eval failed to restore the proposed SKILL.md"
    reporter.end()


@pytest.mark.asyncio
async def test_run_ab_eval_refuses_wrong_status_and_repeat(
    client, tmp_path: Path, reporter: Reporter
) -> None:
    from uteki_api.evolution.ab_eval import run_ab_eval
    from uteki_api.evolution.proposals.store import ProposalStore

    root = tmp_path / "proposals"
    p1 = _seed_with_snapshot(root, pid_label="alice")

    reporter.section("refuses while still pending_review")
    with pytest.raises(ValueError, match="expected a_b_eval"):
        await run_ab_eval(p1, store=ProposalStore(root))

    _accept(root, p1, by="cli:alice")
    await _apply_only(root, p1)
    await run_ab_eval(p1, store=ProposalStore(root))

    reporter.section("refuses re-run when ab_summary already present")
    with pytest.raises(ValueError, match="already has ab_summary"):
        await run_ab_eval(p1, store=ProposalStore(root))

    reporter.end()


def test_cli_accept_chains_apply_then_ab(
    client, tmp_path: Path, reporter: Reporter
) -> None:
    root = tmp_path / "proposals"
    p1 = _seed_with_snapshot(root, pid_label="alice")

    cli = REPO_ROOT / "scripts" / "proposals"
    env = {**os.environ, "NO_COLOR": "1", "UTEKI_OPERATOR": "alice"}
    reporter.section("./proposals accept — chains apply + ab")
    proc = subprocess.run(
        [str(cli), "--root", str(root), "accept", p1, "--reason", "t15"],
        check=False, capture_output=True, text=True, env=env, timeout=120,
    )
    reporter.kv("exit", proc.returncode)
    reporter.kv("stdout", proc.stdout)
    assert proc.returncode == 0, proc.stderr
    assert "apply OK" in proc.stdout
    assert "running A/B" in proc.stdout
    assert "baseline:" in proc.stdout
    assert "proposed:" in proc.stdout
    assert "pp" in proc.stdout  # delta line

    from uteki_api.evolution.proposals.store import ProposalStore
    final = ProposalStore(root).get(p1)
    assert final.ab_summary
    assert final.status == "a_b_eval"
    reporter.end()


def test_cli_accept_no_ab_flag_skips_ab(
    client, tmp_path: Path, reporter: Reporter
) -> None:
    root = tmp_path / "proposals"
    p1 = _seed_with_snapshot(root, pid_label="alice")
    cli = REPO_ROOT / "scripts" / "proposals"
    env = {**os.environ, "NO_COLOR": "1", "UTEKI_OPERATOR": "alice"}

    reporter.section("./proposals accept --no-ab — apply but skip A/B")
    proc = subprocess.run(
        [str(cli), "--root", str(root), "accept", p1, "--no-ab"],
        check=False, capture_output=True, text=True, env=env, timeout=60,
    )
    reporter.kv("exit", proc.returncode)
    reporter.kv("stdout (tail 200)", proc.stdout[-200:])
    assert proc.returncode == 0, proc.stderr
    assert "apply OK" in proc.stdout
    assert "running A/B" not in proc.stdout

    from uteki_api.evolution.proposals.store import ProposalStore
    assert ProposalStore(root).get(p1).ab_summary is None

    reporter.section("./proposals ab-eval picks up the slack")
    proc2 = subprocess.run(
        [str(cli), "--root", str(root), "ab-eval", p1],
        check=False, capture_output=True, text=True, env=env, timeout=120,
    )
    reporter.kv("exit", proc2.returncode)
    assert proc2.returncode == 0, proc2.stderr
    assert "baseline:" in proc2.stdout
    assert ProposalStore(root).get(p1).ab_summary is not None

    reporter.section("ab-eval refuses re-run after ab_summary set")
    proc3 = subprocess.run(
        [str(cli), "--root", str(root), "ab-eval", p1],
        check=False, capture_output=True, text=True, env=env, timeout=30,
    )
    reporter.kv("exit", proc3.returncode)
    reporter.kv("stderr (tail 200)", proc3.stderr[-200:])
    assert proc3.returncode == 7  # _run_ab_eval's ValueError exit code
    assert "already has ab_summary" in proc3.stderr
    reporter.end()


# Suppress noisy unused-import warnings about asyncio when running under pytest
# in environments without strict imports — keeps the module valid even if
# pytest's plugin path changes test discovery.
_ = asyncio
