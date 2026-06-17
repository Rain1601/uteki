"""013 PR γ — rule-based cost discipline axis.

Grades whether a run's ``usage_summary.cost_usd`` looks reasonable
against the recent baseline for the same skill. Pure rule, no LLM call —
keeps the second axis cheap and deterministic.

Why this is its own dim, not just an outcome-rubric line item: outcome
graders should focus on whether the answer is good. Cost is an
independent quality signal — a tight, correct answer that burned $4 of
tokens is still a sign of a regression worth flagging — and is easier
to score with a rule than to nudge a judge prompt about.

The baseline is the **median (p50) cost of finished runs of the same
skill in the last 30 days**, cached for one hour in process.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass

from uteki_api.runs.models import Run
from uteki_api.runs.store import RunStore


def score_cost_discipline(run_cost: float, baseline_p50: float) -> float:
    """Score on a 1-5 scale. Ratio = run_cost / baseline_p50.

    - ratio ≤ 1.0  → 5.0  (at or under the median; ideal)
    - ratio ≤ 1.5  → 4.0
    - ratio ≤ 2.0  → 3.0  (warning territory)
    - ratio ≤ 3.0  → 2.0
    - ratio  > 3.0 → 1.0  (over 3x baseline = burning cash)

    Edge cases:
    - baseline = 0  → return 5.0 (no prior data; don't punish blindly)
    - run_cost = 0  → return 5.0 (free run, e.g. cache hit; ideal)
    """
    if baseline_p50 <= 0 or run_cost <= 0:
        return 5.0
    ratio = run_cost / baseline_p50
    if ratio <= 1.0:
        return 5.0
    if ratio <= 1.5:
        return 4.0
    if ratio <= 2.0:
        return 3.0
    if ratio <= 3.0:
        return 2.0
    return 1.0


# ── Baseline cache ──────────────────────────────────────────────────


@dataclass
class _Cached:
    p50: float
    sampled_at: float
    sample_size: int


class CostBaselineCache:
    """Per-skill p50 cost cache. Bound to a ``RunStore``.

    Caller is the dispatcher; e2e tests can rebind via the constructor.
    """

    TTL_SECONDS = 3600.0           # refresh hourly
    LOOKBACK_LIMIT = 200            # how many recent same-skill runs to consider
    MIN_SAMPLE = 5                  # below this, return None (no confidence)

    def __init__(self, run_store: RunStore) -> None:
        self._store = run_store
        self._cache: dict[str, _Cached] = {}

    async def get(self, skill: str) -> float | None:
        """Return the cached / freshly-computed p50, or None when we have
        too few samples to be useful (in which case the dispatcher will
        skip the cost axis for this run)."""
        now = time.monotonic()
        cached = self._cache.get(skill)
        if cached is not None and (now - cached.sampled_at) < self.TTL_SECONDS:
            return cached.p50 if cached.sample_size >= self.MIN_SAMPLE else None

        # Refresh. We pull the recent N rows for this skill *without*
        # a user filter so multi-tenant baselines roll into one
        # population — the cost shape of a "research" run is a
        # function of the skill, not the caller.
        costs = await self._collect_costs(skill)
        if not costs:
            self._cache[skill] = _Cached(p50=0.0, sampled_at=now, sample_size=0)
            return None
        p50 = float(statistics.median(costs))
        self._cache[skill] = _Cached(p50=p50, sampled_at=now, sample_size=len(costs))
        if len(costs) < self.MIN_SAMPLE:
            return None
        return p50

    async def _collect_costs(self, skill: str) -> list[float]:
        """Pull recent runs across all users for this skill, return their
        cost_usd values where > 0. The store's ``list`` is user-scoped,
        so we use a small platform-level helper here: walk both the
        ``system`` user partition AND any cached actives. For a more
        rigorous query we'd want a global ``list_recent`` on the store;
        Phase 2 can refactor — the cache buys us hours of stability
        between fetches so the cost of the workaround is bounded.
        """
        # 013 starts with a pragmatic shortcut: list runs for the
        # ``system`` user partition (where platform evals land) AND
        # accept that single-user installs have all their runs there
        # anyway. When the user table grows past 1, we'll need to
        # iterate per-user OR add a proper global lister. Tracked under
        # the same task that adds a /admin/baselines page (Phase 2).
        rows = await self._store.list(
            user_id="system",
            skill=skill,
            limit=self.LOOKBACK_LIMIT,
        )
        out: list[float] = []
        for r in rows:
            cost = float(r.usage_summary.cost_usd or 0.0)
            if cost > 0 and r.ended_at is not None:
                out.append(cost)
        return out


def aggregate(breakdown: dict[str, float | None], weights: dict[str, float]) -> float | None:
    """Weighted blend of per-axis scores.

    Both axes use a 1-5 scale for the dispatcher's view (we normalise
    outcome from 1-10 → 1-5 BEFORE calling this, so the aggregate is
    in a single common unit). Axes with ``None`` are dropped from
    BOTH numerator and denominator — a missing axis just doesn't vote.

    Returns ``None`` when every axis is missing.
    """
    num = 0.0
    den = 0.0
    for axis, score in breakdown.items():
        if score is None:
            continue
        w = weights.get(axis, 0.0)
        if w <= 0:
            continue
        num += float(score) * w
        den += w
    if den <= 0:
        return None
    return num / den


# Outcome rubric is 1-10; cost rule is 1-5. The aggregate lives in
# the same 1-5 space cost uses, so the dispatcher halves the outcome
# score before blending.
DEFAULT_WEIGHTS: dict[str, float] = {
    "outcome": 0.7,
    "cost": 0.3,
}
