"""Run model — one bounded execution of a skill by the harness.

Captures who triggered the run, when it started/ended, the conversational
input that seeded it, every emitted `AgentEvent`, and a short summary. Stored
by `RunStore` so the API and frontend can list / inspect / diff runs.

M1.9 — status reshape:
``status`` used to mean "did this run finish without an infrastructure
problem?" but at the same time was the field everyone looked at for "was
this run good?". Pipeline runs that finished harness-OK but were rejected
by the evaluator looked identical to high-quality runs in /api/runs.

Split into three independent signals:

- ``harness_status``    — infrastructure layer: harness finished cleanly,
                          hit max_steps, hit max_cost, timed out, or crashed.
                          Values: running | ok | error | timeout.
                          This is the legacy ``status`` semantics; the old
                          field stays as a synonym so existing callers keep
                          working.
- ``evaluator_decision`` — quality gate from pipeline runs that include an
                          EvaluatorSkill pass. Populated from
                          eval-report.json's ``decision`` field at finish.
                          Values: approve | revise | reject | None
                          (None = no evaluator ran, e.g. leaf-skill runs).
- ``overall_assessment`` — operator-facing roll-up of the two above.
                          Values: passed | below_quality_bar | failed |
                          ok_no_judge | running.

The roll-up logic lives in ``_derive_overall_assessment`` below so writers
don't have to remember the mapping; harness sets harness_status +
evaluator_decision, then re-derives overall_assessment.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from uteki_api.schemas.events import AgentEvent

TriggeredBy = Literal["user", "cron", "event", "eval", "compare", "test"]
RunStatus = Literal["running", "ok", "error", "timeout"]
EvaluatorDecision = Literal["approve", "revise", "reject"]
OverallAssessment = Literal[
    "running",
    "passed",
    "below_quality_bar",
    "failed",
    "ok_no_judge",
]

# 010 — public surface visibility. Default `private`: owner promotes runs to
# `public` deliberately. `unlisted` = accessible by direct URL but not in
# anon-facing lists (Substack/gist-style share-by-link).
RunVisibility = Literal["private", "unlisted", "public"]


def derive_overall_assessment(
    harness_status: str,
    evaluator_decision: str | None,
) -> OverallAssessment:
    """Roll the two independent signals into one operator-facing verdict.

    The mapping is intentionally narrow so the UI only ever has to color
    five badges. Kept as a free function (not a Run method) so callers
    can compute it without instantiating a model — useful when the SQL
    layer is hydrating rows column-by-column.
    """
    if harness_status == "running":
        return "running"
    if harness_status != "ok":
        # timeout / error — infra failure dominates regardless of evaluator.
        return "failed"
    if evaluator_decision == "approve":
        return "passed"
    if evaluator_decision in {"revise", "reject"}:
        return "below_quality_bar"
    return "ok_no_judge"


class UsageSummary(BaseModel):
    """Aggregated token usage + cost across all `usage` events in a run."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0


class Run(BaseModel):
    id: str
    # M4: user that owns this run. ``system`` for platform-level evals.
    # Required — every Run must carry an owner; harness fails fast otherwise.
    user_id: str
    skill: str
    skill_version: str | None = None
    triggered_by: TriggeredBy
    trigger_reason: str = ""
    started_at: float
    ended_at: float | None = None
    # M1.9: status reshape — see module docstring. ``status`` stays as a
    # backward-compatible alias for ``harness_status`` so existing
    # consumers (tests, /api/runs UI, MCP) keep working without changes.
    status: RunStatus = "running"
    harness_status: RunStatus = "running"
    evaluator_decision: EvaluatorDecision | None = None
    overall_assessment: OverallAssessment = "running"
    user_input: str = ""
    summary: str = ""
    events: list[AgentEvent] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    usage_summary: UsageSummary = Field(default_factory=UsageSummary)
    # 013 — async LLM judge writes back here after the run finishes.
    # NULL = judge hasn't run yet / doesn't apply to this skill / disabled.
    # Aggregate (0.0–5.0) is the weighted blend of `score_breakdown`'s
    # per-axis values. The API masks both fields for callers without the
    # ``runs:annotate`` permission — see 013 design "reveal-after-label".
    auto_score: float | None = None
    score_breakdown: dict | None = None  # {"outcome": 4.2, "cost": 5.0, ...}
    # 010 — owner gates per-run visibility for the public surface.
    visibility: RunVisibility = "private"
