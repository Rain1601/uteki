"""T17 — drift_monitor auto-trigger (M1.11).

Exercises the Phase 1 Gate: ``跑一个故意低质量 research run → 等 6 小时
(或手动 trigger drift_monitor.check_drift) → 看到 data/evolution/proposals/
P-2026-*/ 自动出现 → ./scripts/proposals review 看到 pending``.

What this asserts:
- check_drift() with a degraded today vs healthy week_ago triggers
  auto-creation of a Proposal stamped triggered_by=system:drift_monitor
- The proposal lands at pending_review (cc_runner ran inline)
- A second check_drift() call returns auto_triggered=None with reason
  ``rate-limited`` — per-skill in-flight cap honored
- check_drift() with healthy today vs healthy week_ago is a no-op
- check_drift() with insufficient data (no week_ago records) is a no-op
- CLI `proposals drift-check` surfaces the verdict in operator-readable
  form (drift line + auto-triggered line)

What this DOESN'T test:
- The Phase 1 cron schedule itself (apscheduler integration is M3.x)
- Per-skill granularity beyond the most-recent-run heuristic
- Slack/webhook notification (M3.x)
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path

import pytest

from .conftest import Reporter
from .test_13_proposals_cli import REPO_ROOT


async def _seed_run(skill: str, label: str) -> str:
    """Seed a fresh Run in the system partition, return its id."""
    from uteki_api.runs import Run, default_run_store
    from uteki_api.schemas.events import AgentEvent

    rid = f"t17-{label}"
    await default_run_store.create(
        Run(
            id=rid, user_id="system", skill=skill, triggered_by="eval",
            started_at=time.time(),
        )
    )
    await default_run_store.append_event(
        rid, AgentEvent(type="delta", run_id=rid, data={"text": "seed"})
    )
    await default_run_store.finish(rid, "ok", "t17 seed")
    return rid


async def _seed_eval_record(case_id: str, pass_rate: float, age_s: float, run_id: str | None) -> None:
    from uteki_api.eval.store import EvalRecord, default_eval_history

    await default_eval_history.append(
        "system",
        EvalRecord(
            case_id=case_id,
            started_at=time.time() - age_s,
            pass_rate=pass_rate,
            run_id=run_id,
        ),
    )


def _proposals_root() -> Path:
    """Where ``default_proposal_store`` writes — matches the CLI default."""
    api_root = Path(__file__).resolve().parents[2]
    return api_root / "data" / "evolution" / "proposals"


def _clean_proposals() -> None:
    """Wipe any proposals left by earlier tests so T17 starts from zero."""
    root = _proposals_root()
    if root.exists():
        import shutil
        shutil.rmtree(root)


@pytest.mark.asyncio
async def test_drift_auto_triggers_proposal_and_runs_cc_runner(
    client, reporter: Reporter
) -> None:
    """The headline scenario — degraded today vs healthy week_ago."""
    from uteki_api.eval.drift_monitor import check_drift
    from uteki_api.evolution.proposals import default_proposal_store

    _clean_proposals()
    # 6 today records at pass_rate 0.40, 6 week_ago records at 0.85.
    # Drop = 0.45 >> DRIFT_THRESHOLD (0.10).
    run_id = await _seed_run("research", label="degraded")
    for i in range(6):
        await _seed_eval_record(
            f"case-today-{i}", pass_rate=0.40, age_s=3600, run_id=run_id
        )
    for i in range(6):
        await _seed_eval_record(
            f"case-week-{i}", pass_rate=0.85, age_s=7 * 86_400, run_id=None
        )

    reporter.section("check_drift() — first call, should auto-trigger")
    result = await check_drift()
    reporter.kv("alert", result["alert"])
    reporter.kv("today_pass_rate", round(result["today_pass_rate"], 3))
    reporter.kv("week_ago_pass_rate", round(result["week_ago_pass_rate"], 3))
    reporter.kv("drop", round(result["drop"], 3))
    reporter.kv("auto_triggered", result["auto_triggered"])
    assert result["alert"] is True, "expected drift alert"
    assert result["auto_triggered"], (
        f"expected auto_triggered proposal_id, got reason={result['auto_trigger_reason']}"
    )

    reporter.section("proposal exists and walked through cc_runner to pending_review")
    pid = result["auto_triggered"]
    proposal = default_proposal_store.get(pid)
    reporter.kv("status", proposal.status)
    reporter.kv("source_skill", proposal.source_skill)
    reporter.kv("source_run_id", proposal.source_run_id)
    reporter.kv("triggered_by", proposal.transitions[0].by)
    assert proposal.status == "pending_review", (
        f"expected pending_review after cc_runner; got {proposal.status} "
        f"trail={[t.to for t in proposal.transitions]}"
    )
    assert proposal.source_skill == "research"
    assert proposal.source_run_id == run_id
    assert proposal.transitions[0].by == "system:drift_monitor"
    # The trigger_reason should mention the drift in pp.
    assert "pp" in proposal.transitions[0].reason

    reporter.section("rate-limit: second check_drift() must NOT spawn a sibling")
    result2 = await check_drift()
    reporter.kv("second auto_triggered", result2["auto_triggered"])
    reporter.kv("second reason", result2["auto_trigger_reason"])
    assert result2["alert"] is True
    assert result2["auto_triggered"] is None
    assert "rate-limited" in (result2["auto_trigger_reason"] or "")

    _clean_proposals()
    reporter.end()


@pytest.mark.asyncio
async def test_drift_check_quiet_when_no_drop(
    client, reporter: Reporter
) -> None:
    from uteki_api.eval.drift_monitor import check_drift

    _clean_proposals()
    run_id = await _seed_run("research", label="healthy")
    for i in range(4):
        await _seed_eval_record(
            f"case-today-{i}", pass_rate=0.80, age_s=3600, run_id=run_id
        )
    for i in range(4):
        await _seed_eval_record(
            f"case-week-{i}", pass_rate=0.82, age_s=7 * 86_400, run_id=None
        )

    reporter.section("check_drift() with delta within threshold")
    result = await check_drift()
    reporter.kv("alert", result["alert"])
    reporter.kv("drop", round(result["drop"], 3))
    assert result["alert"] is False
    assert result["auto_triggered"] is None
    _clean_proposals()
    reporter.end()


@pytest.mark.asyncio
async def test_drift_check_skips_with_insufficient_data(
    client, reporter: Reporter
) -> None:
    """A fresh deployment with no week-ago data shouldn't crash or trigger."""
    from uteki_api.eval.drift_monitor import check_drift

    _clean_proposals()
    run_id = await _seed_run("research", label="fresh")
    for i in range(3):
        await _seed_eval_record(
            f"case-today-{i}", pass_rate=0.40, age_s=3600, run_id=run_id
        )
    # No week_ago records.

    reporter.section("check_drift() with no week_ago records")
    result = await check_drift()
    reporter.kv("alert", result["alert"])
    reporter.kv("today_pass_rate", result["today_pass_rate"])
    assert result["alert"] is False
    assert result["auto_triggered"] is None
    assert result["today_pass_rate"] is None  # not enough data to compute
    _clean_proposals()
    reporter.end()


@pytest.mark.asyncio
async def test_drift_skips_when_no_run_id_in_today_records(
    client, reporter: Reporter
) -> None:
    """If today's eval records didn't carry a run_id we can't anchor a
    proposal — should alert but skip auto-trigger with a clear reason."""
    from uteki_api.eval.drift_monitor import check_drift

    _clean_proposals()
    for i in range(4):
        await _seed_eval_record(
            f"case-today-{i}", pass_rate=0.30, age_s=3600, run_id=None,
        )
    for i in range(4):
        await _seed_eval_record(
            f"case-week-{i}", pass_rate=0.85, age_s=7 * 86_400, run_id=None,
        )

    reporter.section("alert without run_id → skip")
    result = await check_drift()
    assert result["alert"] is True
    assert result["auto_triggered"] is None
    assert "run_id" in (result["auto_trigger_reason"] or "")
    _clean_proposals()
    reporter.end()


def test_cli_drift_check_renders_alert(
    client, reporter: Reporter
) -> None:
    """CLI subprocess wrapper — operator-driven manual trigger.

    The subprocess opens fresh module instances + a real SqliteRunStore +
    a real JsonFileEvalHistory. We can't write through the test's
    InMemory* rebinds — instead, seed directly into the on-disk stores
    the subprocess will read.
    """
    _clean_proposals()

    # Seed Run via SqliteRunStore so the subprocess can fetch it. The
    # client fixture's clean_data_dir already wiped the DB + recreated
    # an empty file; init_db() in the CLI startup ensures tables exist.
    async def go() -> str:
        import time as _time

        from sqlmodel import Session

        from uteki_api.core.db import engine, init_db
        from uteki_api.runs.sql_models import RunRow
        init_db()  # idempotent — guarantees tables before raw insert
        rid = "t17-cli-degraded"
        with Session(engine) as db:
            db.add(
                RunRow(
                    id=rid, user_id="system", skill="research",
                    triggered_by="eval", trigger_reason="",
                    started_at=_time.time(), ended_at=_time.time(),
                    status="ok", user_input="cli seed", summary="",
                    events_json="[]", tags_json="[]",
                    usage_summary_json='{"input_tokens":0,"output_tokens":0,'
                                        '"cache_read_tokens":0,'
                                        '"cache_creation_tokens":0,"cost_usd":0.0}',
                )
            )
            db.commit()
        # EvalHistory writes to ./data/users/system/eval-history; the
        # subprocess sees that file because it's on disk.
        for i in range(5):
            await _seed_eval_record(
                f"case-cli-today-{i}", pass_rate=0.45, age_s=3600, run_id=rid
            )
        for i in range(5):
            await _seed_eval_record(
                f"case-cli-week-{i}", pass_rate=0.85, age_s=7 * 86_400, run_id=None
            )
        return rid

    asyncio.run(go())

    cli = REPO_ROOT / "scripts" / "proposals"
    env = {**os.environ, "NO_COLOR": "1", "UTEKI_OPERATOR": "alice"}
    reporter.section("./proposals drift-check")
    proc = subprocess.run(
        [str(cli), "drift-check"],
        check=False, capture_output=True, text=True, env=env, timeout=60,
    )
    reporter.kv("exit", proc.returncode)
    reporter.kv("stdout", proc.stdout)
    assert proc.returncode == 0, proc.stderr
    assert "DRIFT alert" in proc.stdout
    assert "auto-triggered P-" in proc.stdout
    assert "next:" in proc.stdout  # follow-up hint shown

    # The proposal landed in the default root — verify it's at pending_review.
    from uteki_api.evolution.proposals import default_proposal_store
    items = default_proposal_store.list(source_skill="research", limit=10)
    assert items
    latest = items[0]
    assert latest.status == "pending_review"
    assert latest.transitions[0].by == "system:drift_monitor"

    _clean_proposals()
    reporter.end()


# Keep asyncio import live for tests above.
_ = asyncio
