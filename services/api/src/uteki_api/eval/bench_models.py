"""015 PR α · Eval workbench schema.

Two tables, both **admin-global** (not user-partitioned). Suites are a
shared baseline against which prompt-tuning experiments run; bench runs
are the per-execution journal. The child Run rows that fan out from a
bench run are still user-partitioned via the existing ``run`` table.

Why this is a new module instead of extending ``eval/cases``:

The existing /evals system (007) hand-picks synthetic case JSONs and
runs them as a regression suite. 015 inverts the polarity — production
runs become the eval signal, and the synthetic case path is being
retired (see 013-run-quality-eval). The data shapes don't overlap
enough to share a store. Once /evals is fully gone, ``eval/cases``
disappears too and ``eval/`` becomes the home of the workbench.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


def _suite_id() -> str:
    """Short hex id — readable + sortable by recency via prefix."""
    return uuid.uuid4().hex[:12]


def _bench_run_id() -> str:
    """Same shape as a regular run_id (12 hex) so URL handlers can route
    either kind through the same `_owner_id` pattern."""
    return uuid.uuid4().hex[:12]


class BenchmarkSuite(SQLModel, table=True):
    """A named collection of (ticker, peers, question) queries to run repeatedly.

    Not user-partitioned — suites are the admin's *yardsticks*, shared
    across the workbench. If we ever want private suites for non-admin
    users (Phase 2), add a ``user_id`` column then; first version is
    admin-only and a single seeded ``mega-cap baseline`` covers our
    primary use case.

    ``queries`` is stored as JSON; per-query shape:

        {"ticker": "GOOGL", "peers": ["MSFT", "META"], "question": "..."}

    Stored as JSON so future fields (asof_date / market segment / ...)
    don't need schema migrations.
    """

    __tablename__ = "benchmark_suite"

    id: str = Field(primary_key=True, default_factory=_suite_id, max_length=32)
    name: str = Field(max_length=128, index=True)
    description: str = Field(default="", max_length=2048)
    skill_name: str = Field(max_length=64, index=True)
    queries: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    # Cron schedule string (POSIX-style "0 6 * * *"); None disables auto-runs.
    # Validation is deferred to the scheduler (PR γ); this column only stores.
    cron_schedule: str | None = Field(default=None, max_length=64)
    # Soft-delete via `archived=True` instead of row deletion — bench_run
    # rows reference suite_id and we want history reachable for audit.
    archived: bool = Field(default=False, index=True)
    created_by: str = Field(max_length=64)  # user_id (informational, not FK)
    created_at: float = Field(default_factory=time.time, index=True)
    updated_at: float = Field(default_factory=time.time)


class BenchmarkRun(SQLModel, table=True):
    """One execution of a suite — either Mode A (quality, N=3) or Mode B (smoke, N=1).

    Lifecycle: queued → running → done | error | cancelled.

    ``run_ids`` is the list of child Run.id rows that this bench
    fanned out. N=3 × 10 queries × 2 versions = 60 child runs; N=1 × 10 × 1 = 10.

    ``metrics_summary`` is the aggregated matrix (median / mode / majority
    of the structural + behavioral + citation + judge dimensions per
    version) — Screen 3 of the UI binds directly to this JSON.

    ``approved_by`` / ``rejected_by`` capture the human decision (see
    anti-pattern rule: workbench surfaces signal, humans confirm).
    """

    __tablename__ = "benchmark_run"

    id: str = Field(primary_key=True, default_factory=_bench_run_id, max_length=32)
    suite_id: str = Field(foreign_key="benchmark_suite.id", index=True, max_length=32)
    mode: str = Field(max_length=16, index=True)  # "A_quality" | "B_smoke"
    skill_name: str = Field(max_length=64, index=True)
    skill_version_a: str = Field(max_length=32)  # baseline
    skill_version_b: str | None = Field(default=None, max_length=32)  # candidate; None for B-only
    n_per_query: int = Field(default=1, ge=1, le=10)
    temperature: float = Field(default=0.0)  # 0 for Mode B; prod default for Mode A
    triggered_by: str = Field(max_length=32, index=True)  # "user" | "cron" | "auto_hash"
    triggered_by_user_id: str = Field(max_length=64)
    triggered_at: float = Field(default_factory=time.time, index=True)
    finished_at: float | None = Field(default=None)
    status: str = Field(default="queued", max_length=16, index=True)
    # The 60 (or 10) child Run.id values, ordered by creation. Index into
    # the run table for full artifact + auto_score data.
    run_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    # Aggregated metric matrix. Shape — informally:
    #   {
    #     "structural": {"gate_completeness": {"a": 8.7, "b": 9.8, "delta": +12.6%}, ...},
    #     "behavioral": {...}, "citation": {...}, "judge": {...}, "cost": {...},
    #     "per_query": [{"ticker": "GOOGL", "a_action": "WATCH", "b_action": "BUY", ...}, ...],
    #     "stability": {"deterministic_pct": 0.93, "unstable": ["AAPL", "AMD"]},
    #   }
    # Populated by PR γ aggregator; PR α leaves it empty {}.
    metrics_summary: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    # Decision capture (anti-pattern rule: doesn't auto-deploy, just registers intent).
    approved_by: str | None = Field(default=None, max_length=64)
    approved_at: float | None = Field(default=None)
    rejected_by: str | None = Field(default=None, max_length=64)
    rejected_at: float | None = Field(default=None)
    rejected_reason: str = Field(default="", max_length=2048)
    error_message: str = Field(default="", max_length=4096)
