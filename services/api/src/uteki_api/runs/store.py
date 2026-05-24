"""RunStore — abstract persistence for `Run` records.

The harness creates a `Run` when execution begins, appends every event it
emits, and finalises it at `done` / `error`. The `InMemoryRunStore` keeps
runs in a dict ordered newest-first; production will swap in Postgres /
Mongo / etc. behind this same interface.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

from uteki_api.runs.models import Run, RunStatus
from uteki_api.schemas.events import AgentEvent


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
        limit: int = 50,
    ) -> list[Run]: ...


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
        limit: int = 50,
    ) -> list[Run]:
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
            out.append(run)
            if len(out) >= limit:
                break
        return out


default_run_store: RunStore = InMemoryRunStore()
