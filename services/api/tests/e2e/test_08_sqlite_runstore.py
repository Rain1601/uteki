"""T8 — SqliteRunStore.

Verifies the SQLite-backed run store's contract end-to-end:
- create / append_event / finish round-trips correctly
- get returns the live in-flight Run while the harness is mutating it
  (mid-flight invariant for harness's mutate-then-finish pattern)
- list returns user-scoped rows ordered newest-first
- A FRESH store instance (simulating a separate process) can read
  finished runs — the cross-process invariant that justifies SQLite
  over InMemory

Doesn't go through HTTP — direct store calls. Cross-process behavior
through the HTTP API is exercised by the existing T7 MCP chain (which
hits the live API via TestClient).
"""

from __future__ import annotations

import asyncio
import time

import pytest
from sqlmodel import SQLModel, create_engine

from uteki_api.runs import Run, SqliteRunStore
from uteki_api.runs.sql_models import RunRow  # noqa: F401 — register table
from uteki_api.schemas.events import AgentEvent

from .conftest import Reporter


@pytest.fixture
def engine(clean_data_dir):  # noqa: ARG001 — autouse cleanup fires
    """Per-test SQLite engine on a fresh file."""
    db_path = clean_data_dir / "t08.db"
    eng = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


def test_sqlite_store_round_trip(engine, reporter: Reporter) -> None:
    """Single-process happy path."""
    store = SqliteRunStore(engine)

    async def go() -> Run:
        run = Run(
            id="t08-A",
            user_id="user-alice",
            skill="research",
            triggered_by="user",
            started_at=time.time(),
            user_input="test input",
        )
        await store.create(run)
        await store.append_event(
            "t08-A",
            AgentEvent(type="run_start", run_id="t08-A", data={"agent": "research"}),
        )
        await store.append_event(
            "t08-A",
            AgentEvent(type="delta", run_id="t08-A", data={"text": "hello"}),
        )
        await store.finish("t08-A", "ok", "hello world")
        return await store.get("t08-A", user_id="user-alice")

    reporter.section("create → append × 2 → finish → get")
    final = asyncio.run(go())
    reporter.kv("status", final.status)
    reporter.kv("summary", final.summary)
    reporter.kv("event count", len(final.events))
    reporter.kv("event types", [e.type for e in final.events])
    reporter.checked("status == ok", final.status == "ok")
    reporter.checked("summary persisted", final.summary == "hello world")
    reporter.checked("both events persisted", len(final.events) == 2)
    assert final.status == "ok"
    assert len(final.events) == 2
    reporter.end()


def test_sqlite_store_returns_live_run_during_flight(engine, reporter: Reporter) -> None:
    """The harness's mutate-then-finish pattern: get() during an in-flight
    run must return the SAME Run object so mutations on .tags and
    .usage_summary land back in finish()'s flush. Without this, the harness's
    'set usage_summary then call finish()' sequence silently loses the usage."""
    store = SqliteRunStore(engine)

    async def go() -> tuple[Run, Run, int]:
        run = Run(
            id="t08-B",
            user_id="user-alice",
            skill="research",
            triggered_by="user",
            started_at=time.time(),
        )
        await store.create(run)
        # Get mid-flight — must be the SAME object the caller passed in
        mid = await store.get("t08-B", user_id="user-alice")
        mid.tags.append("auto-approved")
        mid.usage_summary.input_tokens = 12345
        await store.finish("t08-B", "ok", "")
        # After finish, the object is evicted from cache. Fresh get
        # rebuilds from DB.
        post = await store.get("t08-B", user_id="user-alice")
        return mid, post, 12345

    reporter.section("get() during flight returns the harness-held object")
    mid, post, expected_tokens = asyncio.run(go())
    reporter.kv("mid.tags (harness mutated)", mid.tags)
    reporter.kv("post.tags (loaded from DB)", post.tags)
    reporter.kv("mid.usage_summary.input_tokens", mid.usage_summary.input_tokens)
    reporter.kv("post.usage_summary.input_tokens", post.usage_summary.input_tokens)
    reporter.checked(
        "tag added mid-flight survived through finish flush",
        "auto-approved" in post.tags,
    )
    reporter.checked(
        "usage_summary mutation mid-flight survived through finish flush",
        post.usage_summary.input_tokens == expected_tokens,
    )
    assert "auto-approved" in post.tags
    assert post.usage_summary.input_tokens == expected_tokens
    reporter.end()


def test_sqlite_store_list_user_scoped(engine, reporter: Reporter) -> None:
    """list() filters by user_id and orders newest-first."""
    store = SqliteRunStore(engine)

    async def go() -> tuple[list[Run], list[Run]]:
        t0 = time.time()
        for uid, label in [("alice", "A1"), ("bob", "B1"), ("alice", "A2"), ("alice", "A3")]:
            t0 += 1.0
            r = Run(
                id=f"t08-list-{label}",
                user_id=uid,
                skill="research",
                triggered_by="user",
                started_at=t0,
            )
            await store.create(r)
            await store.finish(r.id, "ok", "")
        return (
            await store.list("alice"),
            await store.list("bob"),
        )

    reporter.section("seed 3 alice runs + 1 bob run, then list")
    alice_runs, bob_runs = asyncio.run(go())
    a_ids = [r.id for r in alice_runs]
    b_ids = [r.id for r in bob_runs]
    reporter.kv("alice sees", a_ids)
    reporter.kv("bob sees", b_ids)
    reporter.checked("alice sees exactly her 3", set(a_ids) == {"t08-list-A1", "t08-list-A2", "t08-list-A3"})
    reporter.checked("bob sees exactly his 1", b_ids == ["t08-list-B1"])
    reporter.checked(
        "alice's list is newest-first (A3 before A1)",
        a_ids.index("t08-list-A3") < a_ids.index("t08-list-A1"),
    )
    assert set(a_ids) == {"t08-list-A1", "t08-list-A2", "t08-list-A3"}
    assert b_ids == ["t08-list-B1"]
    reporter.end()


def test_sqlite_store_cross_process_read(engine, reporter: Reporter) -> None:
    """Simulate the 'MCP server reads a run created by HTTP server' case
    by using two separate SqliteRunStore instances on the same DB.

    Process 1 (HTTP server): creates a run, appends events, finishes.
    Process 2 (MCP server): instantiates a fresh store, reads the same
    run, sees full state.
    """
    proc1 = SqliteRunStore(engine)
    proc2 = SqliteRunStore(engine)  # fresh instance: no shared cache

    async def go() -> Run:
        run = Run(
            id="t08-xp",
            user_id="alice",
            skill="research",
            triggered_by="user",
            started_at=time.time(),
        )
        await proc1.create(run)
        await proc1.append_event(
            "t08-xp",
            AgentEvent(type="delta", run_id="t08-xp", data={"text": "from p1"}),
        )
        await proc1.finish("t08-xp", "ok", "p1 says hi")
        # Now proc2 reads (no in-process cache hit; will load from DB)
        return await proc2.get("t08-xp", user_id="alice")

    reporter.section("proc1 writes, proc2 reads (different stores, same engine)")
    read = asyncio.run(go())
    reporter.kv("status (proc2 view)", read.status)
    reporter.kv("summary (proc2 view)", read.summary)
    reporter.kv("event count (proc2 view)", len(read.events))
    reporter.checked("proc2 sees status=ok", read.status == "ok")
    reporter.checked("proc2 sees summary", read.summary == "p1 says hi")
    reporter.checked("proc2 sees the event", len(read.events) == 1)
    assert read.status == "ok"
    assert read.summary == "p1 says hi"
    assert len(read.events) == 1
    reporter.end()


def test_sqlite_store_cross_process_inflight(engine, reporter: Reporter) -> None:
    """The in-flight cross-process behavior: proc2 sees the run exists
    with status='running' but events=[] until proc1's finish flushes.

    Why this matters: MCP server polls get_run on a still-running
    pipeline. It needs to see the run exists (status=running) so it
    knows to keep polling — but won't see the raw event log until done.
    That's the documented MVP behavior.
    """
    proc1 = SqliteRunStore(engine)
    proc2 = SqliteRunStore(engine)

    async def go() -> tuple[Run, Run]:
        run = Run(
            id="t08-xp-inflight",
            user_id="alice",
            skill="research",
            triggered_by="user",
            started_at=time.time(),
        )
        await proc1.create(run)
        await proc1.append_event(
            "t08-xp-inflight",
            AgentEvent(type="delta", run_id="t08-xp-inflight", data={"text": "in flight"}),
        )
        # proc2 reads NOW, before finish
        mid_view = await proc2.get("t08-xp-inflight", user_id="alice")
        await proc1.finish("t08-xp-inflight", "ok", "")
        # proc2 reads again after finish
        post_view = await proc2.get("t08-xp-inflight", user_id="alice")
        return mid_view, post_view

    reporter.section("proc1 mid-flight, proc2 polls")
    mid, post = asyncio.run(go())
    reporter.kv("proc2 mid-flight status", mid.status)
    reporter.kv("proc2 mid-flight event count", len(mid.events))
    reporter.kv("proc2 post-finish status", post.status)
    reporter.kv("proc2 post-finish event count", len(post.events))
    reporter.checked(
        "mid-flight: proc2 sees status=running (run exists)",
        mid.status == "running",
    )
    reporter.checked(
        "mid-flight: proc2 sees events=[] (buffered in proc1, not yet flushed)",
        len(mid.events) == 0,
    )
    reporter.checked(
        "post-finish: proc2 sees terminal status",
        post.status == "ok",
    )
    reporter.checked(
        "post-finish: proc2 sees the event proc1 buffered",
        len(post.events) == 1,
    )
    assert mid.status == "running" and len(mid.events) == 0
    assert post.status == "ok" and len(post.events) == 1
    reporter.end()


def test_sqlite_store_cross_user_404_shape(engine, reporter: Reporter) -> None:
    """get(run_id, user_id=B) for A's run must raise KeyError — same
    shape as 'doesn't exist' (per the multi-tenant invariant)."""
    store = SqliteRunStore(engine)

    async def go() -> None:
        run = Run(
            id="t08-iso",
            user_id="alice",
            skill="research",
            triggered_by="user",
            started_at=time.time(),
        )
        await store.create(run)
        await store.finish("t08-iso", "ok", "")
        # Bob asks for alice's run
        with pytest.raises(KeyError):
            await store.get("t08-iso", user_id="bob")

    reporter.section("bob → get(alice's run) → KeyError")
    asyncio.run(go())
    reporter.checked("KeyError raised (404 shape preserved)", True)
    reporter.end()
