"""A/B eval driver for the self-evolution loop (M1.7).

Runs the eval suite twice — once against the just-applied proposed prompt,
once against the snapshotted baseline — and writes a structured
``ab_summary`` onto the proposal. Operator's G2 decision in M1.8 reads
this to choose adopted/rolled_back/inconclusive.

Approach: physical SKILL.md swap.

EvalRunner reads ``skill.system_prompt`` (bound by load_skill_prompt off
disk). To compare two prompt variants we temporarily restore the snapshot
SKILL.md to the live location, reload the skill, run the eval, then
restore the proposed prompt and reload again. Tradeoff: any in-flight
user run during the swap window sees the wrong prompt. Acceptable for
the design/05 dev flow because A/B fires right after the operator's
synchronous G1 accept — the operator is implicitly aware that prompt
state is changing.

Future hardening (not in M1.7):
- Inject a prompt override at the harness level so EvalRunner can pin
  a SKILL.md per call without touching disk.
- Concurrency lock to refuse new user runs while A/B is in flight.

ab_summary schema (lands on Proposal.ab_summary + heartbeat extra):

    {
        "cases_run": int,
        "pass_rate_baseline": float,
        "pass_rate_proposed": float,
        "delta_pp": float,                # (proposed - baseline) * 100
        "latency_ms_baseline_mean": float,
        "latency_ms_proposed_mean": float,
        "judge_score_baseline": dict[str, float],
        "judge_score_proposed": dict[str, float],
        "ran_at": float,
        "mode": "mock-llm" | "real-llm",  # follows settings.use_mock_llm
    }
"""

from __future__ import annotations

import logging
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from uteki_api.core.config import settings
from uteki_api.eval.runner import EvalRunner
from uteki_api.eval.store import default_eval_history
from uteki_api.evolution.proposals import default_proposal_store
from uteki_api.skills import default_skills
from uteki_api.skills.loader import load_skill_prompt

if TYPE_CHECKING:
    from uteki_api.eval.runner import EvalReport
    from uteki_api.evolution.proposals.store import ProposalStore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ABEvalResult:
    proposal_id: str
    ok: bool
    ab_summary: dict[str, Any]
    duration_s: float
    error: str | None = None


def _default_skill_root() -> Path:
    return Path(__file__).resolve().parent.parent / "skills"


def _live_skill_md(skill_root: Path, skill_name: str) -> Path:
    return skill_root / skill_name / "SKILL.md"


def _reload_skill(skill_name: str) -> None:
    """Same hot-reload hop apply.py uses — clear the loader cache + rebind
    skill.system_prompt off disk so the next EvalRunner pass sees the
    fresh file."""
    load_skill_prompt.cache_clear()
    try:
        skill = default_skills.get(skill_name)
    except KeyError:
        return
    if not hasattr(skill, "system_prompt"):
        return
    try:
        new_text, new_refs = load_skill_prompt(skill_name)
    except FileNotFoundError:
        return
    skill.system_prompt = new_text
    skill.refs = new_refs


async def _judge_score_mean(
    case_count: int, after_ts: float
) -> dict[str, float]:
    """Average judge scores from EvalHistory records appended since
    ``after_ts``. Returns empty dict when no judges fired."""
    if case_count == 0:
        return {}
    records = await default_eval_history.list_recent("system", limit=case_count * 4)
    rubric_totals: dict[str, list[int]] = {}
    for rec in records:
        if rec.started_at < after_ts:
            continue
        for rubric, score in (rec.judge_scores or {}).items():
            rubric_totals.setdefault(rubric, []).append(int(score))
    return {
        rubric: round(statistics.mean(scores), 2)
        for rubric, scores in rubric_totals.items()
        if scores
    }


def _latency_mean(report: EvalReport) -> float:
    if not report.results:
        return 0.0
    return round(
        statistics.mean(float(r.latency_ms) for r in report.results), 1
    )


# ── Public entry point ─────────────────────────────────────────────


async def run_ab_eval(
    proposal_id: str,
    *,
    store: ProposalStore | None = None,
    skill_root: Path | None = None,
) -> ABEvalResult:
    """Run the eval suite twice and write ab_summary onto the proposal.

    Refuses if the proposal isn't at ``a_b_eval`` (the state apply.py
    leaves it in). Refuses idempotency: once ab_summary is non-empty,
    re-running requires explicit ``force=True`` (not in MVP — operator
    can use `proposals ab-eval --force` in M1.7b).
    """
    pstore = store or default_proposal_store
    sroot = skill_root or _default_skill_root()
    started = time.time()

    proposal = pstore.get(proposal_id)
    if proposal.status != "a_b_eval":
        raise ValueError(
            f"ab_eval: proposal {proposal_id} is {proposal.status}, expected a_b_eval"
        )
    if proposal.ab_summary:
        raise ValueError(
            f"ab_eval: proposal {proposal_id} already has ab_summary; "
            "use `proposals ab-eval --force` to re-run"
        )

    proposal_dir = pstore._dir(proposal_id)  # noqa: SLF001
    live_skill_md = _live_skill_md(sroot, proposal.source_skill)
    snapshot_skill_md = proposal_dir / "snapshot" / "skill" / "SKILL.md"
    if not snapshot_skill_md.exists():
        raise ValueError(
            f"ab_eval: missing baseline at {snapshot_skill_md} — "
            "snapshot/ wasn't created (cc_runner skipped?)"
        )
    if not live_skill_md.exists():
        raise ValueError(
            f"ab_eval: missing live skill at {live_skill_md} — "
            "apply pipeline didn't populate"
        )

    # ── Pass 1 — PROPOSED (live state right now) ─────────────────
    # apply.py just left the proposed prompt on disk, so this is what
    # we're already running with. No swap needed for this pass.
    _reload_skill(proposal.source_skill)
    proposed_started = time.time()
    proposed_runner = EvalRunner(user_id="system")
    proposed_report = await proposed_runner.run_all()
    proposed_judge_scores = await _judge_score_mean(
        len(proposed_report.results), proposed_started
    )

    # ── Pass 2 — BASELINE (snapshot SKILL.md temporarily live) ───
    # Save the proposed prompt so we can restore it after.
    proposed_text = live_skill_md.read_text(encoding="utf-8")
    baseline_text = snapshot_skill_md.read_text(encoding="utf-8")
    swap_error: str | None = None
    try:
        live_skill_md.write_text(baseline_text, encoding="utf-8")
        _reload_skill(proposal.source_skill)
        baseline_started = time.time()
        baseline_runner = EvalRunner(user_id="system")
        baseline_report = await baseline_runner.run_all()
        baseline_judge_scores = await _judge_score_mean(
            len(baseline_report.results), baseline_started
        )
    except Exception as e:  # noqa: BLE001
        # Always try to restore — a failure mid-A/B must NOT leave the
        # live skill stuck on the baseline.
        swap_error = f"baseline pass failed: {e}"
        baseline_report = None  # type: ignore[assignment]
        baseline_judge_scores = {}
    finally:
        try:
            live_skill_md.write_text(proposed_text, encoding="utf-8")
            _reload_skill(proposal.source_skill)
        except Exception:  # noqa: BLE001
            logger.exception(
                "ab_eval: FAILED to restore proposed SKILL.md for %s — "
                "live skill may be on the baseline now!", proposal_id
            )

    if swap_error or baseline_report is None:
        pstore.transition(
            proposal_id,
            "a_b_eval",
            by="system:ab_eval",
            reason=swap_error or "baseline pass returned no report",
            extra={"ab_eval_error": swap_error},
        )
        return ABEvalResult(
            proposal_id=proposal_id,
            ok=False,
            ab_summary={},
            duration_s=time.time() - started,
            error=swap_error,
        )

    # ── Assemble ab_summary ──────────────────────────────────────
    proposed_pr = proposed_report.pass_rate
    baseline_pr = baseline_report.pass_rate
    ab_summary: dict[str, Any] = {
        "cases_run": len(proposed_report.results),
        "pass_rate_baseline": round(baseline_pr, 4),
        "pass_rate_proposed": round(proposed_pr, 4),
        "delta_pp": round((proposed_pr - baseline_pr) * 100, 2),
        "latency_ms_baseline_mean": _latency_mean(baseline_report),
        "latency_ms_proposed_mean": _latency_mean(proposed_report),
        "judge_score_baseline": baseline_judge_scores,
        "judge_score_proposed": proposed_judge_scores,
        "ran_at": time.time(),
        "mode": "mock-llm" if settings.use_mock_llm else "real-llm",
    }

    # Persist onto the proposal record itself + write a heartbeat
    # transition so decisions/<NNN>-a_b_eval.json captures the data.
    proposal = pstore.get(proposal_id)
    proposal.ab_summary = ab_summary
    pstore._persist(proposal)  # noqa: SLF001
    pstore.transition(
        proposal_id,
        "a_b_eval",
        by="system:ab_eval",
        reason=(
            f"pass_rate {baseline_pr:.2f} → {proposed_pr:.2f} "
            f"({ab_summary['delta_pp']:+.1f} pp) over {ab_summary['cases_run']} cases"
        ),
        extra={"ab_summary": ab_summary},
    )

    logger.info(
        "ab_eval %s: baseline=%.3f proposed=%.3f delta=%+.1fpp cases=%d",
        proposal_id, baseline_pr, proposed_pr, ab_summary["delta_pp"],
        ab_summary["cases_run"],
    )
    return ABEvalResult(
        proposal_id=proposal_id,
        ok=True,
        ab_summary=ab_summary,
        duration_s=time.time() - started,
    )


__all__ = ["ABEvalResult", "run_ab_eval"]
