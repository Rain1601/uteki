"""T14 — apply pipeline (M1.6).

Drives a proposal from ``accepted`` → ``a_b_eval`` via the apply pipeline.
Two flavors:

1. Direct ``apply_proposal`` invocation (in-process) — verifies the apply
   primitives: skill cache reload, EvolutionStore record, post_apply
   snapshot, ``Proposal.applied_skill_signature`` stamp.
2. Through the CLI: ``proposals accept`` (default = auto-apply) runs the
   full chain via subprocess and the operator-facing console output.

Both flavors use the empty-patch case because mock cc_runner produces an
empty patch and we want T14 to be hermetic. A non-empty-patch path runs
in M1.6 unit tests against a synthetic skill dir.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

from .conftest import Reporter
from .test_13_proposals_cli import REPO_ROOT, _seed_pending


def _accept_via_store(root: Path, proposal_id: str, *, by: str = "test") -> None:
    from uteki_api.evolution.proposals.store import ProposalStore
    ProposalStore(root).transition(proposal_id, "accepted", by=by, reason="t14 seed")


@pytest.mark.asyncio
async def test_apply_proposal_records_version_and_advances_to_a_b_eval(
    tmp_path: Path, reporter: Reporter
) -> None:
    """Direct apply_proposal call against a fresh in-process EvolutionStore."""
    from uteki_api.evolution.apply import apply_proposal
    from uteki_api.evolution.proposals.store import ProposalStore
    from uteki_api.evolution.store import InMemoryEvolutionStore

    root = tmp_path / "proposals"
    p1 = _seed_pending(root, pid_label="alice")
    _accept_via_store(root, p1, by="cli:alice")

    fresh_evo = InMemoryEvolutionStore()
    store = ProposalStore(root)

    reporter.section("apply_proposal(...) — empty patch, real research skill")
    result = await apply_proposal(p1, store=store, evolution_store=fresh_evo)
    reporter.kv("ok", result.ok)
    reporter.kv("final_status", result.final_status)
    reporter.kv("new_version", result.new_version)
    reporter.kv("applied_signature", result.applied_signature)
    reporter.kv("patch_was_empty", result.patch_was_empty)
    assert result.ok
    assert result.final_status == "a_b_eval"
    assert result.patch_was_empty is True
    assert result.new_version, "expected EvolutionStore to assign a version id"
    assert result.applied_signature, "expected applied_signature to be recorded"

    reporter.section("proposal state machine + applied_skill_signature stamped")
    final = store.get(p1)
    reporter.kv("status", final.status)
    reporter.kv("applied_skill_signature", final.applied_skill_signature)
    reporter.kv(
        "transition path",
        [t.to for t in final.transitions],
    )
    assert final.status == "a_b_eval"
    assert final.applied_skill_signature == result.applied_signature
    walked = {t.to for t in final.transitions}
    assert {"accepted", "applying", "a_b_eval"}.issubset(walked)

    reporter.section("EvolutionStore.list shows new SkillVersion")
    versions = await fresh_evo.list("research")
    reporter.kv("version count", len(versions))
    reporter.kv("latest.version", versions[0].version if versions else None)
    reporter.kv(
        "latest.params.applied_from_proposal",
        versions[0].params.get("applied_from_proposal") if versions else None,
    )
    assert versions, "expected at least one SkillVersion recorded"
    latest = versions[0]
    assert latest.version == result.new_version
    assert latest.skill == "research"
    assert latest.params.get("applied_from_proposal") == p1
    assert latest.parent_version is None  # fresh store, no parent

    reporter.section("post_apply/ snapshot written for rollback")
    post = root / p1 / "post_apply"
    assert (post / "skill" / "SKILL.md").exists(), \
        f"missing post_apply/skill/SKILL.md under {post}"
    assert (post / "signature").read_text(encoding="utf-8") == result.applied_signature

    reporter.section("apply_proposal refuses to re-fire on non-accepted")
    with pytest.raises(ValueError, match="expected accepted"):
        await apply_proposal(p1, store=store, evolution_store=fresh_evo)

    reporter.end()


@pytest.mark.asyncio
async def test_apply_proposal_apply_failed_on_bad_patch(
    tmp_path: Path, reporter: Reporter
) -> None:
    """Non-empty patch that won't apply → apply_failed (terminal)."""
    from uteki_api.evolution.apply import apply_proposal
    from uteki_api.evolution.proposals.store import ProposalStore
    from uteki_api.evolution.store import InMemoryEvolutionStore

    root = tmp_path / "proposals"
    p1 = _seed_pending(root, pid_label="alice")
    # Replace mock's empty patch with one that targets nonexistent content.
    bad_patch = (
        "--- a/snapshot/skill/SKILL.md\n"
        "+++ b/snapshot/skill/SKILL.md\n"
        "@@ -1,1 +1,1 @@\n"
        "-this line definitely does not exist in research SKILL.md\n"
        "+replacement\n"
    )
    (root / p1 / "cc_run" / "patch.diff").write_text(bad_patch, encoding="utf-8")
    _accept_via_store(root, p1, by="cli:alice")

    fresh_evo = InMemoryEvolutionStore()
    reporter.section("apply with mismatched patch context → apply_failed")
    result = await apply_proposal(
        p1, store=ProposalStore(root), evolution_store=fresh_evo
    )
    reporter.kv("ok", result.ok)
    reporter.kv("final_status", result.final_status)
    reporter.kv("error (first 100)", (result.error or "")[:100])
    assert result.ok is False
    assert result.final_status == "apply_failed"

    reporter.section("no SkillVersion recorded on apply_failed")
    versions = await fresh_evo.list("research")
    assert versions == [], "should not bump versions when apply fails"

    reporter.section("proposal terminal at apply_failed")
    final = ProposalStore(root).get(p1)
    assert final.status == "apply_failed"
    assert final.is_terminal

    reporter.end()


def test_cli_accept_auto_applies(tmp_path: Path, reporter: Reporter) -> None:
    """Full CLI subprocess: accept → auto-apply → proposal at a_b_eval."""
    root = tmp_path / "proposals"
    p1 = _seed_pending(root, pid_label="alice")

    cli = REPO_ROOT / "scripts" / "proposals"
    env = {**os.environ, "NO_COLOR": "1", "UTEKI_OPERATOR": "alice"}
    reporter.section(f"./proposals accept {p1} (no --no-apply)")
    proc = subprocess.run(
        [str(cli), "--root", str(root), "accept", p1, "--reason", "auto-apply demo"],
        check=False, capture_output=True, text=True, env=env, timeout=60,
    )
    reporter.kv("exit", proc.returncode)
    reporter.kv("stdout", proc.stdout)
    assert proc.returncode == 0, proc.stderr
    assert "accepted" in proc.stdout
    assert "applying patch..." in proc.stdout
    assert "apply OK" in proc.stdout
    assert "no-op — empty patch" in proc.stdout

    reporter.section("subprocess landed proposal at a_b_eval on disk")
    from uteki_api.evolution.proposals.store import ProposalStore
    final = ProposalStore(root).get(p1)
    reporter.kv("final status", final.status)
    reporter.kv("applied_signature", final.applied_skill_signature)
    assert final.status == "a_b_eval"
    assert final.applied_skill_signature

    reporter.section("apply subcommand on already-applied → exit 3")
    proc2 = subprocess.run(
        [str(cli), "--root", str(root), "apply", p1],
        check=False, capture_output=True, text=True, env=env, timeout=30,
    )
    reporter.kv("exit", proc2.returncode)
    reporter.kv("stderr", proc2.stderr.strip())
    assert proc2.returncode == 3
    assert "expected accepted" in proc2.stderr

    reporter.end()


def test_cli_apply_subcommand_after_no_apply(tmp_path: Path, reporter: Reporter) -> None:
    """`accept --no-apply` + `apply` two-step works (the edit-then-apply path)."""
    root = tmp_path / "proposals"
    p1 = _seed_pending(root, pid_label="alice")
    cli = REPO_ROOT / "scripts" / "proposals"
    env = {**os.environ, "NO_COLOR": "1", "UTEKI_OPERATOR": "alice"}

    reporter.section("accept --no-apply")
    proc = subprocess.run(
        [str(cli), "--root", str(root), "accept", p1, "--no-apply"],
        check=False, capture_output=True, text=True, env=env, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert "apply OK" not in proc.stdout

    reporter.section("apply explicitly")
    proc2 = subprocess.run(
        [str(cli), "--root", str(root), "apply", p1],
        check=False, capture_output=True, text=True, env=env, timeout=60,
    )
    reporter.kv("exit", proc2.returncode)
    reporter.kv("stdout", proc2.stdout)
    assert proc2.returncode == 0, proc2.stderr
    assert "apply OK" in proc2.stdout

    from uteki_api.evolution.proposals.store import ProposalStore
    assert ProposalStore(root).get(p1).status == "a_b_eval"

    reporter.end()


def test_apply_writes_signature_referencing_real_skill(
    tmp_path: Path, reporter: Reporter
) -> None:
    """The applied_signature matches what load_skill_prompt currently sees —
    i.e. apply actually picks up the live state of the skill on disk, not
    a stale cache."""
    from uteki_api.evolution.apply import apply_proposal
    from uteki_api.evolution.proposals.store import ProposalStore
    from uteki_api.evolution.store import InMemoryEvolutionStore
    from uteki_api.skills.loader import compute_signature, load_skill_prompt

    root = tmp_path / "proposals"
    p1 = _seed_pending(root, pid_label="alice")
    _accept_via_store(root, p1, by="cli:alice")

    expected_text, _refs = load_skill_prompt("research")
    expected_sig = compute_signature(expected_text)
    reporter.kv("expected signature", expected_sig)

    result = asyncio.run(
        apply_proposal(
            p1,
            store=ProposalStore(root),
            evolution_store=InMemoryEvolutionStore(),
        )
    )
    reporter.kv("apply result signature", result.applied_signature)
    assert result.applied_signature == expected_sig

    # And the validation.json from M1.4 is still present alongside.
    validation = json.loads((root / p1 / "validation.json").read_text())
    assert validation["ok"] is True
    reporter.end()
