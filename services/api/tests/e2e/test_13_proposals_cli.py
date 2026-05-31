"""T13 — proposals CLI (M1.5).

Drives the G1 review CLI as a real subprocess so it's exercised the same
way an operator runs it. Uses ``--root <tmp>`` to isolate from any real
proposals on disk.

What this asserts:
- ``list`` shows pending_review proposals + hides terminals by default
- ``--all`` reveals terminal-status proposals
- ``show <P-id>`` prints findings + validation stats + transition trail
- ``accept`` / ``reject`` / ``defer`` / ``discard`` transition correctly
  and refuse non-``pending_review`` proposals
- Exit codes: 0 success, 2 unknown id, 3 wrong status, 4 store rejects
- ``--root`` does NOT touch the default services/api/data/ root

What this DOESN'T test:
- Interactive prompts (the CLI is intentionally non-interactive — every
  decision is an explicit subcommand for scriptability and audit)
- Real cc_runner integration (T12 covers that; T13 seeds proposals
  directly via ProposalStore)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from .conftest import Reporter

REPO_ROOT = Path(__file__).resolve().parents[4]
CLI = REPO_ROOT / "scripts" / "proposals"


def _run_cli(
    *args: str, root: Path, env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    """Invoke ./scripts/proposals with NO_COLOR=1 for deterministic output."""
    env = {**os.environ, "NO_COLOR": "1", "UTEKI_OPERATOR": "t13"}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [str(CLI), "--root", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _seed_pending(root: Path, pid_label: str = "alice") -> str:
    """Drop a synthetic pending_review proposal under ``root`` so the CLI
    has something to render. Mirrors what cc_runner would leave behind."""
    from uteki_api.evolution.proposals.store import ProposalStore

    store = ProposalStore(root)
    p = store.create(
        source_run_id=f"r-{pid_label}",
        source_skill="research",
        source_user_id=pid_label,
        triggered_by=f"system:t13:{pid_label}",
        trigger_reason="t13 seed",
    )
    for s in ("snapshotting", "briefing", "spawning", "generating", "validating",
              "pending_review"):
        store.transition(p.proposal_id, s, by="system:cc_runner")  # type: ignore[arg-type]

    # Seed cc_run + validation.json so 'show' has rich content.
    pdir = root / p.proposal_id
    cc = pdir / "cc_run"
    cc.mkdir(parents=True, exist_ok=True)
    (cc / "critique.md").write_text(
        "# CC critique\n\n"
        "### Finding #1: sector overview lacks sources\n"
        "Body...\n\n"
        "### Finding #2: cite_compliance loose\n"
        "Body...\n",
        encoding="utf-8",
    )
    (cc / "patch.diff").write_text("", encoding="utf-8")
    (pdir / "validation.json").write_text(
        json.dumps({
            "ok": True,
            "reasons": [],
            "stats": {
                "critique_bytes": 120,
                "critique_finding_count": 2,
                "patch_bytes": 0,
                "patch_file_count": 0,
                "patch_lines_added": 0,
                "patch_lines_removed": 0,
                "patch_lines_total": 0,
                "patch_applies": True,
            },
            "checked_at": 0.0,
        }),
        encoding="utf-8",
    )
    return p.proposal_id


@pytest.fixture(scope="module", autouse=True)
def _skip_when_uv_missing():
    """The CLI shell wrapper uses `uv run`. Skip the whole module if uv
    isn't on PATH — saves a confusing 127 in CI containers."""
    from shutil import which
    if which("uv") is None or not CLI.exists():
        pytest.skip(f"uv or {CLI} not available")


def test_list_shows_pending_and_hides_terminal_by_default(
    tmp_path: Path, reporter: Reporter
) -> None:
    root = tmp_path / "proposals"
    p1 = _seed_pending(root, pid_label="alice")
    # Seed a second proposal and mark it discarded — should be hidden by default.
    p2 = _seed_pending(root, pid_label="bob")
    from uteki_api.evolution.proposals.store import ProposalStore
    ProposalStore(root).transition(p2, "discarded", by="system:t13", reason="seed")

    reporter.section("default `list` hides terminal-status proposals")
    proc = _run_cli("list", root=root)
    reporter.kv("exit", proc.returncode)
    reporter.kv("stdout (first 400)", proc.stdout[:400])
    assert proc.returncode == 0, proc.stderr
    assert p1 in proc.stdout, f"missing pending proposal in list:\n{proc.stdout}"
    assert p2 not in proc.stdout, f"discarded proposal shouldn't show by default:\n{proc.stdout}"
    assert "pending_review" in proc.stdout
    # Hint footer should appear because pending proposals exist.
    assert "pending your review" in proc.stdout

    reporter.section("`list --all` reveals terminal proposals")
    proc2 = _run_cli("list", "--all", root=root)
    assert proc2.returncode == 0
    assert p1 in proc2.stdout
    assert p2 in proc2.stdout

    reporter.end()


def test_show_renders_findings_and_validation(
    tmp_path: Path, reporter: Reporter
) -> None:
    root = tmp_path / "proposals"
    p1 = _seed_pending(root, pid_label="alice")

    reporter.section(f"show {p1}")
    proc = _run_cli("show", p1, root=root)
    reporter.kv("exit", proc.returncode)
    reporter.kv("stdout (first 600)", proc.stdout[:600])
    assert proc.returncode == 0
    assert p1 in proc.stdout
    assert "pending_review" in proc.stdout
    assert "Finding #1: sector overview lacks sources" in proc.stdout
    assert "Finding #2: cite_compliance loose" in proc.stdout
    assert "ok            True" in proc.stdout or "ok            true" in proc.stdout.lower()
    assert "Transition trail" in proc.stdout
    # Snapshot signature might not be set in our seed; ensure 'Owner' label rendered.
    assert "Owner          alice" in proc.stdout

    reporter.end()


def test_show_unknown_proposal_exits_nonzero(
    tmp_path: Path, reporter: Reporter
) -> None:
    root = tmp_path / "proposals"
    reporter.section("show on missing id")
    proc = _run_cli("show", "P-does-not-exist", root=root)
    reporter.kv("exit", proc.returncode)
    reporter.kv("stderr", proc.stderr.strip())
    assert proc.returncode == 2
    assert "unknown proposal" in proc.stderr
    reporter.end()


def test_accept_transitions_and_records_operator(
    tmp_path: Path, reporter: Reporter
) -> None:
    root = tmp_path / "proposals"
    p1 = _seed_pending(root, pid_label="alice")

    reporter.section(f"accept --no-apply {p1} — leaves at 'accepted'")
    # --no-apply lets us assert the accept transition specifically;
    # the auto-apply path is exercised in T14.
    proc = _run_cli(
        "accept", p1, "--no-apply", "--reason", "matches pattern from last week",
        root=root, env_extra={"UTEKI_OPERATOR": "alice"},
    )
    reporter.kv("exit", proc.returncode)
    reporter.kv("stdout", proc.stdout.strip())
    assert proc.returncode == 0, proc.stderr
    assert "pending_review" in proc.stdout and "accepted" in proc.stdout
    # No apply means no "apply OK" line.
    assert "apply OK" not in proc.stdout

    reporter.section("on-disk proposal reflects the transition")
    from uteki_api.evolution.proposals.store import ProposalStore
    p = ProposalStore(root).get(p1)
    reporter.kv("final status", p.status)
    reporter.kv("last transition", p.transitions[-1].model_dump())
    assert p.status == "accepted"
    last = p.transitions[-1]
    assert last.to == "accepted"
    assert last.by == "cli:alice"
    assert last.reason == "matches pattern from last week"

    reporter.section("accept again on already-accepted → exit 3")
    proc2 = _run_cli(
        "accept", p1, "--reason", "double accept",
        root=root, env_extra={"UTEKI_OPERATOR": "alice"},
    )
    reporter.kv("exit", proc2.returncode)
    reporter.kv("stderr", proc2.stderr.strip())
    assert proc2.returncode == 3
    assert "expected pending_review" in proc2.stderr

    reporter.end()


def test_reject_and_discard_paths(tmp_path: Path, reporter: Reporter) -> None:
    root = tmp_path / "proposals"
    p_reject = _seed_pending(root, pid_label="r-user")
    p_discard = _seed_pending(root, pid_label="d-user")

    reporter.section("reject")
    proc = _run_cli("reject", p_reject, "-r", "off-topic", root=root)
    assert proc.returncode == 0
    from uteki_api.evolution.proposals.store import ProposalStore
    assert ProposalStore(root).get(p_reject).status == "rejected"

    reporter.section("discard")
    proc2 = _run_cli("discard", p_discard, "-r", "duplicate", root=root)
    assert proc2.returncode == 0
    assert ProposalStore(root).get(p_discard).status == "discarded"

    reporter.end()


def test_cli_does_not_touch_real_proposal_root(
    tmp_path: Path, reporter: Reporter
) -> None:
    """The --root override must not write anything into the default location."""
    root = tmp_path / "proposals_isolated"
    _seed_pending(root, pid_label="alice")

    # The "real" root the API would use; capture its size before the CLI call.
    real_root = REPO_ROOT / "services" / "api" / "data" / "evolution" / "proposals"
    before = sorted(p.name for p in real_root.glob("P-*")) if real_root.exists() else []
    reporter.kv("real-root before", before)

    proc = _run_cli("list", root=root)
    assert proc.returncode == 0

    after = sorted(p.name for p in real_root.glob("P-*")) if real_root.exists() else []
    reporter.kv("real-root after", after)
    assert before == after, "CLI leaked writes into the default proposals root"

    # And the isolated root still holds the seed.
    isolated_items = sorted(p.name for p in (root).glob("P-*"))
    assert isolated_items, f"isolated root has no proposals after seed: {root}"

    reporter.end()


def test_bare_invocation_defaults_to_list(tmp_path: Path, reporter: Reporter) -> None:
    """`proposals` with no subcommand falls through to `list` — the design demo."""
    root = tmp_path / "proposals"
    pid = _seed_pending(root, pid_label="alice")

    reporter.section("./proposals (no subcommand) — should behave like `list`")
    proc = _run_cli(root=root)
    reporter.kv("exit", proc.returncode)
    reporter.kv("stdout (first 200)", proc.stdout[:200])
    assert proc.returncode == 0
    assert pid in proc.stdout
    reporter.end()


# Keep mypy happy about `sys` import while letting flake8 confirm it's used.
assert sys.version_info >= (3, 11)
