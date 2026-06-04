# 011 · Tasks

Four PRs, each independently shippable. PR A is fully additive (dual-write only, no behavior change). PR B introduces the new endpoint but keeps the old direct-SSE path. PR C cuts over. PR D unlocks the frontend reattach UX.

Status legend: `[pending]` / `[in-progress]` / `[done]`.

---

## PR A — `run_events` table + dual-write from harness (~6h)

Goal: every harness-emitted event lands in a new append-only table with a monotonic `seq` per `run_id`. Zero caller-visible behavior change. New table is fully populated and queryable by the time PR B starts using it.

### Phase A.1 · data model

- [ ] **TA.1** `runs/sql_models.py` add `RunEventRow` table: PK `(run_id, seq)`, columns `(run_id, seq, user_id, type, data_json, ts)`, two indexes (`ix_run_events_user_id`, `ix_run_events_ts`)
- [ ] **TA.2** `runs/models.py` extend `AgentEvent` with optional `seq: int | None = None` field (forward-compat — older clients ignore unknown fields)
- [ ] **TA.3** Alembic migration `XXXX_add_run_events_table.py`: create table + 2 indexes; downgrade drops both indexes then the table
- [ ] **TA.4** `core/db.py` add `_ensure_run_events_table()` helper analogous to `_ensure_run_visibility_column` for SQLite installs that bypass alembic in dev

### Phase A.2 · RunEventStore ABC + impls

- [ ] **TA.5** New module `runs/event_store.py`: `RunEventStore` ABC with `append`, `read_from`, `subscribe`, `latest_seq`, `is_terminal`; module-level `TERMINAL_TYPES = {"done", "error"}`; custom exceptions `EventLogConflict`, `TerminalEventLogClosed`
- [ ] **TA.6** `runs/event_store.py` `InMemoryRunEventStore` impl: dict-of-list + per-run-id `asyncio.Condition`; covers all ABC methods
- [ ] **TA.7** `runs/event_store.py` `SqliteRunEventStore` impl: writes via `RunEventRow`; per-run-id `asyncio.Condition` for fan-out; `append` under condition lock for race-free `seq` allocation
- [ ] **TA.8** `runs/__init__.py` expose `default_run_event_store` singleton (sqlite in prod, in-memory in test), selected via `settings.run_event_store` env (default same backend as `run_store`)
- [ ] **TA.9** Update `tests/e2e/conftest.py` to rebind `default_run_event_store` on the same set of importing modules it already handles (`agents/harness`, `api/{agent,runs}`) — follow the existing singleton-replacement pattern

### Phase A.3 · harness dual-write

- [ ] **TA.10** `agents/harness.py` accept optional `run_event_store: RunEventStore = default_run_event_store` constructor kwarg
- [ ] **TA.11** `agents/harness.py` modify the central `_emit_event` (or equivalent) path: after existing memory + run_store writes, call `seq = await self._run_event_store.append(self._run_id, self.user_id, ev)` and annotate `ev.seq = seq` via `model_copy`; yield the annotated event upstream
- [ ] **TA.12** `agents/harness.py` handle `EventLogConflict` defensively — log + skip (should never happen by construction; defense in depth)
- [ ] **TA.13** `agents/harness.py` handle `TerminalEventLogClosed` — log warn and stop; should be unreachable since harness already enforces "one terminal event per run", but proves the storage-layer guard

### Phase A.4 · tests

- [ ] **TA.14** `tests/runs/test_event_store_inmem.py` — unit tests on `InMemoryRunEventStore`: append assigns monotonic seq from 0, read_from with various from_seq values, terminal-sticky enforcement, conflict on duplicate (run_id, seq)
- [ ] **TA.15** `tests/runs/test_event_store_sqlite.py` — same suite against `SqliteRunEventStore`; uses tmp_path DB fixture
- [ ] **TA.16** `tests/runs/test_event_store_subscribe.py` — `subscribe()` semantics: catch-up only (terminal already written), live tail (append after subscribe starts), late subscriber on terminal run (replay-then-close), two concurrent subscribers see the same events
- [ ] **TA.17** `tests/e2e/test_harness_event_log.py` — run any existing skill end-to-end; assert `run_event_store.read_from(run_id, 0)` returns the same events as `Run.events` after `finish` (parity check)
- [ ] **TA.18** Run `./scripts/e2e.sh` — all existing 81+ cases must still pass; no behavioral change visible

### Phase A.5 · ops

- [ ] **TA.19** Document in `services/api/.env.example`: `UTEKI_RUN_EVENT_STORE=sqlite|memory` (defaults to match `UTEKI_RUN_STORE`)
- [ ] **TA.20** Update CLAUDE.md "Singleton-replacement testing pattern" note to mention `default_run_event_store` if a new module imports it later

**PR A acceptance:** every E2E + unit test green; manual smoke shows `SELECT * FROM run_events WHERE run_id = ? ORDER BY seq` matches the event sequence shown in the existing `/api/runs/:id/events` response.

---

## PR B — `RunQueue` ABC + worker + new `GET /api/runs/:id/events` SSE endpoint (~8h)

Goal: introduce the queue + new endpoint. **Do not** change `POST /chat` yet — it still uses the old direct-SSE path. New endpoint is reachable but only via direct URL or new test code.

### Phase B.1 · RunSpec + RunQueue ABC

- [ ] **TB.1** New module `runs/queue.py`: `@dataclass(frozen=True) class RunSpec` with fields `(user_id, agent, messages, session_id, model, as_of, triggered_by, trigger_reason)`; all JSON-serializable (no datetime besides date, no opaque objects)
- [ ] **TB.2** `runs/queue.py` `RunQueue` ABC: `enqueue(spec) -> run_id` and `cancel(run_id) -> bool` (cancel can `raise NotImplementedError` in MVP — declared in ABC for future)
- [ ] **TB.3** `runs/queue.py` helper `allocate_run_id() -> str` (centralize the `uuid4().hex[:12]` used in `agents/harness.py`)

### Phase B.2 · InProcessRunQueue + worker

- [ ] **TB.4** `runs/queue.py` `InProcessRunQueue(RunQueue)`: holds `dict[str, asyncio.Task]`; `enqueue` synchronously creates `Run` row (`status="pending"`), then spawns task
- [ ] **TB.5** `runs/queue.py` `run_worker(run_id, spec)`: builds harness via a new shared helper `_build_harness_from_spec`, awaits `harness.run(...)`; defensive `except` clauses (CancelledError, generic) ensure a terminal `error` event is written if the harness somehow doesn't
- [ ] **TB.6** `runs/models.py` `RunStatus` literal — add `"pending"` value; default `status="pending"` for newly-created Run (after `enqueue`, before first `run_start` emit)
- [ ] **TB.7** `runs/sql_models.py` no schema change needed — `status` column is already `TEXT`; just verify enum
- [ ] **TB.8** `runs/__init__.py` expose `default_run_queue: RunQueue = InProcessRunQueue(default_run_store, default_run_event_store)`; document the singleton-rebind requirement
- [ ] **TB.9** Refactor `api/agent.py`: extract `_build_harness(...)` logic into `_build_harness_from_spec(spec: RunSpec)` so both the queue worker and any direct callers can share it

### Phase B.3 · `_owner_id` helper (already exists for artifacts — reuse)

- [ ] **TB.10** Audit `api/artifacts.py` `_owner_id(run_id, user)` — confirm signature, return type, and 404 behavior. If it lives behind a private name, lift to a shared module `api/_ownership.py` so `api/runs.py` and the new events route can import it cleanly

### Phase B.4 · new SSE endpoint

- [ ] **TB.11** `api/runs.py` add `GET /{run_id}/events` SSE handler:
  - Param `from_seq: int = 0` (validate `>= 0`, else 400)
  - Uses `optional_user` dep + `_owner_id(run_id, user)` ownership check (404 on denial)
  - Internally calls `event_store.subscribe(run_id, from_seq)` and yields `{"event": ev.type, "id": str(seq), "data": ev.model_dump_json()}`
  - Closes stream after first terminal event
  - Uses `EventSourceResponse(gen(), ping=15)` for heartbeat
- [ ] **TB.12** The legacy `GET /{run_id}/events` route in `api/runs.py` (which returns JSON `{items: [...]}` — see `api/runs.py:109-115`) is **kept** under a different path: rename to `GET /{run_id}/events.json` (or keep as-is and add `?stream=true` query param to switch behavior). Plan: keep the JSON endpoint at the existing path **but** dispatch on `Accept: text/event-stream` header — if SSE accept header is present, stream; otherwise return JSON. Document the dispatch in the route docstring.

### Phase B.5 · feature-flag the queue for new endpoint only

- [ ] **TB.13** Add `POST /api/agent/enqueue` endpoint (TEMPORARY; deleted in PR C) — accepts `ChatRequest`, calls `run_queue.enqueue(...)`, returns `{run_id}`. Used by PR B tests + manual smoke to exercise the new path end-to-end without touching `/chat`.

### Phase B.6 · tests

- [ ] **TB.14** `tests/runs/test_queue_inproc.py` — `InProcessRunQueue.enqueue` creates Run row synchronously, spawns task, returns run_id; worker runs to completion (mock skill); terminal event reaches the event store
- [ ] **TB.15** `tests/runs/test_queue_cancel.py` — worker exception path: harness throws → worker writes `error` event; `Run.status == "error"`; event store has terminal
- [ ] **TB.16** `tests/api/test_runs_events_sse.py` — fastapi TestClient: POST /enqueue, then GET /events?from_seq=0, assert SSE frames arrive in order, terminal closes stream
- [ ] **TB.17** `tests/api/test_runs_events_reattach.py` — enqueue + drain to completion, then a fresh subscriber attaches with from_seq=0; gets full replay-then-close
- [ ] **TB.18** `tests/api/test_runs_events_midstream.py` — enqueue, attach, simulate disconnect after N events, reconnect with `from_seq=N+1`, assert no duplicate events delivered
- [ ] **TB.19** `tests/api/test_runs_events_ownership.py` — user A enqueues a private run; user B `GET /api/runs/<id>/events` → 404; anonymous → 404
- [ ] **TB.20** `tests/api/test_runs_events_public.py` — user A enqueues a run and marks it `public` (010); anonymous `GET /events` works
- [ ] **TB.21** Run `./scripts/e2e.sh` — all 81+ cases still pass; no regression in the legacy `/chat` path

### Phase B.7 · docs

- [ ] **TB.22** Add docstring to `api/agent.py` explaining the two endpoints' relationship: `/chat` (old direct SSE) and `/enqueue` (new queue-backed, temporary)
- [ ] **TB.23** Add docstring to `api/runs.py` `events` route explaining the Accept-header dispatch (or query param)

**PR B acceptance:** can POST `/api/agent/enqueue` with a long-running pipeline, disconnect the response immediately, reconnect via `GET /api/runs/<run_id>/events?from_seq=0` and see the full event stream replayed + tailed live to completion.

---

## PR C — Cutover `POST /api/agent/chat` to enqueue-then-subscribe (~3h)

Goal: `POST /chat` internally uses the queue + event store. Delete the old direct-SSE code path. Delete the temporary `/enqueue` route. Old clients see identical behavior.

### Phase C.1 · rewire `POST /chat`

- [ ] **TC.1** `api/agent.py` rewrite `chat()` to:
  1. Build `RunSpec` from `ChatRequest` + `current_user`
  2. `run_id = await run_queue.enqueue(spec)`
  3. Return `EventSourceResponse` that consumes `event_store.subscribe(run_id, 0)` and yields frames in the same shape as today (`{"event": ev.type, "data": ev.model_dump_json()}`)
- [ ] **TC.2** Delete the old `agen = harness.run(...)` + `try/finally aclose()` block from `chat()`
- [ ] **TC.3** Delete the temporary `POST /api/agent/enqueue` route added in PR B
- [ ] **TC.4** `api/agent.py` simplify `POST /start` (MCP endpoint): it becomes a thin wrapper — `run_id = await run_queue.enqueue(spec); return {"run_id": run_id, "agent": req.agent, "status": "pending"}`. Delete the manual `_inflight_runs: set[asyncio.Task]`, the `_drain()` helper, and the `await agen.__anext__()` first-frame hack — all of that is now handled by the queue.

### Phase C.2 · response shape compatibility

- [ ] **TC.5** Compare SSE frame shape before/after — must include the same `event:` line, same `data:` JSON shape. PR A added an optional `seq` field to `AgentEvent`; verify it serializes cleanly and old clients tolerate it (forward-compat per Pydantic defaults)
- [ ] **TC.6** Verify the first frame is still `run_start` with the new `run_id`. The new flow: `enqueue` creates Run row → worker starts → worker emits `run_start` → event store appends with `seq=0` → subscriber's Phase 1 catch-up immediately pulls it. The order is: client sees `run_start` frame on the wire as before.

### Phase C.3 · tests

- [ ] **TC.7** `tests/api/test_chat_streaming_parity.py` — run the same chat request against pre- and post-PR-C code paths; assert frame-by-frame parity (modulo the new optional `seq`)
- [ ] **TC.8** `tests/api/test_chat_disconnect_resilience.py` — POST `/chat`, read first 3 frames, drop the connection; then `GET /api/runs/<run_id>/events?from_seq=3` and assert the run completes to terminal and we see all remaining events. **This is the marquee test for this change.**
- [ ] **TC.9** `tests/api/test_chat_long_running.py` — POST `/chat` against `company_research_pipeline` (mock mode), simulate a 60s disconnect, reconnect, assert run still completes
- [ ] **TC.10** `tests/api/test_mcp_start_compat.py` — POST `/api/agent/start` still returns `{run_id, agent, status}`; polling `/api/runs/<id>` still observes status transitions from `pending` → `running` → terminal
- [ ] **TC.11** Run `./scripts/e2e.sh` — full suite green; check Reporter trace for the marquee disconnect test specifically
- [ ] **TC.12** (Optional) Real-LLM smoke: `UTEKI_USE_MOCK_LLM=false ./scripts/e2e.sh -k chat_disconnect` to confirm the disconnect resilience holds end-to-end against a real provider

### Phase C.4 · cleanup

- [ ] **TC.13** Grep + delete now-dead code: `_inflight_runs`, `_drain` references in `api/agent.py`
- [ ] **TC.14** Update module docstring at top of `api/agent.py` — remove the references to "MCP draining" since the queue owns that
- [ ] **TC.15** Update `openspec/specs/harness/spec.md` "Run 生命周期" section to mention queue step [0] + `pending` status (mirror the delta in this change's `specs/harness/spec.md`)

**PR C acceptance:** disconnect-during-run resilience test passes; full E2E green; no in-flight runs lost on client disconnect; `/api/agent/start` MCP endpoint preserves its existing contract.

---

## PR D — Frontend URL persistence + reattach on mount (~4h)

Goal: web client persists `run_id` in URL and reattaches to in-flight runs on page load / refresh / route change.

### Phase D.1 · URL state

- [ ] **TD.1** `apps/web/lib/runs/useRunStream.ts` new hook:
  - Reads `?run` and `?seq` from URL on mount
  - If `?run` present: subscribe via `EventSource("/api/runs/<run_id>/events?from_seq=<seq+1>")`
  - On each event: update local state, update `?seq` via `router.replace`
  - On terminal: close EventSource, mark complete
- [ ] **TD.2** `apps/web/lib/runs/dedupe.ts` helper: `dedupeBySeq(events, lastSeenSeq) -> filtered`; defensive client-side dedupe against at-least-once delivery
- [ ] **TD.3** `apps/web/components/chat/ChatStream.tsx` (or equivalent — locate the current SSE-consuming component): on first frame `run_start`, call `router.replace(\`?run=${run_id}\`)`; on each subsequent event, update `?seq=<latest>`

### Phase D.2 · reattach UX

- [ ] **TD.4** `apps/web/app/(console)/chat/page.tsx` — on mount, if URL has `?run=…`, render a "Reattaching to run <id>…" placeholder and call `useRunStream({ runId })`
- [ ] **TD.5** `apps/web/app/(console)/runs/[id]/page.tsx` — already shows a run by id; switch its event source from "fetch + render static" to "subscribe live"; SSE stream handles both replay-then-close (terminal) and live tail (in-flight) uniformly
- [ ] **TD.6** Show a small badge near the run header: "Streaming live" (if not terminal) vs "Completed" (if terminal); derive from last received event type

### Phase D.3 · cross-route survival

- [ ] **TD.7** If the user navigates away from a chat page mid-run, the URL contains `?run=<id>` so they can navigate back; verify back-navigation reattaches cleanly
- [ ] **TD.8** Open the same `?run=<id>` URL in a second browser tab — both tabs should see the same events (proves multi-subscriber fan-out works in practice)

### Phase D.4 · disconnect resilience UI

- [ ] **TD.9** On `EventSource.onerror` (transient network drop): show "Reconnecting…" toast, exponential backoff retry up to 30s; on success, resume with current `lastSeenSeq`
- [ ] **TD.10** On permanent failure (e.g., 404 means the run no longer exists OR isn't yours): show "Run not available" error state with a "Start a new run" CTA

### Phase D.5 · tests

- [ ] **TD.11** Playwright test (via `services/api/tests/e2e/test_frontend_reattach.py` or new `apps/web/e2e/`): start a run, refresh the page mid-run, assert the run continues streaming events into the refreshed page
- [ ] **TD.12** Playwright test: open `?run=<id>` for a completed run in a fresh tab → assert full event replay renders, then "Completed" badge appears
- [ ] **TD.13** Manual smoke checklist (V12-style): see "Acceptance" below

**PR D acceptance:** see V section. Marquee scenarios: refresh mid-run survives; back-button mid-run survives; two-tab viewing works.

---

## 验收 (Acceptance)

- [ ] **V1** Disconnect resilience: POST `/api/agent/chat` against `company_research_pipeline` (mock mode), close the SSE response after first 3 frames, then `GET /api/runs/<run_id>/events?from_seq=3` → all remaining events + `done` arrive, `Run.status == "ok"`
- [ ] **V2** Reattach replay: completed run, fresh `GET /api/runs/<run_id>/events?from_seq=0` → all events replayed in order, stream closes after `done`
- [ ] **V3** Cursor correctness: `GET /api/runs/<run_id>/events?from_seq=10` for a run with 50 events → returns events 10..49 + terminal; no events 0..9
- [ ] **V4** Terminal sticky: after `done` is written, any further internal `event_store.append(...)` call raises `TerminalEventLogClosed`; harness handles defensively (logs warn, does not crash)
- [ ] **V5** Multi-subscriber: two concurrent `EventSource` connections to the same in-flight `run_id` both receive every event, in order, both close at terminal
- [ ] **V6** Cross-user 404: user A's private run; user B `GET /api/runs/<a_run_id>/events` → 404 (same shape as nonexistent); anonymous → 404
- [ ] **V7** Public run anon access: A marks run `public` (010 invariant); anonymous `GET /events` works, full replay
- [ ] **V8** MCP back-compat: POST `/api/agent/start` returns `{run_id, agent, status}`; status starts `pending`, transitions to `running` → `ok|error|timeout`
- [ ] **V9** Mock-mode contract preserved: `UTEKI_USE_MOCK_LLM=true ./scripts/e2e.sh` → all 81+ cases pass
- [ ] **V10** Real-LLM smoke: `UTEKI_USE_MOCK_LLM=false ./scripts/e2e.sh -k real_llm` runs a real `company_research_pipeline`, disconnects after 30s, reattaches, completes successfully
- [ ] **V11** Frontend refresh-mid-run: start a chat, wait 5s, hit F5 → page reloads, EventSource reconnects to the same `?run=<id>`, run completes
- [ ] **V12** Frontend back-button-mid-run: start a chat, navigate to /runs, come back to /chat?run=<id> → reattaches and continues streaming
- [ ] **V13** Frontend multi-tab: open same `?run=<id>` in two tabs → both render full event stream live
- [ ] **V14** Database invariants: `SELECT run_id, MAX(seq) FROM run_events GROUP BY run_id` aligns with `Run.events` length for runs created post-PR A; no `(run_id, seq)` duplicates; no events for non-existent run_ids
- [ ] **V15** Worker isolation: kill the client mid-run via `pkill` on the SSE process → worker continues; reattach later → run completed normally
- [ ] **V16** `pnpm typecheck` clean; `make lint` clean

---

## 时间盒估算

| PR | 估时 | 拆 commit 数 |
|---|---|---|
| PR A | 6h | 5-6 commits (table → store → harness → tests → docs) |
| PR B | 8h | 6-7 commits (RunSpec → queue → worker → endpoint → ownership lift → tests) |
| PR C | 3h | 3 commits (chat rewire → cleanup → docs/spec) |
| PR D | 4h | 4-5 commits (hook → reattach → resilience → playwright) |
| **合计** | **21h ≈ 2.5 工作日** | ~20 commits |

## Known follow-ups (out of scope; track separately)

- Boot-time sweep that marks orphaned `running` runs as `error` after a process crash (existing M5 issue, see `runs/sql_models.py:11-15`)
- `POST /api/runs/:id/cancel` REST endpoint backed by `RunQueue.cancel(...)`
- Migrate to `ArqRunQueue` + `PostgresRunEventStore` when single-process workers stop being enough
- Drop legacy `Run.events_json` column once `run_events` has baked for ≥ 1 deployment cycle
- Wire up Postgres `LISTEN/NOTIFY` for cross-process subscribe (replaces in-process `asyncio.Condition`)
