"""Quality drift watchdog.

Reads recent ``EvalRecord`` entries and compares today's average pass_rate
against the same window 7 days ago. If today is ≥ 10 percentage points
worse, emits a structured warning to the logger. M4+ will route that
warning to a user-configured webhook (Slack / DingTalk / etc.); for now
it just logs.

Wired as a daily CronTrigger in ``triggers/registry.py``.
"""

from __future__ import annotations

import logging
import time

from uteki_api.eval.store import default_eval_history

logger = logging.getLogger(__name__)

DRIFT_THRESHOLD = 0.10  # 10 percentage-point drop


async def check_drift() -> dict:
    """Return a dict describing the comparison; also log a warning on drift.

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
    }

    if not today or not week_ago:
        logger.info(
            "drift check skipped: today=%d records, week_ago=%d records",
            len(today),
            len(week_ago),
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
            today_rate * 100,
            week_rate * 100,
            drop * 100,
            DRIFT_THRESHOLD * 100,
        )
    else:
        logger.info(
            "drift OK: today %.0f%% vs 7d-ago %.0f%% (delta %.0f pp)",
            today_rate * 100,
            week_rate * 100,
            drop * 100,
        )
    return result
