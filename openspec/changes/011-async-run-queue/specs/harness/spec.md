## ADDED Requirements

### Requirement: Run execution is decoupled from the HTTP/SSE connection that started it

Agent runs SHALL execute in a background worker, independent of the lifetime of the HTTP request that initiated them. Disconnecting the client mid-run SHALL NOT abort the harness; the worker continues until the run reaches a terminal state (`done` / `error` / `timeout`).

#### Scenario: Client disconnects mid-run

- **GIVEN** the client posts `/api/agent/chat` and the harness begins emitting events
- **WHEN** the client closes the SSE connection before the run finishes
- **THEN** the worker SHALL continue executing the skill
- **AND** all subsequent events SHALL still be appended to the run event log
- **AND** the run's final status SHALL be the same as if the client had stayed connected

#### Scenario: Client reattaches after disconnect

- **GIVEN** a run was started and the client disconnected after seeing seq N
- **WHEN** the client opens `GET /api/runs/{run_id}/events?from_seq=N+1`
- **THEN** the server SHALL replay all events with `seq >= N+1`
- **AND** then live-tail any new events until the run reaches terminal
- **AND** then close the stream

### Requirement: Run lifecycle gains a `pending` state and a queue-submission step

The Run lifecycle SHALL begin with `RunQueue.enqueue(...)` which synchronously creates the `Run` row with `status="pending"` before any harness code executes. The harness worker SHALL transition the status to `running` on emitting `run_start`.

The lifecycle becomes:

```
[0]  RunQueue.enqueue:
       - allocate run_id
       - run_store.create(Run(..., status="pending"))
       - spawn worker (asyncio.create_task)
       - return run_id to caller
[1]  (worker) build harness
[2]  (worker) emit run_start    ← status → "running"
[3-9] ... unchanged from current spec
[10] emit done
[11] usage_totals → Run.usage_summary
[12] run_store.finish(status, summary)
[13] (worker exits)
```

#### Scenario: Run row exists before any event is emitted

- **WHEN** `RunQueue.enqueue(spec)` returns
- **THEN** a `Run` row SHALL exist in `RunStore` with the returned `run_id`
- **AND** `Run.status` SHALL be `"pending"`
- **AND** no events SHALL have been appended yet
- **AND** a subscriber attaching to `GET /api/runs/{run_id}/events?from_seq=0` SHALL be valid (it will Phase-1 yield zero events, then Phase-2 wait)

#### Scenario: Worker emits run_start

- **GIVEN** `Run.status == "pending"`
- **WHEN** the worker emits `run_start` (the first event)
- **THEN** the event SHALL be appended at `seq=0`
- **AND** `Run.status` SHALL transition to `"running"`

### Requirement: Harness dual-writes every event to `RunEventStore`

For every event yielded by the skill (after the existing `_emit_event` side effects of writing to `Memory` + `RunStore`), the harness SHALL also call `RunEventStore.append(run_id, user_id, event)`. The returned `seq` SHALL be assigned to the event's optional `AgentEvent.seq` field via `model_copy` before yielding upstream.

#### Scenario: Every emitted event has a seq

- **WHEN** the harness yields any event to its consumer
- **THEN** the event's `seq` field SHALL be a non-negative integer
- **AND** `seq` SHALL be unique within the `run_id`
- **AND** `seq` SHALL be monotonically increasing per `run_id`, starting at 0

#### Scenario: Event log parity with legacy Run.events

- **GIVEN** a run started after this change is deployed
- **WHEN** the run reaches terminal
- **THEN** `RunEventStore.read_from(run_id, 0)` SHALL return the same events, in the same order, as `Run.events`
- **AND** during the deprecation window, both writes SHALL be performed by the harness

### Requirement: Terminal events are sticky at the storage layer

Once an event with `type in {"done", "error"}` is appended for a `run_id`, the `RunEventStore` SHALL raise `TerminalEventLogClosed` on any further `append` call for that `run_id`. The harness SHALL handle this defensively (log warn, continue) — it should never reach this case by construction, since the harness already enforces "exactly one terminal event per run".

#### Scenario: Defensive terminal guard

- **GIVEN** `RunEventStore` has appended a `done` event for `run_id`
- **WHEN** any caller attempts `RunEventStore.append(run_id, user_id, event)` again
- **THEN** the store SHALL raise `TerminalEventLogClosed`
- **AND** the run's existing terminal status SHALL be preserved

## MODIFIED Requirements

### Requirement: Run lifecycle (replaces the existing 11-step lifecycle in current spec)

The Run lifecycle described in the current harness spec ("Run 生命周期" section) SHALL be replaced with the 14-step version below. Steps [3]-[12] are functionally identical to the existing [1]-[11]; the additions are step [0] (queue submission, before harness code runs) and step [13] (worker exit).

```
[0]  RunQueue.enqueue creates Run row (status="pending") and spawns worker task
[1]  Worker builds harness (skill, limits, run_store, event_store, etc.)
[2]  emit run_start (seq=0; transitions status → "running")
[3]  for raw in skill.run(messages):
       ├── deadline check → error+break, status=timeout
       ├── inject run_id (model_copy)
       ├── count step_start / tool_call → over → error+break
       ├── tool_call → execute (_invoke_tool) → emit tool_result
       ├── delta → buffer, summary at end
       ├── usage → accumulate + budget check → exceeded emit error+break
       ├── error event → mark final_status=error
       └── dual-write memory + run_store + event_store, yield upstream
[4]  catch skill exception → emit error, status=error
[5]  if final content but no primary artifact, write final-report.md and emit artifact_written
[6]  if source catalog non-empty, write source-catalog.json and emit artifact_written
[7]  write trace-diagnosis.json and emit artifact_written
[8]  emit done (terminal — event_store will reject further appends)
[9]  usage_totals → Run.usage_summary
[10] run_store.finish(status, summary)
[11] (worker exits — task is removed from RunQueue tracking)
```

#### Scenario: Harness step ordering is preserved

- **WHEN** comparing pre-change and post-change runs (same skill, same inputs, mock mode)
- **THEN** the sequence of events emitted SHALL be byte-identical (modulo the new optional `seq` field on each event)
- **AND** the timing of `run_start`, `done`, `artifact_written`, and `error` SHALL be unchanged

## ADDED Requirements (continued)

### Requirement: `AgentEvent.seq` is an optional monotonic identifier

The `AgentEvent` schema SHALL gain an optional `seq: int | None = None` field. The harness fills it in after `RunEventStore.append` returns the assigned `seq`. Older clients that do not know about `seq` SHALL continue to function (forward-compat via Pydantic's default field tolerance).

#### Scenario: Wire format includes seq

- **WHEN** the SSE endpoint serializes an event into a frame
- **THEN** the JSON payload SHALL include `"seq": <int>`
- **AND** the SSE `id:` line SHALL also carry the seq as a string (for browser-native `Last-Event-ID` support)

## RENAMED / RESCOPED Requirements

### Requirement: "Async cancellation" follow-up note is no longer "out of scope"

The current harness spec's "不属于本 spec" section lists "异步 cancellation（SSE 客户端断开 → 中止 skill）" as out of scope. After this change, the **opposite** is true: the harness SHALL NOT abort on client disconnect; instead, it runs to completion in the worker.

The line SHALL be removed from "不属于本 spec" and replaced with: "**异步 cancellation** — `RunQueue.cancel(run_id)` API exists in the ABC but is not implemented; future work."

#### Scenario: Disconnect no longer aborts

- **WHEN** the SSE response to `POST /api/agent/chat` is closed by the client
- **THEN** the harness worker SHALL continue
- **AND** the run SHALL reach its natural terminal state
- **AND** no `error` event with `reason="cancelled"` SHALL be emitted (because the client disconnect is no longer a cancellation signal)
