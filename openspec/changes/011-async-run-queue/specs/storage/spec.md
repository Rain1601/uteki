## ADDED Requirements

### Requirement: New capability — `RunEventStore` (append-only run event log)

A new store, **`RunEventStore`**, SHALL provide an append-only event log per run, with monotonic `seq` allocation and condition-based subscription for live tailing. It is a **sibling** of the existing `RunStore`, not a replacement — both stores coexist during the dual-write window.

#### Scenario: Store has a defined ABC

The store SHALL expose this abstract interface:

```python
class RunEventStore(ABC):
    async def append(self, run_id: str, user_id: str, event: AgentEvent) -> int
    async def read_from(self, run_id: str, from_seq: int, *, limit: int | None = None) -> list[tuple[int, AgentEvent]]
    async def subscribe(self, run_id: str, from_seq: int) -> AsyncIterator[tuple[int, AgentEvent]]
    async def latest_seq(self, run_id: str) -> int | None
    async def is_terminal(self, run_id: str) -> bool
```

- **AND** two implementations SHALL be provided: `InMemoryRunEventStore` (used in tests) and `SqliteRunEventStore` (used in dev + prod)
- **AND** the default impl is selected at module-load time via `settings.run_event_store` (`UTEKI_RUN_EVENT_STORE=sqlite|memory`)
- **AND** the default value matches `UTEKI_RUN_STORE`

#### Scenario: Append assigns monotonic seq

- **GIVEN** `run_id` has previously had N events appended
- **WHEN** `append(run_id, user_id, event)` is called
- **THEN** the new event SHALL be persisted at `seq = N`
- **AND** the call SHALL return `seq`
- **AND** the next event for the same `run_id` SHALL receive `seq = N + 1`

#### Scenario: Append after terminal raises

- **GIVEN** the latest event for `run_id` has `type in {"done", "error"}`
- **WHEN** `append(run_id, user_id, event)` is called again
- **THEN** the store SHALL raise `TerminalEventLogClosed`
- **AND** no row SHALL be inserted

#### Scenario: Duplicate (run_id, seq) raises

- **GIVEN** a row with `(run_id, seq=K)` exists
- **WHEN** any caller attempts to insert a second row at `(run_id, K)`
- **THEN** the store SHALL raise `EventLogConflict` (defense in depth — the DB primary key prevents this physically)

#### Scenario: read_from is ordered and bounded

- **WHEN** `read_from(run_id, from_seq=N)` is called
- **THEN** events with `seq >= N` SHALL be returned in ascending `seq` order
- **AND** if `limit` is provided, at most `limit` events SHALL be returned

#### Scenario: subscribe yields catch-up then live tail

- **WHEN** `subscribe(run_id, from_seq=N)` is called
- **THEN** Phase 1: all events with `seq >= N` already in the store SHALL be yielded in order
- **AND** Phase 2: the iterator SHALL await an `asyncio.Condition` per run_id; on each `append` to the same `run_id`, the iterator SHALL yield the newly appended event(s) (catching up via `read_from` from the last yielded seq + 1)
- **AND** the iterator SHALL close after yielding an event whose `type in {"done", "error"}`

#### Scenario: subscribe on already-terminal run replays then closes

- **GIVEN** a run whose latest event is `done` at `seq=42`
- **WHEN** a fresh subscriber calls `subscribe(run_id, from_seq=0)`
- **THEN** events 0..42 SHALL be yielded in order
- **AND** the iterator SHALL close cleanly after yielding event 42
- **AND** no Condition wait SHALL be entered (pure replay path)

### Requirement: `RunEventStore` table schema

The SQLite + Postgres backing table SHALL be:

```python
class RunEventRow(SQLModel, table=True):
    __tablename__ = "run_events"

    run_id:    str   = Field(primary_key=True, index=True)
    seq:       int   = Field(primary_key=True)
    user_id:   str   = Field(index=True)   # denormalized from Run.user_id
    type:      str
    data_json: str
    ts:        float = Field(index=True)
```

#### Scenario: Primary key is composite

- **WHEN** the migration runs
- **THEN** the table SHALL have a composite primary key on `(run_id, seq)`
- **AND** two secondary indexes: `ix_run_events_user_id`, `ix_run_events_ts`

#### Scenario: No FK to `run` table

- **WHEN** the migration runs
- **THEN** no foreign key constraint SHALL be declared between `run_events.run_id` and `run.id`
- **AND** consistency is maintained by the application layer (the run row is created before any event append, see harness spec delta)
- **AND** this avoids cascading delete surprises and keeps the event log resilient if `run` table maintenance happens

### Requirement: `user_id` denormalized into `run_events` for ownership checks

The `run_events` table SHALL carry `user_id` redundantly (also present on the parent `Run`). This allows ownership checks at the events route without joining `run`.

#### Scenario: Ownership check uses `_owner_id` helper

- **GIVEN** the API route `GET /api/runs/{run_id}/events`
- **WHEN** the route handler processes the request
- **THEN** it SHALL call the shared `_owner_id(run_id, user)` helper (already used by `api/artifacts.py`) which resolves ownership against the `Run` row
- **AND** if ownership is denied (private run, non-owner user), the route SHALL return 404 (same shape as "run does not exist")

### Requirement: New capability — `RunQueue` (run worker dispatch)

A new abstraction, **`RunQueue`**, SHALL own the lifecycle of an agent run's worker. The interface is process-agnostic; the MVP impl is single-process `asyncio.create_task`, and future Redis/Arq/Celery backends SHALL drop in without changing route handlers.

#### Scenario: ABC interface

```python
class RunQueue(ABC):
    async def enqueue(self, spec: RunSpec) -> str  # returns run_id
    async def cancel(self, run_id: str) -> bool    # best-effort; NotImplementedError in MVP
```

- **AND** `RunSpec` is a frozen dataclass with fields `(user_id, agent, messages, session_id, model, as_of, triggered_by, trigger_reason)` — all JSON-serializable
- **AND** a singleton `default_run_queue` is exposed from `runs/__init__.py`

#### Scenario: enqueue creates Run row synchronously

- **WHEN** `RunQueue.enqueue(spec)` is called
- **THEN** the call SHALL synchronously create a `Run` row in `RunStore` with `status="pending"`
- **AND** the call SHALL then spawn a worker task (impl-dependent)
- **AND** the call SHALL return the new `run_id`
- **AND** the call SHALL return before any event has been appended to `RunEventStore`

#### Scenario: Worker drives harness to terminal

- **GIVEN** an enqueued `RunSpec`
- **WHEN** the worker task runs
- **THEN** it SHALL build a harness from the spec
- **AND** drive `harness.run(spec.messages, session_id=spec.session_id)` to completion
- **AND** if the harness raises before emitting a terminal event, the worker SHALL append an `error` event to `RunEventStore` so subscribers do not hang

#### Scenario: Worker is unaffected by HTTP disconnect

- **GIVEN** the worker is mid-execution
- **WHEN** any subscriber to `GET /api/runs/{run_id}/events` disconnects
- **THEN** the worker SHALL continue uninterrupted
- **AND** all subsequent events SHALL still be appended to the event log

## MODIFIED Requirements

### Requirement: Storage partitioning table includes `RunEventStore`

The "Storage — spec" table that lists user-owned stores and their partition keys SHALL be extended:

| Store | Partition key | Implementation | Path |
|---|---|---|---|
| RunStore | `Run.user_id` column | `InMemoryRunStore`, `SqliteRunStore` | in-process / SQLite |
| **RunEventStore (NEW)** | **`run_events.user_id` column (denormalized)** | **`InMemoryRunEventStore`, `SqliteRunEventStore`** | **in-process / SQLite** |
| ArtifactStore | path prefix `data/users/<user_id>/runs/...` | `LocalFileArtifactStore` | filesystem |
| Memory (short-term) | dict key `(user_id, session_id)` | `InMemoryStore` | in-process |
| EvalHistoryStore | path prefix `data/users/<user_id>/eval-history/...` | `JsonFileEvalHistory` | filesystem |

#### Scenario: Cross-user isolation for events

- **GIVEN** users A and B; A has a private run with id `R`
- **WHEN** user B calls `GET /api/runs/R/events`
- **THEN** the API SHALL return 404 (same shape as "does not exist")
- **AND** B's request SHALL NOT discover the existence of `R`

#### Scenario: Anonymous access to public-run events

- **GIVEN** user A's run `R` has `visibility = "public"` (010)
- **WHEN** an anonymous client calls `GET /api/runs/R/events`
- **THEN** the API SHALL stream the full event log
- **AND** the ownership helper SHALL pass anonymous access through the same way it does for `/api/runs/R` and `/api/runs/R/artifacts/*`

## ADDED Requirements (continued)

### Requirement: Conftest singleton-replacement covers the new stores

`tests/e2e/conftest.py` rebinds `default_run_store` and `default_memory` on every module that imports them by name (per the existing M4 pattern). The same conftest SHALL also rebind:

- `default_run_event_store` on every importing module (`agents/harness`, `api/agent`, `api/runs`, `runs/queue`)
- `default_run_queue` on every importing module (`api/agent`)

#### Scenario: Test isolation between cases

- **WHEN** two tests run sequentially in the same process
- **THEN** the second test SHALL NOT see events written by the first test
- **AND** the second test SHALL NOT see Run rows created by the first test
- **AND** the second test SHALL NOT see workers spawned by the first test

### Requirement: `Run.status="pending"` is a valid value

`RunStatus` SHALL gain a `"pending"` value, used between `RunQueue.enqueue` and the worker emitting `run_start`. Existing values (`running` / `ok` / `error` / `timeout`) are unchanged.

#### Scenario: Status transitions

- **WHEN** a Run is queried during its lifecycle
- **THEN** its `status` field SHALL follow this sequence: `pending` (after enqueue, before run_start) → `running` (after run_start, before terminal) → `ok` | `error` | `timeout` (after terminal)
- **AND** no other transitions are valid
