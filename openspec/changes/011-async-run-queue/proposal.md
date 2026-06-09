# 011 · Async run queue + cursor-based event subscription

## Problem

Agent runs are physically coupled to the HTTP/SSE connection that started them.

Concretely, `POST /api/agent/chat` (see `services/api/src/uteki_api/api/agent.py:81-109`) does this inside the request handler:

```
chat()
  └── _build_harness(...)
  └── return EventSourceResponse(event_source())
        └── agen = harness.run(messages, session_id=...)
        └── async for event in agen: yield event
        └── finally: await agen.aclose()
```

`harness.run(...)` is an async generator. The moment the SSE client disconnects — page refresh, tab close, route change, mobile screen lock, network blip — `sse_starlette` raises `GeneratorExit` into the `event_source` coroutine, `agen.aclose()` fires, and the harness aborts **mid-run**.

For a 1-token chat skill this is fine. For real pipelines this is **broken architecture**:

- `company_research_pipeline` (M6 + 009): 7 gates, ~3–6 minutes wall time on a real LLM
- `research` with tool-use loop: 1–3 minutes
- Any `as_of` backtest replay: same numbers

The product behavior is: **the user must keep the tab open and idle for 5 minutes** or lose the whole run. Backgrounding the tab in Chrome throttles timers; switching to another route navigates away; an iPhone screen lock kills the EventSource within ~30s. We have already paid for the LLM tokens. We have already written intermediate artifacts. The frontend then just… forgets the run exists.

The `POST /api/agent/start` endpoint (added for the MCP server) sidesteps this by draining the generator in a background `asyncio.create_task`. But it returns no stream — callers must poll `GET /api/runs/{id}` for terminal state and `GET /api/runs/{id}/events` for the full event list after the fact. There is no live "subscribe to in-progress run" path. The web client cannot use `/start` without losing the streaming UX.

This is a load-bearing architectural bug. It will not get easier to fix later — every new pipeline-style skill makes the failure mode more painful.

## Solution

**Decouple run execution from the HTTP connection** by introducing an append-only **run event log** + **cursor-based subscription** model.

Three primitives:

1. **`run_events` table** — append-only `(run_id, seq, type, data_json, ts, user_id)`. Every harness-emitted event gets a monotonically increasing `seq` per `run_id`, starting at 0. `done` and `error` are terminal: once written, no more events for that `run_id`.

2. **`RunQueue` ABC + `InProcessRunQueue`** — `enqueue(run_spec) -> run_id` schedules a harness invocation. MVP impl wraps `asyncio.create_task`; future Redis/Celery/Arq impl swaps in with zero caller-side change.

3. **`GET /api/runs/{run_id}/events?from_seq=N`** — SSE endpoint that (a) replays all events with `seq >= N` from the store (catch-up), then (b) waits on an `asyncio.Condition` per `run_id` to push newly appended events (live tail), and (c) closes the stream after writing `done` or `error`. Subscribing to a terminal run = replay-then-close.

The harness becomes a pure producer: it writes events to the store (which assigns `seq` and notifies the condition). It no longer cares whether anyone is listening.

The `POST /api/agent/chat` endpoint shape is preserved for backward compat — but internally it:

1. Enqueues the run via `RunQueue.enqueue(...)` → returns `run_id` immediately
2. Immediately subscribes to `GET /api/runs/{run_id}/events?from_seq=0` and streams those frames back to the client

So old clients see the same SSE stream. New clients can persist `run_id` and reattach.

### What changes — surface area

| Layer | Change |
|---|---|
| DB | New `run_events` table + alembic migration; no change to existing `run` table |
| Store | New `RunEventStore` ABC with `append` / `read_from` / `subscribe`; `default_run_event_store` singleton |
| Harness | `_emit_event(...)` dual-writes to legacy `Run.events` (back-compat) **and** `run_event_store.append(...)` |
| Queue | New `RunQueue` ABC + `InProcessRunQueue` (asyncio.create_task) |
| API | New `GET /api/runs/{run_id}/events` SSE endpoint with `from_seq` cursor; `POST /api/agent/chat` rewired to enqueue + subscribe |
| Frontend | `run_id` persisted in URL (`?run=…`); on mount, subscribe with `from_seq` = last-seen seq |

### Key invariants (full list in design.md)

1. Event log is **append-only** — never modify, never delete
2. `seq` is **monotonically increasing per run_id**, starting at 0
3. `done` and `error` are **sticky terminal**: once either is written, no further events for that `run_id`
4. Subscribing to a **terminal run** = replay-then-close (deterministic)
5. **User isolation unchanged**: subscribing to another user's `run_id` returns 404 (same shape as "doesn't exist", via `_owner_id` helper reused from `api/artifacts.py`)
6. The `RunQueue` ABC contract is **process-agnostic**: callers do not learn whether the worker is in-process or distributed
7. **Mock-mode contract preserved**: `UTEKI_USE_MOCK_LLM=true` still emits the same deterministic event sequence; only the transport changes

### Migration / rollout — four PRs, each shippable independently

Each PR is end-to-end testable on its own. PR A is invisible to users (additive table + dual-write). PR B introduces the new endpoint behind a feature flag. PR C cuts over. PR D unlocks the frontend UX.

- **PR A — `run_events` table + dual-write** (zero behavior change for callers)
- **PR B — `RunQueue` ABC + worker + `GET /runs/:id/events` endpoint** (new path exists but `POST /chat` still uses old direct-SSE path; both work in parallel)
- **PR C — cutover `POST /chat`** (internally enqueue + subscribe; delete old direct-SSE path)
- **PR D — frontend `?run=…` URL persistence + reattach on mount**

See `tasks.md` for explicit checkboxes.

## Non-goals

- **Distributed worker.** MVP is single-process `asyncio.create_task`. Redis/Arq/Celery integration is documented as the future swap point but not implemented here. (Design preserves the swap.)
- **Crash recovery for in-flight runs.** If the API process crashes, runs that were executing are lost. The `run_events` table preserves whatever was already emitted; status stays `running` (existing M5 known issue, see `runs/sql_models.py:11-15`). A future PR can add a boot-time sweep that marks orphaned `running` runs as `error`. Not in this change.
- **Pause/resume / await_review human-in-the-loop.** Terminal-sticky semantics are preserved. Future `await_review` async pause (008 mentions this as future work) builds on top of the event log but is out of scope here.
- **Cancellation API.** `POST /api/runs/:id/cancel` is a natural follow-up — the worker model makes it trivially possible (cancel the task) — but is out of scope for this change.
- **Replacing `Run.events` in storage.** The legacy `events_json` column on the `run` table stays for back-compat reads. New code reads from `run_events`. The legacy column can be deprecated in a follow-up.
- **WebSocket transport.** SSE is sufficient and matches the existing protocol. No WS migration.
- **Auth changes.** Owner / optional_user from change 010 is unchanged. The new `/events` endpoint uses the same `optional_user` + `_owner_id` ownership check as `/api/runs/:id/artifacts/*`.

## Dependencies

Hard:

- **010** (`public-readonly-and-owner-console`) — `Run.visibility` + ownership helper `_owner_id(run_id, user)`. The new `/events` SSE endpoint reuses both.
- **001** (`tenant-and-auth`) — `Run.user_id` partition key.

Soft / informational:

- **harness spec** §"Run 生命周期" — the 11-step run lifecycle is preserved; `_emit_event` gains a dual-write side effect.
- **storage spec** §"RunStore" — new `RunEventStore` is a sibling; existing `RunStore` is unchanged.

## Risks

| Risk | Mitigation |
|---|---|
| Dual-write to `Run.events` (legacy) + `run_events` (new) doubles event-write cost during PR A / B | Acceptable. Events are small (mostly `delta`, `step_start`, `tool_call`); SQLite handles 5k inserts/run trivially. Drop legacy write in a follow-up after PR C bakes. |
| `seq` allocation race if two harness loops emit concurrently for same run_id | Cannot happen by construction: one `Run` ↔ one worker task. Defense in depth: `(run_id, seq)` is the PK — duplicate insert raises. |
| `asyncio.Condition` per run_id leaks memory if subscribers don't clean up | Use weakref dict + cleanup on terminal event. Terminal event also `notify_all` then drops the condition. |
| SSE client disconnects → worker keeps running, fine; but client reconnects with stale `from_seq` and replays already-seen events | At-least-once delivery contract documented. Client dedupes by `seq`. Frontend tracks `lastSeenSeq` in component state + URL hash. |
| Process crash mid-run leaves `running` status forever | Same as today (existing bug per `sql_models.py:11-15`). Not introduced by this change; follow-up sweep job recommended. |
| Migration to distributed queue (post-MVP) requires changing event-store backend too (in-proc Condition won't work cross-process) | Documented in design.md §"Future: distributed worker". `RunQueue` + `RunEventStore` swap together; the API surface (`POST /chat`, `GET /events`) is stable. |
| Old clients that hold an open SSE stream against the cutover deployment | SSE is request-scoped — clients reconnect after the deployment with a fresh request, which hits the new path. No protocol-level break. |
| Existing E2E tests assume `harness.run(...)` returns directly to the test (no worker indirection) | Test harness can still call `AgentHarness(...).run(...)` directly — the worker is only inserted at the API layer. E2E tests of the API endpoint reattach via SSE the same way frontends do. |

## 改 vs 重做

Considered alternatives (full discussion in `design.md`):

- **Celery / Arq / SQS** — proper distributed queue. Rejected for MVP: deployment complexity (Redis dep), local dev pain. Designed to be a drop-in upgrade later via the `RunQueue` ABC.
- **WebSockets instead of SSE** — bidirectional, supports client→server cancel. Rejected: SSE is sufficient; existing client + server code is SSE; cancellation can be a separate REST POST.
- **Store events on disk per-run-id append file (no DB table)** — Rejected: no efficient `WHERE seq >= N` reads, no cross-replica fan-out (would block distributed-queue future).
- **Keep current direct-stream model + just background `chat()` via `create_task`** — Rejected: doesn't solve reattach, doesn't solve "what was the run_id when I refresh", doesn't solve multi-device viewing.

The event-log + cursor model is the minimum machinery that fixes the disconnect problem **and** preserves a clean path to distributed execution. It is an architectural one-way door we are deliberately walking through.
