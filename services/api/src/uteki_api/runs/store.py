"""RunStore — abstract persistence for `Run` records.

The harness creates a `Run` when execution begins, appends every event it
emits, and finalises it at `done` / `error`. Two implementations:

- ``InMemoryRunStore`` — process-local dict, ordered newest-first. Fast,
  ephemeral. Used in tests via the conftest singleton-rebind pattern.
- ``SqliteRunStore`` — persists to the shared SQLite DB. Visible across
  processes (the MCP server reads runs created by the HTTP server this
  way). In-flight runs are held in a process-local cache to honor the
  harness's mutate-then-finish pattern; finish() flushes everything to
  the DB row.

Selection happens at module load time via ``settings.run_store``
(``UTEKI_RUN_STORE=sqlite|memory``, defaults to ``sqlite`` in prod).
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from uteki_api.runs.models import Run, RunStatus, RunVisibility
from uteki_api.runs.sql_models import RunRow
from uteki_api.schemas.events import AgentEvent

logger = logging.getLogger(__name__)


class RunStore(ABC):
    """Run persistence.

    M4: every read/write is scoped by ``user_id``. The harness sets
    ``Run.user_id`` at creation; ``get(run_id, user_id)`` returns the run
    only if it belongs to that user (otherwise raises KeyError → 404 at the
    API layer). ``list`` always filters by user.

    Special ``user_id`` values:
      - any registered User.id → that user's runs
      - ``"system"`` → platform-level (eval / drift_monitor) runs
    """

    @abstractmethod
    async def create(self, run: Run) -> None: ...

    @abstractmethod
    async def append_event(self, run_id: str, event: AgentEvent) -> None: ...

    @abstractmethod
    async def finish(self, run_id: str, status: RunStatus, summary: str) -> None: ...

    @abstractmethod
    async def get(self, run_id: str, user_id: str | None = None) -> Run: ...

    @abstractmethod
    async def list(
        self,
        user_id: str,
        skill: str | None = None,
        triggered_by: str | None = None,
        visibility_filter: RunVisibility | list[RunVisibility] | None = None,
        limit: int = 50,
    ) -> list[Run]: ...

    @abstractmethod
    async def update_score(
        self,
        run_id: str,
        *,
        auto_score: float | None,
        score_breakdown: dict | None,
    ) -> None:
        """013 — write the async judge result onto an already-finished run.

        Called by ``eval/judges/dispatcher.py`` after the LLM judge returns.
        Idempotent: re-running the dispatcher for the same run overwrites
        prior scores in place. Doesn't touch any other Run field — the
        dispatcher knows nothing about events, status, etc.
        """
        ...

    @abstractmethod
    async def set_visibility(
        self, run_id: str, user_id: str, visibility: RunVisibility
    ) -> None:
        """Owner-scoped visibility flip. Raises KeyError if the run isn't
        owned by ``user_id`` (defense in depth — the API layer also gates
        the route on ``require_owner``)."""
        ...

    @abstractmethod
    async def delete(self, run_id: str, user_id: str) -> None:
        """Owner-scoped delete. Raises KeyError when the run isn't owned by
        ``user_id``. Drops the row and any in-process active cache entry;
        callers are responsible for purging artifacts via the ArtifactStore."""
        ...


class InMemoryRunStore(RunStore):
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._order: list[str] = []  # newest-first

    async def create(self, run: Run) -> None:
        if not run.user_id:
            raise ValueError("Run.user_id is required (M4)")
        self._runs[run.id] = run
        self._order.insert(0, run.id)

    async def append_event(self, run_id: str, event: AgentEvent) -> None:
        run = self._runs.get(run_id)
        if run is None:
            return
        run.events.append(event)

    async def finish(self, run_id: str, status: RunStatus, summary: str) -> None:
        run = self._runs.get(run_id)
        if run is None:
            return
        run.status = status
        run.summary = summary
        run.ended_at = time.time()

    async def get(self, run_id: str, user_id: str | None = None) -> Run:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(f"Unknown run: {run_id}")
        if user_id is not None and run.user_id != user_id:
            raise KeyError(f"Unknown run: {run_id}")
        return run

    async def list(
        self,
        user_id: str,
        skill: str | None = None,
        triggered_by: str | None = None,
        visibility_filter: RunVisibility | list[RunVisibility] | None = None,
        limit: int = 50,
    ) -> list[Run]:
        viz_set = _viz_filter_to_set(visibility_filter)
        out: list[Run] = []
        for rid in self._order:
            run = self._runs.get(rid)
            if run is None:
                continue
            if run.user_id != user_id:
                continue
            if skill is not None and run.skill != skill:
                continue
            if triggered_by is not None and run.triggered_by != triggered_by:
                continue
            if viz_set is not None and run.visibility not in viz_set:
                continue
            out.append(run)
            if len(out) >= limit:
                break
        return out

    async def set_visibility(
        self, run_id: str, user_id: str, visibility: RunVisibility
    ) -> None:
        run = self._runs.get(run_id)
        if run is None or run.user_id != user_id:
            raise KeyError(f"Unknown run: {run_id}")
        run.visibility = visibility

    async def update_score(
        self,
        run_id: str,
        *,
        auto_score: float | None,
        score_breakdown: dict | None,
    ) -> None:
        run = self._runs.get(run_id)
        if run is None:
            return  # dispatcher fired for a deleted run; silently no-op
        run.auto_score = auto_score
        run.score_breakdown = score_breakdown

    async def delete(self, run_id: str, user_id: str) -> None:
        run = self._runs.get(run_id)
        if run is None or run.user_id != user_id:
            raise KeyError(f"Unknown run: {run_id}")
        self._runs.pop(run_id, None)
        try:
            self._order.remove(run_id)
        except ValueError:
            pass


def _viz_filter_to_set(
    f: RunVisibility | list[RunVisibility] | None,
) -> set[str] | None:
    """Normalize filter shapes into a set for membership tests, or None to skip."""
    if f is None:
        return None
    if isinstance(f, str):
        return {f}
    return set(f)


class SqliteRunStore(RunStore):
    """Persist runs to the shared SQLite DB.

    Cross-process invariant:
    - ``create`` inserts a row immediately, so other procs see the run
      exists with ``status='running'``.
    - ``append_event`` does NOT touch the DB — events are buffered in
      this process's memory until ``finish``. Avoids 1000s of UPDATEs
      per run. Side effect: an in-flight run viewed from another proc
      shows ``events=[]`` (status visible, event log not).
    - ``finish`` flushes the full Run snapshot (events JSON, tags,
      usage_summary) to the row in one transaction.

    The harness's mid-flight mutation pattern (``await get(run_id)`` →
    mutate ``.tags`` / ``.usage_summary``) requires this process's
    ``get`` to return the SAME ``Run`` object across calls, so we hold
    in-flight runs in ``_active``. Mutations land on the cached
    instance; finish flushes it.

    Cross-process ``get`` for a run not in this proc's ``_active``
    cache loads from DB and returns a fresh snapshot.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        # Runs currently in-flight in THIS process. Keyed by run_id.
        # Harness mutates these in place; finish() flushes + evicts.
        self._active: dict[str, Run] = {}

    # ── (de)serialization helpers ───────────────────────────────────

    @staticmethod
    def _to_row(run: Run, events_override: list[AgentEvent] | None = None) -> RunRow:
        events = events_override if events_override is not None else run.events
        return RunRow(
            id=run.id,
            user_id=run.user_id,
            skill=run.skill,
            skill_version=run.skill_version,
            triggered_by=str(run.triggered_by),
            trigger_reason=run.trigger_reason,
            started_at=run.started_at,
            ended_at=run.ended_at,
            status=str(run.status),
            harness_status=str(run.harness_status),
            evaluator_decision=run.evaluator_decision,
            overall_assessment=str(run.overall_assessment),
            user_input=run.user_input,
            summary=run.summary,
            visibility=str(run.visibility),
            # 013 — async LLM judge result. Both NULL until dispatcher writes.
            auto_score=run.auto_score,
            score_breakdown_json=(
                json.dumps(run.score_breakdown) if run.score_breakdown is not None else None
            ),
            events_json=json.dumps([e.model_dump() for e in events]),
            tags_json=json.dumps(list(run.tags)),
            usage_summary_json=run.usage_summary.model_dump_json(),
        )

    @staticmethod
    def _from_row(row: RunRow) -> Run:
        # Pydantic round-trip for events + usage_summary; tags is a plain list.
        events = [AgentEvent.model_validate(e) for e in json.loads(row.events_json or "[]")]
        tags = list(json.loads(row.tags_json or "[]"))
        # UsageSummary lives on the Run model; rebuild via model_validate.
        from uteki_api.runs.models import UsageSummary

        usage = UsageSummary.model_validate_json(row.usage_summary_json or "{}")
        # M1.9 — old rows pre-ALTER will have None for harness_status; fall
        # back to legacy ``status`` so the Run object stays consistent.
        harness_status = row.harness_status or row.status or "running"
        overall = row.overall_assessment or "running"
        # Pre-010 rows may have NULL visibility — coerce to private (the
        # safe default; owner can promote later).
        visibility = row.visibility or "private"
        return Run(
            id=row.id,
            user_id=row.user_id,
            skill=row.skill,
            skill_version=row.skill_version,
            triggered_by=row.triggered_by,  # type: ignore[arg-type]
            trigger_reason=row.trigger_reason,
            started_at=row.started_at,
            ended_at=row.ended_at,
            status=row.status,  # type: ignore[arg-type]
            harness_status=harness_status,  # type: ignore[arg-type]
            evaluator_decision=row.evaluator_decision,  # type: ignore[arg-type]
            overall_assessment=overall,  # type: ignore[arg-type]
            user_input=row.user_input,
            summary=row.summary,
            events=events,
            tags=tags,
            usage_summary=usage,
            visibility=visibility,  # type: ignore[arg-type]
            # 013 — judge scores; NULL on pre-013 rows and on runs that
            # haven't been scored yet.
            auto_score=row.auto_score,
            score_breakdown=(
                json.loads(row.score_breakdown_json) if row.score_breakdown_json else None
            ),
        )

    # ── RunStore impl ───────────────────────────────────────────────

    async def create(self, run: Run) -> None:
        if not run.user_id:
            raise ValueError("Run.user_id is required (M4)")
        with Session(self._engine) as db:
            db.add(self._to_row(run))
            db.commit()
        # Cache the live Run object so the harness can mutate it.
        self._active[run.id] = run

    async def append_event(self, run_id: str, event: AgentEvent) -> None:
        # Buffer in memory. The cached Run is the same object the harness
        # holds; mutating its .events propagates to finish() naturally.
        run = self._active.get(run_id)
        if run is not None:
            run.events.append(event)

    async def finish(self, run_id: str, status: RunStatus, summary: str) -> None:
        run = self._active.get(run_id)
        if run is None:
            # Finalizing a run we don't have cached. Load, mutate, save.
            with Session(self._engine) as db:
                row = db.get(RunRow, run_id)
                if row is None:
                    logger.warning("finish() for unknown run_id=%s", run_id)
                    return
                row.status = str(status)
                row.summary = summary
                row.ended_at = time.time()
                db.add(row)
                db.commit()
            return

        run.status = status
        run.summary = summary
        run.ended_at = time.time()
        # Flush full snapshot
        with Session(self._engine) as db:
            existing = db.get(RunRow, run_id)
            fresh = self._to_row(run)
            if existing is None:
                db.add(fresh)
            else:
                # Update every column in place
                for col in (
                    "user_id", "skill", "skill_version", "triggered_by",
                    "trigger_reason", "started_at", "ended_at", "status",
                    "harness_status", "evaluator_decision", "overall_assessment",
                    "user_input", "summary", "visibility",
                    # 013 — judge fields. finish() flushes whatever's on
                    # the Run object; the async dispatcher (started here as
                    # fire-and-forget) updates them later via a separate
                    # store.update_score() call.
                    "auto_score", "score_breakdown_json",
                    "events_json", "tags_json", "usage_summary_json",
                ):
                    setattr(existing, col, getattr(fresh, col))
                db.add(existing)
            db.commit()
        # Evict from active cache
        self._active.pop(run_id, None)

    async def get(self, run_id: str, user_id: str | None = None) -> Run:
        # Live in-process run? Return the same object the harness is
        # mutating (essential for the mid-run usage_summary update path).
        live = self._active.get(run_id)
        if live is not None:
            if user_id is not None and live.user_id != user_id:
                raise KeyError(f"Unknown run: {run_id}")
            return live

        # Otherwise load from DB (the cross-process / post-finish path).
        with Session(self._engine) as db:
            row = db.get(RunRow, run_id)
            if row is None:
                raise KeyError(f"Unknown run: {run_id}")
            if user_id is not None and row.user_id != user_id:
                raise KeyError(f"Unknown run: {run_id}")
            return self._from_row(row)

    async def list(
        self,
        user_id: str,
        skill: str | None = None,
        triggered_by: str | None = None,
        visibility_filter: RunVisibility | list[RunVisibility] | None = None,
        limit: int = 50,
    ) -> list[Run]:
        viz_set = _viz_filter_to_set(visibility_filter)
        with Session(self._engine) as db:
            stmt = (
                select(RunRow)
                .where(RunRow.user_id == user_id)
                .order_by(RunRow.started_at.desc())
                .limit(limit)
            )
            if skill is not None:
                stmt = stmt.where(RunRow.skill == skill)
            if triggered_by is not None:
                stmt = stmt.where(RunRow.triggered_by == triggered_by)
            if viz_set is not None:
                stmt = stmt.where(RunRow.visibility.in_(viz_set))  # type: ignore[attr-defined]
            rows = db.exec(stmt).all()
        out: list[Run] = []
        for row in rows:
            # If this proc has the live version cached, prefer it (it has
            # mid-run events/tags the DB doesn't yet).
            live = self._active.get(row.id)
            out.append(live if live is not None else self._from_row(row))
        return out

    async def set_visibility(
        self, run_id: str, user_id: str, visibility: RunVisibility
    ) -> None:
        # Update both the cached live Run (if mid-flight) and the DB row.
        live = self._active.get(run_id)
        if live is not None and live.user_id == user_id:
            live.visibility = visibility
        with Session(self._engine) as db:
            row = db.get(RunRow, run_id)
            if row is None or row.user_id != user_id:
                raise KeyError(f"Unknown run: {run_id}")
            row.visibility = str(visibility)
            db.add(row)
            db.commit()

    async def update_score(
        self,
        run_id: str,
        *,
        auto_score: float | None,
        score_breakdown: dict | None,
    ) -> None:
        # 013 — written by the async judge dispatcher. No owner check:
        # the dispatcher is a platform-internal caller that already knows
        # the run id from finish()'s asyncio.create_task argument.
        score_json = json.dumps(score_breakdown) if score_breakdown is not None else None
        live = self._active.get(run_id)
        if live is not None:
            live.auto_score = auto_score
            live.score_breakdown = score_breakdown
        with Session(self._engine) as db:
            row = db.get(RunRow, run_id)
            if row is None:
                # Run got deleted between finish() and the judge returning.
                # Drop the result on the floor — there's no row to attach
                # it to and recreating one would be wrong.
                return
            row.auto_score = auto_score
            row.score_breakdown_json = score_json
            db.add(row)
            db.commit()

    async def delete(self, run_id: str, user_id: str) -> None:
        # Drop the DB row first, then evict any active cache entry. If the
        # row is owned by someone else the DB op raises KeyError before we
        # touch the cache.
        with Session(self._engine) as db:
            row = db.get(RunRow, run_id)
            if row is None or row.user_id != user_id:
                raise KeyError(f"Unknown run: {run_id}")
            db.delete(row)
            db.commit()
        self._active.pop(run_id, None)


def _build_default_run_store() -> RunStore:
    """Construct the platform default per settings.run_store.

    Falls back to InMemory if anything goes wrong instantiating SQLite
    (engine import failure, etc.) — the in-memory path keeps the API
    usable even with a misconfigured DB.
    """
    from uteki_api.core.config import settings

    if settings.run_store == "sqlite":
        try:
            from uteki_api.core.db import engine
            return SqliteRunStore(engine)
        except Exception:  # noqa: BLE001 — defensive boot path
            logger.exception("SqliteRunStore init failed; falling back to InMemory")
    return InMemoryRunStore()


default_run_store: RunStore = _build_default_run_store()
