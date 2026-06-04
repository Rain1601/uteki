# 011 · Design

## 整体架构

```
┌──────────────────────────────────────────────────────────────────────┐
│ Browser                                                               │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  /console/runs/[id]?run=<run_id>&seq=<lastSeenSeq>                   │
│      │                                                                │
│      │  1. POST /api/agent/chat  → { run_id }                        │
│      │     (or just navigate to existing ?run=<id>)                  │
│      ▼                                                                │
│      EventSource("/api/runs/<run_id>/events?from_seq=<lastSeenSeq>") │
│      ── reads frames ──> dedupe by seq ──> render                    │
│      ── connection drop ──> reconnect with new from_seq ──> resume   │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│ FastAPI                                                               │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  POST /api/agent/chat                                                 │
│    │                                                                  │
│    ├──> RunQueue.enqueue(RunSpec)  ──┐                               │
│    │      (returns run_id)           │                                │
│    │                                 │  asyncio.create_task           │
│    │                                 ▼                                │
│    │                          ┌──────────────────────────────────┐   │
│    │                          │ run_worker(run_id, run_spec)     │   │
│    │                          │   harness = AgentHarness(...)    │   │
│    │                          │   async for ev in harness.run(): │   │
│    │                          │       store.append(run_id, ev)   │   │
│    │                          │       condition.notify_all()     │   │
│    │                          └──────────────────────────────────┘   │
│    │                                                                  │
│    └──> 302/internal redirect to GET /api/runs/<run_id>/events       │
│         (or implemented as inline subscription, see §POST /chat)      │
│                                                                       │
│  GET /api/runs/{run_id}/events?from_seq=N                             │
│    │                                                                  │
│    ├──> _owner_id(run_id, user)  (404 if not yours)                  │
│    │                                                                  │
│    ├──> for ev in store.read_from(run_id, N): yield ev               │
│    │                                                                  │
│    └──> while not terminal:                                          │
│            await condition.wait()                                     │
│            for ev in store.read_from(run_id, last_seq+1): yield ev   │
│            if ev.type in {done, error}: close stream                  │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Storage                                                               │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  RunEventStore (NEW)                                                  │
│    append(run_id, event) -> seq                                       │
│    read_from(run_id, from_seq) -> list[(seq, event)]                  │
│    subscribe(run_id) -> AsyncIterator[(seq, event)]                   │
│                                                                       │
│  Backing table: run_events                                            │
│    PK (run_id, seq)                                                   │
│                                                                       │
│  RunStore (EXISTING, unchanged)                                       │
│    Run record, Run.events legacy column (still dual-written in PR A) │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

## 数据模型

### 新表 `run_events`

```python
# services/api/src/uteki_api/runs/sql_models.py (additions)

class RunEventRow(SQLModel, table=True):
    """Append-only event log per run.

    One row per AgentEvent. seq is monotonically increasing per run_id
    starting at 0. PK (run_id, seq) prevents duplicate inserts at the DB
    level — the harness should never try, but defense in depth.
    """
    __tablename__ = "run_events"

    run_id: str = Field(primary_key=True, index=True)
    seq:    int = Field(primary_key=True)               # 0, 1, 2, ...
    user_id: str = Field(index=True)                    # denormalized from Run.user_id
                                                        # for cheap ownership checks
    type:   str                                         # event type ("delta", "tool_call", ...)
    data_json: str                                      # AgentEvent.model_dump_json()
    ts:     float = Field(index=True)                   # wall clock at append time
```

Indexes:
- PK `(run_id, seq)` — primary access pattern (`read_from`)
- `ix_run_events_user_id` — defense-in-depth ownership filter
- `ix_run_events_ts` — operational queries ("show me all events in the last hour")

**Size estimate.** A real-LLM `company_research_pipeline` run emits ~2000–4000 events (mostly `delta`). Average row size after JSON ~400 bytes ⇒ ~1.5MB per run on disk. At 100 runs/day → ~150MB/month. Comfortable in SQLite for MVP; same shape works in Postgres for prod (010 PR 5 deploy target).

### Alembic migration

```python
# services/api/src/uteki_api/migrations/versions/XXXX_add_run_events_table.py

def upgrade():
    op.create_table(
        "run_events",
        sa.Column("run_id",    sa.String, nullable=False),
        sa.Column("seq",       sa.Integer, nullable=False),
        sa.Column("user_id",   sa.String, nullable=False),
        sa.Column("type",      sa.String, nullable=False),
        sa.Column("data_json", sa.Text,   nullable=False),
        sa.Column("ts",        sa.Float,  nullable=False),
        sa.PrimaryKeyConstraint("run_id", "seq"),
    )
    op.create_index("ix_run_events_user_id", "run_events", ["user_id"])
    op.create_index("ix_run_events_ts",      "run_events", ["ts"])

def downgrade():
    op.drop_index("ix_run_events_ts", table_name="run_events")
    op.drop_index("ix_run_events_user_id", table_name="run_events")
    op.drop_table("run_events")
```

No backfill — old `Run.events` data stays in the legacy `events_json` column on the `run` table. `GET /api/runs/{id}` for archived runs continues to read from there (back-compat). Only new runs (post-PR A) have rows in `run_events`.

## RunEventStore ABC

```python
# services/api/src/uteki_api/runs/event_store.py

class RunEventStore(ABC):
    @abstractmethod
    async def append(self, run_id: str, user_id: str, event: AgentEvent) -> int:
        """Append `event` to `run_id`'s log. Returns the assigned seq.

        Invariants:
          - seq is monotonically increasing per run_id, starting at 0
          - if (run_id, seq) already exists, raises EventLogConflict
          - if the previous event for run_id was `done` or `error`,
            raises TerminalEventLogClosed

        Side effect: notifies any subscribers waiting on this run_id.
        """
        ...

    @abstractmethod
    async def read_from(
        self, run_id: str, from_seq: int, *, limit: int | None = None
    ) -> list[tuple[int, AgentEvent]]:
        """Read events for run_id with seq >= from_seq, ordered by seq."""
        ...

    @abstractmethod
    async def subscribe(
        self, run_id: str, from_seq: int
    ) -> AsyncIterator[tuple[int, AgentEvent]]:
        """Yield events for run_id starting at from_seq.

        Phase 1 (catch-up): drain all events already in the store with
                            seq >= from_seq.
        Phase 2 (live):     await per-run-id Condition for new appends.
        Termination:        stream closes after yielding a `done` or
                            `error` event.

        If the most recent event in the store is already terminal,
        Phase 1 yields it and Phase 2 is skipped — pure replay.
        """
        ...

    @abstractmethod
    async def latest_seq(self, run_id: str) -> int | None:
        """Highest seq written for run_id, or None if no events yet.
        Used by harness to compute next seq under the per-run-id lock."""
        ...

    @abstractmethod
    async def is_terminal(self, run_id: str) -> bool:
        """True iff the last event for run_id has type in {done, error}."""
        ...
```

Two implementations:

- **`SqliteRunEventStore`** — backs onto `RunEventRow`. Uses an in-process `dict[run_id, asyncio.Condition]` for fan-out. SQLite is single-writer-friendly but we never have concurrent writers for the same `run_id` (one worker per run), so no contention.
- **`InMemoryRunEventStore`** — used by tests via the conftest singleton-replacement pattern (see CLAUDE.md "Singleton-replacement testing pattern"). Pure dict + condition.

### Fan-out: per-run-id `asyncio.Condition`

```python
class SqliteRunEventStore(RunEventStore):
    def __init__(self, engine: Engine):
        self._engine = engine
        self._conditions: dict[str, asyncio.Condition] = {}
        self._lock = asyncio.Lock()  # guards _conditions dict mutation

    def _cond(self, run_id: str) -> asyncio.Condition:
        # Lazy create; never delete (small footprint, ~bytes per run)
        # If memory becomes an issue we can WeakValueDictionary later
        # but ergonomics + correctness > micro-optimization here.
        if run_id not in self._conditions:
            self._conditions[run_id] = asyncio.Condition()
        return self._conditions[run_id]

    async def append(self, run_id, user_id, event):
        cond = self._cond(run_id)
        async with cond:
            # Compute next seq + insert under the condition's lock,
            # so any subscriber's "latest_seq read" → "wait" race is closed.
            next_seq = (await self._latest_seq_unlocked(run_id, ...)) + 1 \
                       if await self._has_events(run_id) else 0
            # ... INSERT into run_events ...
            cond.notify_all()
        return next_seq
```

The Condition is held only across the `INSERT` + `notify_all`, which is microseconds. Subscribers wait on the same condition; on wake, they re-read `read_from(run_id, last_seen+1)` to pull whatever the latest seq is. Crucially, **multiple inserts between waits are coalesced** — the subscriber catches up by reading all unseen seqs, not by counting `notify_all` calls.

### Cross-process fan-out (future)

In-process `asyncio.Condition` does not work across processes. If we ever run multiple API replicas (or distributed workers), `subscribe()` needs to either:

- Long-poll the DB with a backoff (`SELECT WHERE seq > N LIMIT 100`, sleep 250ms, repeat) — works everywhere, latency cost
- Use Postgres `LISTEN/NOTIFY` on the `run_events` row — works in prod, not in SQLite
- Use Redis pub/sub on `run_events:{run_id}` channel — requires Redis dep but matches future `RunQueue` Redis backend

We pick **long-poll DB with 250ms cadence** as the universal cross-process fallback in the design. It's slightly slower than `LISTEN/NOTIFY` but works in every deployment and doesn't add a new infra dep. Documented as a follow-up; MVP is in-process `Condition`.

## RunQueue ABC

```python
# services/api/src/uteki_api/runs/queue.py

@dataclass(frozen=True)
class RunSpec:
    """Everything needed to construct a harness for a queued run.

    Frozen + JSON-serializable so a future Redis/Celery backend can
    enqueue it as a blob without leaking object refs.
    """
    user_id: str
    agent: str                              # skill name
    messages: list[ChatMessage]
    session_id: str | None = None
    model: str | None = None                # per-run override
    as_of: date | None = None
    triggered_by: str = "user"
    trigger_reason: str = ""


class RunQueue(ABC):
    @abstractmethod
    async def enqueue(self, spec: RunSpec) -> str:
        """Schedule a run. Returns run_id immediately (before the worker
        starts executing). The returned run_id MUST already exist in
        RunStore (i.e. Run row created synchronously here), so callers
        can begin subscribing to /events right away.
        """
        ...

    @abstractmethod
    async def cancel(self, run_id: str) -> bool:
        """Best-effort cancel. Returns True if the worker was found and
        signaled, False if already terminal or unknown. Not part of MVP
        scope — left in the ABC so a future PR can fill it in without
        ABI churn.
        """
        ...


class InProcessRunQueue(RunQueue):
    """asyncio.create_task-backed worker pool. One task per enqueued run."""

    def __init__(self, run_store, run_event_store):
        self._tasks: dict[str, asyncio.Task] = {}

    async def enqueue(self, spec: RunSpec) -> str:
        # 1. Create the Run row synchronously — gives us run_id and
        #    ensures /events subscribers can attach immediately even if
        #    the worker hasn't started executing yet.
        run = Run(
            id=allocate_run_id(),
            user_id=spec.user_id,
            skill=spec.agent,
            triggered_by=spec.triggered_by,
            trigger_reason=spec.trigger_reason,
            ...,
            status="pending",  # new status, see §"Run lifecycle"
        )
        await run_store.create(run)

        # 2. Spawn worker task.
        task = asyncio.create_task(run_worker(run.id, spec), name=f"run-{run.id}")
        self._tasks[run.id] = task
        task.add_done_callback(lambda _: self._tasks.pop(run.id, None))
        return run.id
```

### Worker function

```python
async def run_worker(run_id: str, spec: RunSpec) -> None:
    """Drive the harness for one enqueued run.

    Errors here are terminal for the run — they SHOULD result in an
    `error` event being written via the harness's existing
    skill-exception path; if the harness itself throws (unexpected),
    we MUST still write a final `error` event ourselves before the
    task exits, so subscribers don't hang waiting for a terminal.
    """
    try:
        harness = await build_harness_for_run(run_id, spec)
        async for event in harness.run(spec.messages, session_id=spec.session_id):
            pass  # harness already dual-writes to event store inside _emit
    except asyncio.CancelledError:
        await event_store.append(
            run_id, spec.user_id,
            AgentEvent(type="error", data={"reason": "cancelled"})
        )
        raise
    except Exception as exc:
        # Defensive: if harness throws without emitting its own `error`,
        # subscribers would hang. Emit one ourselves.
        if not await event_store.is_terminal(run_id):
            await event_store.append(
                run_id, spec.user_id,
                AgentEvent(type="error", data={"reason": str(exc)})
            )
        logger.exception("run_worker failed for %s", run_id)
```

The worker holds no references to any HTTP request. The original `POST /chat` request can return its first frame and disconnect immediately; the worker keeps running until terminal.

## Harness changes

The harness already does step [13] `memory.append_event` and `run_store.append_event` for each emitted event (see harness spec §"Run 生命周期" step 4). PR A adds a third write target: `run_event_store.append(...)`.

```python
# Conceptual diff in agents/harness.py

async def _emit_event(self, ev: AgentEvent) -> AgentEvent:
    # Existing dual-write:
    await self._memory.append_event(self.user_id, self.session_id, ev)
    await self._run_store.append_event(self._run_id, ev)
    # NEW: append to event log, returns assigned seq
    seq = await self._run_event_store.append(self._run_id, self.user_id, ev)
    # Optionally annotate ev with seq for downstream tooling (M1.x style).
    ev_with_seq = ev.model_copy(update={"seq": seq})  # if AgentEvent gains seq field
    return ev_with_seq
```

The harness does **not** change otherwise:
- Same 11-step lifecycle
- Same 6 budget guards
- Same skill-injection (`_tool_executor`, `artifacts`, `sources`)
- Same `_already_executed` tool-call dedupe
- Same primary-artifact + diagnosis writes before `done`

The harness becomes ignorant of who is listening. **It writes; it does not stream.** This is the architectural shift.

### AgentEvent gets `seq` (optional)

For client dedupe convenience, we extend `AgentEvent` with an optional `seq: int | None = None`. The harness fills it in via `model_copy` after `event_store.append` returns the assigned seq. SSE frames serialize `seq` as part of the data payload; clients store `lastSeenSeq` and reattach with `?from_seq=lastSeenSeq+1`.

**Why add `seq` to the event itself?** Two reasons:
1. Clients need it for dedupe even when the SSE wire-level `id:` field is dropped by intermediate proxies
2. Future debugging — `grep "seq=42"` across events + logs lines up cleanly

The field is optional so older event handlers that don't know about it continue to work.

## SSE protocol — `GET /api/runs/{run_id}/events`

### Request

```
GET /api/runs/{run_id}/events?from_seq=N
Authorization: Bearer <token>    # optional, optional_user dep
Accept: text/event-stream
```

### Response

Standard SSE. Each frame:

```
event: <event.type>
id: <seq>
data: {"seq":<seq>,"type":<type>,"data":{...},"run_id":"<run_id>",...}

```

- `event:` line carries the AgentEvent `type` (so clients can `addEventListener("delta", ...)`)
- `id:` line carries `seq` — browsers natively use this for `Last-Event-ID` reconnect (we don't depend on it but it's free + correct)
- `data:` is the full `AgentEvent.model_dump_json()`, which now includes `seq`

### Server algorithm

```python
@router.get("/{run_id}/events")
async def stream_run_events(
    run_id: str,
    from_seq: int = 0,
    user: User | None = Depends(optional_user),
):
    # 1. Ownership check via shared helper (same as artifacts)
    try:
        owner = await _owner_id(run_id, user)
    except OwnershipDenied:
        raise HTTPException(404)

    async def gen():
        # Phase 1: replay everything from from_seq forward
        async for seq, ev in event_store.subscribe(run_id, from_seq):
            yield {"event": ev.type, "id": str(seq), "data": ev.model_dump_json()}
            if ev.type in TERMINAL_TYPES:
                return  # subscribe() stops on terminal too, but be explicit

    return EventSourceResponse(gen())
```

`subscribe()` handles both phase 1 (catch-up) and phase 2 (live tail) internally. From the route handler's perspective it's one async iterator that eventually closes.

### Disconnect handling

If the client disconnects mid-stream, `EventSourceResponse` cancels `gen()`. `subscribe()` propagates `CancelledError` to its internal Condition wait — cleanup happens automatically. **The worker is unaffected.** This is the whole point of the change.

### At-least-once delivery

We promise **at-least-once**, not exactly-once. A client can receive the same `seq` twice if:

- It disconnects mid-frame, reconnects with stale `from_seq`
- A proxy re-sends a frame after a transient error

Clients dedupe by tracking `lastSeenSeq` in component state and skipping events with `seq <= lastSeenSeq`. The dedupe is trivial because `seq` is per-`run_id` monotonic.

### Replay-then-close for terminal runs

Subscribing to a run that already has a `done` or `error` event:

1. `subscribe()` reads all events with `seq >= from_seq` (Phase 1)
2. Last event read is terminal → Phase 2 is skipped
3. Stream closes cleanly

This is the same protocol regardless of run state. Frontend doesn't need a separate "fetch finished run" code path.

### Heartbeat

SSE drops idle connections. Use `EventSourceResponse(ping=15)` (15-second heartbeat). Heartbeat frames have no event type and are filtered by EventSource clients automatically.

## POST /api/agent/chat — cutover behavior

Existing shape preserved. After PR C:

```python
@router.post("/chat")
async def chat(req: ChatRequest, user: User = Depends(require_owner)):
    # 1. Enqueue
    spec = RunSpec(
        user_id=user.id,
        agent=req.agent,
        messages=req.messages,
        session_id=req.session_id,
        model=req.model,
        as_of=req.as_of,
        triggered_by="user",
        trigger_reason=f"chat:{req.session_id or 'adhoc'}",
    )
    run_id = await run_queue.enqueue(spec)

    # 2. Immediately subscribe — same SSE shape as before, but the harness
    #    now executes in a background task, so disconnects don't kill it.
    async def gen():
        async for seq, ev in event_store.subscribe(run_id, from_seq=0):
            yield {"event": ev.type, "id": str(seq), "data": ev.model_dump_json()}
            if ev.type in TERMINAL_TYPES:
                return

    return EventSourceResponse(gen())
```

Client experience: identical to today (SSE stream of AgentEvents).  
Underlying execution: decoupled.

`POST /api/agent/start` (the MCP endpoint, see `agent.py:112-154`) is simplified to just `run_queue.enqueue(...)` + return `{run_id}`. Its existing manual `asyncio.create_task` + `_inflight_runs` set is deleted — the queue owns task tracking now.

## Frontend changes

### URL state

```
/console/runs/[run_id]                ← canonical run page
/console/chat?run=<run_id>            ← chat surface, reattach on mount
/console/chat?run=<run_id>&seq=42     ← reattach + skip already-seen
```

On a `POST /api/agent/chat`, the response stream's first frame is `run_start` with `run_id`. The client immediately updates the URL via `router.replace(\`?run=${run_id}\`)`. Subsequent in-flight events arrive via the same SSE response — no resubscribe needed during the happy path.

If the page is reloaded mid-run (or the user navigates back to a `?run=…` URL):
1. Component mounts, reads `run` and `seq` from URL
2. Opens `EventSource("/api/runs/<run_id>/events?from_seq=<seq+1>")`
3. Receives phase-1 catch-up of all missed events
4. Continues with phase-2 live tail
5. On every received event, update `seq` in URL via `router.replace`

### Multi-device viewing

Two browsers pointed at the same `/console/runs/<run_id>` subscribe independently. Each gets its own SSE stream. Each tracks its own `lastSeenSeq`. The event store fans out via the per-run-id Condition. Free side benefit of the design.

### Owner-only mutation

The `POST /chat` still requires `require_owner` (010 invariant). `GET /events` uses `optional_user` + `_owner_id` — public/unlisted runs are visible to anonymous viewers (same rule as `/api/runs/<id>`).

## Run lifecycle changes

Existing 11-step lifecycle (harness spec §"Run 生命周期") becomes 13 steps:

```
[0]  RunQueue.enqueue:
       allocate run_id
       create Run row, status="pending"
       spawn run_worker task
       return run_id to caller
[1]  (worker) build harness
[2]  (worker) emit run_start ─┐ same as before
[3-9] ... same as today      │
[10] emit done                │
[11] usage_totals → Run.usage_summary
[12] run_store.finish(status, summary)
[13] (worker exits)
```

Two new fields on `Run`:

- `status="pending"` — new value, between row-creation and `run_start` emit. Existing values (`running` / `ok` / `error` / `timeout`) unchanged.
- (Optional, follow-up) `queued_at: float` — wall clock at enqueue. Useful for queue latency observability. Not required for MVP.

### Terminal-sticky invariant

Once `RunEventStore` has appended an event with `type in {"done", "error"}` for a `run_id`:

- Further `append()` calls for that `run_id` raise `TerminalEventLogClosed`
- `subscribe()` and `read_from()` continue to work (pure reads) and behave as "replay-then-close"
- `Run.status` is set to the corresponding terminal status by `run_store.finish(...)`

The harness already enforces "always reach `done`" (invariant #2 in harness spec). The event store enforces it independently at the storage layer.

## Cross-cutting invariants (full list)

1. **Event log is append-only.** No `UPDATE` or `DELETE` against `run_events`.
2. **`seq` is monotonically increasing per `run_id`, starting at 0.**
3. **`done` and `error` are sticky terminals.** Appending after either raises.
4. **Subscribing to a terminal run = replay-then-close.** Deterministic, idempotent.
5. **At-least-once delivery.** Clients dedupe by `seq`. Never exactly-once over the wire.
6. **User isolation unchanged.** `/events` reuses `_owner_id` from `api/artifacts.py`. Cross-user access → 404.
7. **In-process worker can be replaced by distributed queue without API change.** `RunQueue` and `RunEventStore` are ABCs; route handlers call the ABCs.
8. **Mock-mode contract preserved.** `UTEKI_USE_MOCK_LLM=true` emits the same deterministic event sequence; only the transport changes.
9. **One worker per run_id.** No fan-out at the worker layer — there's exactly one writer per run, so `seq` allocation has no race.
10. **The harness is ignorant of subscribers.** It produces events; the event store fans out.
11. **Run row exists before any event is appended.** `enqueue()` creates the row synchronously; only then spawns the worker.
12. **`POST /chat` SSE shape is preserved.** Old clients see the same frames; new clients can additionally reconnect.

## Failure modes & mitigations

| Failure | What the user sees | What we do |
|---|---|---|
| API process crashes mid-run | Run stuck in `running` status forever; events written-so-far are persisted | Same as today. Follow-up: boot-time sweep marks orphaned `running` runs as `error`. Not in MVP. |
| Worker raises unhandled exception | `error` event appended by worker's `except` clause; status becomes `error` | Defensive handler in `run_worker` ensures terminal event always written |
| Subscriber disconnects mid-stream | Stream cleanly cancels; worker unaffected | This is the **whole point** of the change. Verify via E2E. |
| Subscriber's `from_seq` exceeds latest seq | Phase 1 yields nothing; Phase 2 awaits Condition normally | Correct behavior. No error needed. |
| Subscriber's `from_seq` is negative or non-numeric | 400 Bad Request | Validate at route level. |
| Cross-user subscription attempt | 404 (same as nonexistent run) | `_owner_id` check, identical to existing artifact behavior |
| Multiple subscribers, terminal arrives between two phase-1 reads | Both subscribers get the terminal event via Condition notify | Per-run-id Condition with `notify_all`; correct by construction |
| Massive event burst (10K deltas in <1s) | Subscriber falls behind; phase-2 reads catch up in batches | `read_from(run_id, last_seen+1)` returns whatever is available since last wake. No per-event ping-pong. |
| SQLite write contention on `run_events` | Negligible: one writer per run, harness emits ~1 event/100ms average | Document. If real-LLM bursts cause issues, switch to batched insert. |
| `asyncio.Condition` dict growth | Bounded by # of distinct run_ids ever subscribed to in this process | Acceptable for MVP. Future: WeakValueDictionary or explicit cleanup on terminal. |
| Worker is cancelled (process shutdown) | `CancelledError` handler emits `error` event with `reason="cancelled"`; status becomes `error` | Defensive `except CancelledError` in `run_worker` |
| Two HTTP clients call `POST /chat` with same `session_id` | Two separate `run_id`s allocated, two workers spawn, two parallel runs | This is current behavior; no change. `session_id` is for conversation context, not run identity. |
| `EventSource` reconnect on network blip resends events 0..N | Client sees duplicates with `seq <= lastSeenSeq` | Client dedupes by seq. Documented as part of at-least-once contract. |

## Alternatives considered

### A1. Celery + Redis broker

Pros: battle-tested; supports retries, deduplication, scheduling; eventually-distributed by default.  
Cons: Redis dep (local dev pain), Celery's own DSL/decorators, beat scheduler for cron use cases. Heavyweight for MVP. Worker startup latency is also an issue — Celery workers prefork and don't start instantly.  
**Verdict:** good future swap target; not MVP.

### A2. Arq (Redis-only, lighter than Celery)

Pros: pure asyncio, modern API, single Redis dep, fits FastAPI mental model.  
Cons: still needs Redis. Still a separate worker process to deploy + monitor.  
**Verdict:** strong candidate for the post-MVP migration. The `RunQueue` ABC is designed to accept an `ArqRunQueue` impl trivially.

### A3. SQS / cloud-managed queue

Pros: serverless, no Redis ops.  
Cons: SQS doesn't push — workers must poll. Latency floor of a few hundred ms per event. Coupling to a specific cloud provider. Not viable for the fast feedback loop the SSE UX wants.  
**Verdict:** not a fit.

### A4. asyncio.create_task in-process (our choice for MVP)

Pros: zero new deps; works in dev + prod identically; works in tests; the existing `/api/agent/start` endpoint already proves the model.  
Cons: process crash → in-flight runs lost; single-process scale ceiling. Both acceptable for personal-scale traffic. Both fixable by swapping the `RunQueue` impl later.  
**Verdict:** ship this; design the ABC so the swap is one PR.

### A5. WebSocket transport instead of SSE

Pros: bidirectional → client can send cancel.  
Cons: existing client + server are SSE; reverse proxies / Cloud Run support SSE first-class; WS framing overhead is not free; we don't need bidirectional for events (cancel can be POST `/api/runs/:id/cancel`).  
**Verdict:** stay on SSE. Add `POST /cancel` as a future REST endpoint if needed.

### A6. Store events on disk per-run-id append file (no DB table)

Pros: cheap append; no schema changes.  
Cons: no `WHERE seq >= N` query without parsing the whole file; no efficient cross-replica fan-out; doesn't fit Postgres path (010 PR 5 deploys to Cloud SQL).  
**Verdict:** rejected. DB table maps cleanly onto SQLite *and* Postgres, plus indexing is free.

### A7. Keep current direct-stream model, just spawn `chat()` in a background task

Pros: minimal code change.  
Cons: doesn't solve reattach. Doesn't solve "what run_id was that on refresh". Doesn't solve multi-device viewing. Doesn't give us an event log we can index, query, or replay.  
**Verdict:** rejected — it's a half-step that doesn't address the actual problem.

## Future: distributed worker

When we outgrow single-process:

1. Implement `RedisRunQueue(RunQueue)`:
   - `enqueue` pushes `RunSpec` JSON to a Redis list
   - Worker processes (separate deployments) `BRPOP` from the list and call `run_worker(run_id, spec)` locally
   - `cancel` writes a "cancel:<run_id>" flag to Redis; workers check it between harness steps
2. Implement `PostgresRunEventStore(RunEventStore)`:
   - Same `run_events` table, Postgres backend (010 PR 5 already targets Cloud SQL)
   - Cross-process subscribe via `LISTEN run_events_<run_id>` + `NOTIFY` on append, or polling fallback (`SELECT WHERE seq > N` every 250ms)
3. Swap `default_run_queue` + `default_run_event_store` bindings.

API routes (`POST /chat`, `GET /events`) **do not change**. The whole point of the ABC was making this possible.

## Cross-change impact

- **001 (tenant-and-auth):** `Run.user_id` reused for `RunEventRow.user_id` denormalization. No schema change to `User` / `AuthIdentity`.
- **005 (artifact-layer):** unchanged. Artifacts continue to write via `RunArtifacts` facade; the new event log is parallel infrastructure.
- **006 (planner-evaluator-pipeline):** unchanged. `subagent_start` / `subagent_end` flow through `_emit_event` like every other event and get logged.
- **007 (trace-diagnosis):** unchanged. `trace-diagnosis.json` is still computed from the run's event stream — that stream is now read from `run_events` (`RunEventStore.read_from(run_id, 0)`).
- **008 (tool-governance):** unchanged. `await_review` / blocked-result events flow through the log the same way.
- **010 (public-readonly):** `GET /events` uses `optional_user` + `_owner_id`. Visibility filtering at the run level (private/unlisted/public) is enforced by `_owner_id` returning 404 for non-owner access to a private run.
- **harness spec:** `Run 生命周期` gains a `pending` status (between enqueue and first emit) and step [0] for queue submission. See `specs/harness/spec.md` delta.
- **storage spec:** new `RunEventStore` ABC. See `specs/storage/spec.md` delta.

## Open questions (for review)

These are not blockers — defaults are listed — but worth a second look before PR A:

1. **Drop legacy `Run.events_json` after PR C?** Plan is to keep it through PR D for safety, deprecate in a follow-up. Acceptable to drop sooner if we trust `run_events`.
2. **`seq` on `AgentEvent` or only on the wire?** Plan: optional `seq` field on `AgentEvent`. Alternative is to keep it strictly transport-only and not pollute the schema. Slight preference for inclusion — cleaner debug story.
3. **`status="pending"` in `Run` model or fold into `running`?** Plan: add `pending`. Alternative: enqueue sets `running` immediately and the row exists for ~ms before the worker emits its own `run_start`. Both work; `pending` is more honest.
4. **Heartbeat cadence:** 15s default. Cloud Run idle timeout is 60s with default config; 15s is conservative. Acceptable.
5. **Cancel API:** explicitly out of scope but the queue interface has the method. Should the route exist in PR B as a 501 placeholder, or wait? Plan: wait.
