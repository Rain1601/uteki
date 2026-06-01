"""T16 — G2 decisions (M1.8) close the self-evolution loop.

Three terminal paths from a_b_eval:
  adopted        — pure transition; live skill = proposed (unchanged)
  rolled_back    — live skill reverted to snapshot, EvolutionStore gets
                   a new vN with rolled_back_from stamped, signature
                   matches baseline
  inconclusive   — pure transition; live skill = proposed (operator
                   parked the proposal without making a determination)

T16 also asserts:
- G2 verbs refuse non-``a_b_eval`` status (exit 3)
- G2 verbs refuse ``a_b_eval`` without ``ab_summary`` (exit 3)
- Re-firing on a terminal status raises (ProposalStore terminal guard)
- The first true end-to-end self-evolution loop: pending_review →
  accepted → applying → a_b_eval → adopted, in one operator command

This closes the M1 happy path. Drift-triggered automatic creation
(M1.11) and cross-skill smoke (M1.12) layer onto this foundation.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import pytest

from .conftest import Reporter
from .test_13_proposals_cli import REPO_ROOT
from .test_15_ab_eval import _accept, _apply_only, _seed_with_snapshot


async def _seed_through_ab_eval(root: Path, *, pid_label: str = "alice") -> str:
    """Drive a fresh proposal all the way to a_b_eval+ab_summary in-process."""
    from uteki_api.evolution.ab_eval import run_ab_eval
    from uteki_api.evolution.proposals.store import ProposalStore

    p1 = _seed_with_snapshot(root, pid_label=pid_label)
    _accept(root, p1, by="cli:alice")
    await _apply_only(root, p1)
    await run_ab_eval(p1, store=ProposalStore(root))
    return p1


# ── adopt ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_adopt_keeps_live_prompt_and_marks_terminal(
    client, tmp_path: Path, reporter: Reporter
) -> None:
    from uteki_api.evolution.apply import _default_skill_root
    from uteki_api.evolution.g2 import adopt_proposal
    from uteki_api.evolution.proposals.store import ProposalStore

    root = tmp_path / "proposals"
    p1 = await _seed_through_ab_eval(root)

    live = _default_skill_root() / "research" / "SKILL.md"
    before = live.read_text(encoding="utf-8")
    reporter.kv("live SKILL.md bytes pre-adopt", len(before))

    reporter.section("adopt_proposal(...)")
    result = await adopt_proposal(
        p1, by="cli:alice", reason="A/B looks fine", store=ProposalStore(root)
    )
    reporter.kv("final_status", result.final_status)
    reporter.kv("new_version", result.new_version)
    assert result.ok
    assert result.final_status == "adopted"
    assert result.new_version is None  # apply-time version is canonical

    reporter.section("live SKILL.md untouched")
    after = live.read_text(encoding="utf-8")
    assert after == before

    reporter.section("proposal terminal")
    final = ProposalStore(root).get(p1)
    assert final.status == "adopted"
    assert final.is_terminal
    last = final.transitions[-1]
    assert last.to == "adopted"
    assert last.by == "cli:alice"
    assert last.reason == "A/B looks fine"

    reporter.section("re-fire on terminal → ValueError")
    # Two equally valid guards may fire first depending on call order:
    # G2's "expected a_b_eval" status guard OR ProposalStore's "terminal"
    # guard. Either is acceptable — accept both shapes.
    with pytest.raises(ValueError, match="(terminal|expected a_b_eval)"):
        await adopt_proposal(p1, by="cli:alice", store=ProposalStore(root))
    reporter.end()


# ── rollback ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rollback_reverts_live_and_records_version(
    client, tmp_path: Path, reporter: Reporter
) -> None:
    """The headline scenario: G2 says 'A/B regressed, revert'."""
    from uteki_api.evolution.apply import _default_skill_root, _live_signature
    from uteki_api.evolution.g2 import rollback_proposal
    from uteki_api.evolution.proposals.store import ProposalStore
    from uteki_api.evolution.store import InMemoryEvolutionStore

    root = tmp_path / "proposals"
    p1 = await _seed_through_ab_eval(root)

    # The seed uses an identical-content snapshot, so for this test we
    # tweak the live SKILL.md so rollback has something visible to revert.
    live = _default_skill_root() / "research" / "SKILL.md"
    pre_rollback_text = live.read_text(encoding="utf-8")
    tampered = pre_rollback_text + "\n<!-- proposed addition that rollback will revert -->\n"
    live.write_text(tampered, encoding="utf-8")
    reporter.kv("live SKILL.md bytes (post-tamper)", len(tampered))

    fresh_evo = InMemoryEvolutionStore()

    reporter.section("rollback_proposal(...)")
    try:
        result = await rollback_proposal(
            p1,
            by="cli:alice",
            reason="A/B regression on cite_compliance",
            store=ProposalStore(root),
            evolution_store=fresh_evo,
        )
        reporter.kv("ok", result.ok)
        reporter.kv("final_status", result.final_status)
        reporter.kv("new_version", result.new_version)
        reporter.kv("live_signature", result.live_signature)
        assert result.ok
        assert result.final_status == "rolled_back"
        assert result.new_version, "rollback should record a new SkillVersion"

        reporter.section("live SKILL.md restored to baseline (= pre-tamper content)")
        after = live.read_text(encoding="utf-8")
        assert after == pre_rollback_text, (
            "rollback didn't revert to baseline — live still has the tamper"
        )
        # result.live_signature is the COMPOSED prompt signature (loader
        # glues guardrails + SKILL.md + references + addendum together),
        # not compute_signature(SKILL.md) directly. Cross-check it against
        # the loader's live read post-revert.
        assert result.live_signature == _live_signature("research")

        reporter.section("Proposal.applied_skill_signature updated to baseline")
        final = ProposalStore(root).get(p1)
        assert final.applied_skill_signature == result.live_signature
        assert final.status == "rolled_back"
        assert final.is_terminal

        reporter.section("EvolutionStore has new vN with rolled_back_from stamp")
        versions = await fresh_evo.list("research")
        assert versions
        latest = versions[0]
        reporter.kv("latest.version", latest.version)
        reporter.kv(
            "latest.params.rolled_back_from",
            latest.params.get("rolled_back_from"),
        )
        assert latest.params.get("rolled_back_from") == p1
        assert latest.params.get("baseline_signature") == result.live_signature
        assert latest.params.get("rolled_back_from_signature"), (
            "should capture the pre-rollback (proposed) signature for forensics"
        )
    finally:
        # Belt-and-suspenders: even if asserts fail, restore the live file.
        live.write_text(pre_rollback_text, encoding="utf-8")
    reporter.end()


@pytest.mark.asyncio
async def test_rollback_missing_baseline_raises(
    client, tmp_path: Path, reporter: Reporter
) -> None:
    from uteki_api.evolution.g2 import rollback_proposal
    from uteki_api.evolution.proposals.store import ProposalStore

    root = tmp_path / "proposals"
    p1 = await _seed_through_ab_eval(root)
    # Remove the snapshot so rollback has nothing to revert TO.
    (root / p1 / "snapshot" / "skill" / "SKILL.md").unlink()

    reporter.section("rollback with missing baseline → ValueError")
    with pytest.raises(ValueError, match="missing baseline"):
        await rollback_proposal(p1, by="cli:alice", store=ProposalStore(root))
    reporter.end()


# ── inconclusive ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inconclusive_keeps_live_marks_terminal(
    client, tmp_path: Path, reporter: Reporter
) -> None:
    from uteki_api.evolution.apply import _default_skill_root
    from uteki_api.evolution.g2 import inconclusive_proposal
    from uteki_api.evolution.proposals.store import ProposalStore

    root = tmp_path / "proposals"
    p1 = await _seed_through_ab_eval(root)
    live = _default_skill_root() / "research" / "SKILL.md"
    before = live.read_text(encoding="utf-8")

    reporter.section("inconclusive_proposal(...) — operator parks the proposal")
    result = await inconclusive_proposal(
        p1, by="cli:alice", reason="A/B sample size too small",
        store=ProposalStore(root),
    )
    assert result.ok
    assert result.final_status == "inconclusive"
    after = live.read_text(encoding="utf-8")
    assert after == before, "inconclusive should not touch the live file"

    final = ProposalStore(root).get(p1)
    assert final.status == "inconclusive"
    assert final.is_terminal
    reporter.end()


# ── shared guards ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_g2_verbs_refuse_without_ab_summary(
    client, tmp_path: Path, reporter: Reporter
) -> None:
    """Operator must have ab_summary in hand before making a G2 call."""
    from uteki_api.evolution.g2 import (
        adopt_proposal,
        inconclusive_proposal,
        rollback_proposal,
    )
    from uteki_api.evolution.proposals.store import ProposalStore

    root = tmp_path / "proposals"
    # Seed through apply but NOT through ab_eval — proposal is a_b_eval
    # but ab_summary is still None.
    p1 = _seed_with_snapshot(root, pid_label="alice")
    _accept(root, p1, by="cli:alice")
    await _apply_only(root, p1)
    assert ProposalStore(root).get(p1).ab_summary is None

    reporter.section("each verb refuses with 'no ab_summary yet'")
    for verb_fn in (adopt_proposal, rollback_proposal, inconclusive_proposal):
        with pytest.raises(ValueError, match="ab_summary"):
            await verb_fn(p1, by="cli:alice", store=ProposalStore(root))
    reporter.end()


# ── CLI ─────────────────────────────────────────────────────────────


def _cli_run(*args: str, env_extra: dict[str, str] | None = None, root: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "NO_COLOR": "1", "UTEKI_OPERATOR": "alice"}
    if env_extra:
        env.update(env_extra)
    cli = REPO_ROOT / "scripts" / "proposals"
    return subprocess.run(
        [str(cli), "--root", str(root), *args],
        check=False, capture_output=True, text=True, env=env, timeout=120,
    )


def test_cli_full_loop_pending_review_to_adopted(
    client, tmp_path: Path, reporter: Reporter
) -> None:
    """The headline closing demo: pending_review → adopted in two
    operator commands ('accept' + 'adopt'), all through the CLI."""
    root = tmp_path / "proposals"
    p1 = _seed_with_snapshot(root, pid_label="alice")

    reporter.section("./proposals accept (chains apply + ab_eval)")
    proc = _cli_run("accept", p1, "--reason", "drift pattern", root=root)
    assert proc.returncode == 0, proc.stderr
    assert "baseline:" in proc.stdout
    assert "proposed:" in proc.stdout

    reporter.section("./proposals adopt — G2 final call")
    proc2 = _cli_run("adopt", p1, "--reason", "delta non-negative, take it", root=root)
    reporter.kv("exit", proc2.returncode)
    reporter.kv("stdout", proc2.stdout)
    assert proc2.returncode == 0, proc2.stderr
    assert "a_b_eval" in proc2.stdout and "adopted" in proc2.stdout

    from uteki_api.evolution.proposals.store import ProposalStore
    final = ProposalStore(root).get(p1)
    assert final.status == "adopted"
    assert final.is_terminal

    reporter.section("show now renders the full 12-step trail")
    proc3 = _cli_run("show", p1, root=root)
    assert proc3.returncode == 0
    # Triage: the trail should mention every milestone.
    for milestone in ("triggered", "pending_review", "accepted",
                       "applying", "a_b_eval", "adopted"):
        assert milestone in proc3.stdout, f"missing {milestone} in show output"
    reporter.end()


def test_cli_rollback_exit_codes(
    client, tmp_path: Path, reporter: Reporter
) -> None:
    """CLI rollback happy path + error contracts."""
    root = tmp_path / "proposals"
    p1 = _seed_with_snapshot(root, pid_label="alice")

    reporter.section("rollback before A/B → exit 3 (wrong status)")
    proc = _cli_run("rollback", p1, root=root)
    assert proc.returncode == 3
    assert "expected a_b_eval" in proc.stderr

    reporter.section("walk through accept (chains apply + ab_eval)")
    accept = _cli_run("accept", p1, "--reason", "t16", root=root)
    assert accept.returncode == 0, accept.stderr

    reporter.section("./proposals rollback — G2 revert path")
    proc2 = _cli_run("rollback", p1, "--reason", "regressed", root=root)
    reporter.kv("exit", proc2.returncode)
    reporter.kv("stdout", proc2.stdout)
    assert proc2.returncode == 0, proc2.stderr
    assert "rolled_back" in proc2.stdout
    assert "live SKILL.md reverted to baseline" in proc2.stdout

    reporter.section("rollback again on terminal → exit 3 (wrong status)")
    proc3 = _cli_run("rollback", p1, root=root)
    assert proc3.returncode == 3
    reporter.end()


# Silence unused-import noise on the asyncio import (kept for explicitness).
_ = asyncio
