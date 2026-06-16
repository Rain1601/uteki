"""013 · Post-run judge dispatcher.

Fires *after* ``RunStore.finish()`` returns. Owns:

  1. Deciding whether this run should be judged at all (skill filter,
     mock-LLM short-circuit, settings flag).
  2. Calling each enabled judge (outcome live; cost added in PR γ).
  3. Folding per-axis scores into the aggregate ``auto_score`` (PR γ).
  4. Persisting via ``RunStore.update_score`` — never via direct row writes.

Failure-mode policy: never raise back to the harness. A judge that times
out, returns garbage, or hits a stale API key drops to a neutral 5 on its
axis and logs; the run itself stays whatever status the harness gave it.
"""

from __future__ import annotations

import logging
from typing import Any

from uteki_api.core.config import settings
from uteki_api.eval.judges.runner import JudgeRunner, default_judge_runner
from uteki_api.runs import default_run_store
from uteki_api.runs.models import Run
from uteki_api.runs.store import RunStore

logger = logging.getLogger(__name__)

# Skills whose runs the judge should look at. Restricting the set keeps the
# (eval, drift_monitor, e2e fixture, mcp-smoke) runs out of the judge's
# inbox — those are infrastructure runs, not product runs. Add a skill
# here once its outputs are stable enough to be worth grading.
DEFAULT_JUDGE_TARGETS: tuple[str, ...] = (
    "research",
    "company_research_pipeline",
)


class JudgeDispatcher:
    """Spawn-and-forget judge runner. One instance per process.

    Bound to a ``RunStore`` at construction so the e2e suite can rebind
    the store without re-importing this module.
    """

    def __init__(
        self,
        run_store: RunStore | None = None,
        runner: JudgeRunner | None = None,
        targets: tuple[str, ...] = DEFAULT_JUDGE_TARGETS,
    ) -> None:
        self.run_store = run_store
        self.runner = runner or default_judge_runner
        self.targets = targets

    def _store(self) -> RunStore:
        # Lazy lookup so per-test rebinds in conftest hit. If the caller
        # passed an explicit store at construction, respect that.
        return self.run_store or default_run_store

    # ── eligibility ──────────────────────────────────────────────────

    def _should_score(self, run: Run) -> tuple[bool, str]:
        if not settings.run_eval_enabled:
            return False, "run_eval_enabled=False"
        if settings.use_mock_llm:
            # Mock-LLM runs are placebos — every event is a canned reply,
            # there's nothing meaningful for an LLM judge to grade. Skip
            # without warnings so the test suite stays quiet.
            return False, "use_mock_llm=True"
        if run.skill not in self.targets:
            return False, f"skill {run.skill!r} not in targets"
        if run.triggered_by in ("eval", "test"):
            # Eval / regression-test runs shouldn't feed back into the
            # production scoring stream; they have their own per-case
            # judge in eval/runner.py.
            return False, f"triggered_by={run.triggered_by!r}"
        return True, "ok"

    # ── main entry ───────────────────────────────────────────────────

    async def score(self, run_id: str) -> None:
        """Score one run. Idempotent — re-running overwrites prior scores."""
        try:
            run = await self._store().get(run_id)
        except KeyError:
            logger.warning("dispatcher.score: unknown run_id=%s", run_id)
            return

        ok, reason = self._should_score(run)
        if not ok:
            logger.debug("dispatcher.score skipped run_id=%s: %s", run_id, reason)
            return

        # PR γ will gather outcome + cost in parallel here. For now just
        # outcome, returned-as-exception-isolated so the same shape works
        # when cost arrives.
        outcome = await self._score_outcome(run)
        breakdown: dict[str, Any] = {"outcome": outcome}

        # MVP aggregate: outcome only. PR γ swaps in the weighted blend.
        aggregate = outcome if isinstance(outcome, (int, float)) else None

        try:
            await self._store().update_score(
                run_id,
                auto_score=aggregate,
                score_breakdown=breakdown,
            )
        except Exception:  # noqa: BLE001
            logger.exception("dispatcher.score: persist failed for %s", run_id)

    # ── outcome axis ─────────────────────────────────────────────────

    async def _score_outcome(self, run: Run) -> float | None:
        """LLM judge against ``outcome.md`` rubric. Returns a score on the
        rubric's 1-10 scale, or ``None`` if the judge couldn't run.

        We feed the judge ONLY the user_input + summary + primary artifact
        text. Per the rubric, trajectory is out of scope here.
        """
        draft = await self._collect_outcome_draft(run)
        if not draft.strip():
            logger.info("dispatcher.score: no draft for run_id=%s; skipping outcome", run.id)
            return None

        # Avoid having the same model self-judge: if the run was driven by
        # an Anthropic-family model, prefer non-Anthropic judges from the
        # rubric's preference list.
        avoid = run.skill_version  # rough hint; runner picks the first
        # configured non-avoid candidate from the rubric's preference list.
        try:
            result = await self.runner.judge(
                "outcome",
                draft_text=draft,
                run_events=[e.model_dump() for e in run.events],
                avoid_model=avoid,
            )
        except Exception:  # noqa: BLE001 — runner is supposed to be safe; defense in depth
            logger.exception("outcome judge raised for run_id=%s", run.id)
            return None

        return float(result.score_1_to_10)

    async def _collect_outcome_draft(self, run: Run) -> str:
        """Stitch user_input + summary + primary artifact body into one
        prompt-friendly draft. Artifacts are best-effort: if the read
        fails, we still score off summary alone."""
        parts: list[str] = []
        if run.user_input:
            parts.append(f"## USER ASKED\n{run.user_input.strip()}")
        if run.summary:
            parts.append(f"## AGENT SUMMARY\n{run.summary.strip()}")

        body = await self._read_primary_artifact(run)
        if body:
            parts.append(f"## PRIMARY ARTIFACT\n{body}")

        return "\n\n".join(parts)

    async def _read_primary_artifact(self, run: Run) -> str:
        """Return the primary artifact's text body (truncated), or empty
        string if there isn't one / it can't be read."""
        from uteki_api.artifacts import default_artifact_store

        try:
            artifacts = await default_artifact_store.list(run.id, run.user_id)
        except Exception:  # noqa: BLE001
            return ""
        if not artifacts:
            return ""
        # Same precedence as api/runs.py:_primary_artifact for consistency.
        primary = None
        for a in artifacts:
            if a.role == "primary":
                primary = a
                break
        if primary is None:
            for name in ("final-report.md", "investment-memo.md", "final-research.md", "research.md"):
                for a in artifacts:
                    if a.name == name:
                        primary = a
                        break
                if primary is not None:
                    break
        if primary is None:
            primary = artifacts[0]

        try:
            _meta, body = await default_artifact_store.read(
                run.id, primary.name, run.user_id
            )
        except Exception:  # noqa: BLE001
            return ""
        try:
            text = body.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return ""
        # Judge prompts get huge if we feed a 50-page memo; the rubric
        # is about decision-readiness, not exhaustive coverage. 16K is
        # ample to assess the top of a deliverable.
        return text[:16_000]


default_judge_dispatcher = JudgeDispatcher()
