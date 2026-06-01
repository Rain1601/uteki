"""Quality drift watchdog + auto-trigger for the self-evolution loop (M1.11).

Reads recent ``EvalRecord`` entries and compares today's average pass_rate
against the same window 7 days ago. If today is ≥ 10 percentage points
worse, the monitor:

1. Logs a structured warning (legacy behavior).
2. **M1.11**: identifies the originating skill from the most recent run,
   checks there isn't already an in-flight proposal for that skill,
   creates a new Proposal stamped ``triggered_by=system:drift_monitor``,
   and runs ``cc_runner`` synchronously so the proposal lands at
   ``pending_review`` ready for G1 by the time check_drift returns.

Rate limit: per design/02 §V G1, each skill may have AT MOST one
in-flight proposal (non-terminal status). If one already exists,
auto-trigger silently skips so a sustained quality regression doesn't
spawn N parallel CC reviews fighting over the same SKILL.md.

Wired as a daily CronTrigger in ``triggers/registry.py``. Also runnable
manually via the CLI: ``./scripts/proposals drift-check``.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from uteki_api.eval.store import default_eval_history
from uteki_api.evolution.cc_runner import run_cc_review
from uteki_api.evolution.proposals import default_proposal_store
from uteki_api.runs import default_run_store

if TYPE_CHECKING:
    from uteki_api.eval.store import EvalRecord

logger = logging.getLogger(__name__)

DRIFT_THRESHOLD = 0.10  # 10 percentage-point drop


async def check_drift() -> dict:
    """Compare today vs 7-days-ago pass_rate, log + maybe auto-trigger.

    Return shape::

        {
          "today_count": int,
          "week_ago_count": int,
          "today_pass_rate": float | None,
          "week_ago_pass_rate": float | None,
          "drop": float | None,              # week - today
          "alert": bool,                     # drop > threshold
          "auto_triggered": str | None,      # proposal_id or None
          "auto_trigger_reason": str | None, # diagnostic if no proposal made
        }

    ``auto_triggered`` is None when ``alert is False`` OR when alert fired
    but auto-trigger was skipped (rate-limited / no source run / cc_runner
    crashed). ``auto_trigger_reason`` explains the skip.

    M4: drift_monitor is platform-level; it reads the ``"system"`` partition.
    Per-user trend lines stay where the user actually ran their evals.
    """
    recent = await default_eval_history.list_recent("system", limit=500)
    now = time.time()
    today = [r for r in recent if now - r.started_at < 86_400]
    week_ago = [
        r for r in recent if 6 * 86_400 < now - r.started_at < 8 * 86_400
    ]

    result: dict = {
        "today_count": len(today),
        "week_ago_count": len(week_ago),
        "today_pass_rate": None,
        "week_ago_pass_rate": None,
        "drop": None,
        "alert": False,
        "auto_triggered": None,
        "auto_trigger_reason": None,
    }

    if not today or not week_ago:
        logger.info(
            "drift check skipped: today=%d records, week_ago=%d records",
            len(today), len(week_ago),
        )
        return result

    today_rate = sum(r.pass_rate for r in today) / len(today)
    week_rate = sum(r.pass_rate for r in week_ago) / len(week_ago)
    drop = week_rate - today_rate

    result["today_pass_rate"] = today_rate
    result["week_ago_pass_rate"] = week_rate
    result["drop"] = drop

    if drop > DRIFT_THRESHOLD:
        result["alert"] = True
        logger.warning(
            "EVAL DRIFT: today %.0f%% vs 7d-ago %.0f%% (drop %.0f pp, threshold %.0f pp)",
            today_rate * 100, week_rate * 100, drop * 100, DRIFT_THRESHOLD * 100,
        )
        triggered, reason = await _maybe_auto_trigger(today, drop)
        result["auto_triggered"] = triggered
        result["auto_trigger_reason"] = reason
    else:
        logger.info(
            "drift OK: today %.0f%% vs 7d-ago %.0f%% (delta %.0f pp)",
            today_rate * 100, week_rate * 100, drop * 100,
        )
    return result


async def _maybe_auto_trigger(
    today_records: list[EvalRecord], drop: float
) -> tuple[str | None, str | None]:
    """If a drift alert fires, try to create a Proposal + run cc_runner.

    Returns ``(proposal_id, None)`` on success, ``(None, reason)`` when
    skipped (rate-limited / no source run / store error). Never raises —
    the caller (check_drift) treats this as best-effort and surfaces the
    reason in the returned dict.
    """
    # Pick the most recent today_record with a run_id — that's the run
    # the proposal will be "about". Falls back to ``None`` if no record
    # carries one (very early in the eval lifecycle).
    src_record = next(
        (
            r for r in sorted(today_records, key=lambda x: -x.started_at)
            if r.run_id
        ),
        None,
    )
    if src_record is None or not src_record.run_id:
        return None, "no today EvalRecord carried a run_id"

    # The run record is what gives us the skill name + ownership.
    try:
        run = await default_run_store.get(src_record.run_id, "system")
    except KeyError:
        return None, f"run_id {src_record.run_id!r} not found in system partition"
    except Exception as e:  # noqa: BLE001 — defensive
        logger.exception("drift_monitor: run_store lookup failed")
        return None, f"run_store lookup raised: {e}"

    # Rate-limit: refuse to spawn a second proposal for a skill that
    # already has one in-flight. Sustained regressions shouldn't pile up
    # N parallel CC reviews — wait for the human to clear the queue.
    try:
        existing = default_proposal_store.list(
            source_skill=run.skill, limit=50
        )
    except Exception as e:  # noqa: BLE001
        return None, f"proposal_store.list raised: {e}"
    in_flight = [p for p in existing if not p.is_terminal]
    if in_flight:
        logger.info(
            "drift_monitor: %d in-flight proposal(s) for skill=%s (e.g. %s), skipping auto-trigger",
            len(in_flight), run.skill, in_flight[0].proposal_id,
        )
        return None, (
            f"rate-limited: {len(in_flight)} in-flight proposal(s) for skill={run.skill!r}"
        )

    # All checks passed — create + drive through cc_runner.
    try:
        proposal = default_proposal_store.create(
            source_run_id=run.id,
            source_skill=run.skill,
            source_user_id="system",
            triggered_by="system:drift_monitor",
            trigger_reason=(
                f"pass_rate dropped {drop * 100:.1f}pp over 24h vs 7d-ago baseline"
            ),
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("drift_monitor: proposal create failed")
        return None, f"proposal create raised: {e}"

    logger.warning(
        "drift_monitor: AUTO-TRIGGERED %s for skill=%s run=%s drop=%.1fpp",
        proposal.proposal_id, run.skill, run.id, drop * 100,
    )

    try:
        await run_cc_review(proposal.proposal_id)
    except Exception as e:  # noqa: BLE001 — cc_runner already logs internally;
        # we surface so the caller's result["auto_trigger_reason"] explains
        # why pending_review didn't follow.
        logger.exception(
            "drift_monitor: cc_runner crashed for %s", proposal.proposal_id
        )
        return proposal.proposal_id, f"cc_runner raised: {e}"

    return proposal.proposal_id, None
