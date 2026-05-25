"""T2 — Tenant isolation across every user-scoped surface.

The M4 promise is: A and B can never observe each other's state. Tests
hit each surface that holds user-scoped data and confirms cross-user
attempts return 404 (same shape as "doesn't exist", to avoid leaking
existence).

Surfaces probed:
  - RunStore (list + get + events) via REST
  - ArtifactStore (list + get) via REST + filesystem inspection
  - In-process Memory short-term (same session_id with different
    user_id must not collide — would let A read B's events via URL
    crafting in any future "rehydrate session" endpoint)
  - EvalHistoryStore (list_recent + list_case)
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi.testclient import TestClient

from .conftest import AuthedUser, Reporter


def test_run_list_and_get_isolation(
    client: TestClient, alice: AuthedUser, bob: AuthedUser, reporter: Reporter
) -> None:
    from uteki_api.runs import Run, default_run_store
    from uteki_api.schemas.events import AgentEvent

    reporter.section("seed one run for each user (in-proc RunStore)")

    async def seed(uid: str, label: str) -> str:
        rid = f"iso-{label}"
        await default_run_store.create(
            Run(
                id=rid,
                user_id=uid,
                skill="research",
                triggered_by="user",
                started_at=time.time(),
            )
        )
        await default_run_store.append_event(
            rid, AgentEvent(type="delta", run_id=rid, data={"text": f"hi from {label}"})
        )
        await default_run_store.finish(rid, "ok", f"hi from {label}")
        return rid

    rid_a = asyncio.run(seed(alice.id, "A"))
    rid_b = asyncio.run(seed(bob.id, "B"))
    reporter.kv("alice run", rid_a)
    reporter.kv("bob run", rid_b)

    reporter.section("each user's /api/runs only contains own runs")
    la = client.get("/api/runs", headers=alice.auth_header())
    lb = client.get("/api/runs", headers=bob.auth_header())
    a_ids = [r["id"] for r in la.json()["items"]]
    b_ids = [r["id"] for r in lb.json()["items"]]
    reporter.kv("alice sees", a_ids)
    reporter.kv("bob sees", b_ids)
    reporter.checked("alice sees only her run", a_ids == [rid_a])
    reporter.checked("bob sees only his run", b_ids == [rid_b])
    assert a_ids == [rid_a]
    assert b_ids == [rid_b]

    reporter.section("cross-user GET attempts → 404 (same as not-exist)")
    for label, path in [
        ("alice→bob's run", f"/api/runs/{rid_b}"),
        ("alice→bob's events", f"/api/runs/{rid_b}/events"),
        ("alice→bob's artifacts", f"/api/runs/{rid_b}/artifacts"),
        ("bob→alice's run", f"/api/runs/{rid_a}"),
    ]:
        h = alice.auth_header() if label.startswith("alice") else bob.auth_header()
        r = client.get(path, headers=h)
        reporter.checked(f"{label} → 404", r.status_code == 404, f"got {r.status_code}")
        assert r.status_code == 404, label

    reporter.section("a totally-bogus run id is also 404 (same shape as cross-user)")
    r = client.get("/api/runs/does-not-exist", headers=alice.auth_header())
    reporter.kv("body", r.json())
    assert r.status_code == 404

    reporter.end()


def test_artifact_partition_on_disk(
    client: TestClient, alice: AuthedUser, bob: AuthedUser, reporter: Reporter
) -> None:
    """Direct ArtifactStore exercise — disk paths physically partition."""
    from uteki_api.artifacts import default_artifact_store

    api_root = Path(__file__).resolve().parents[2]

    reporter.section("write same-name artifact for each user")

    async def write_three() -> None:
        await default_artifact_store.write(
            run_id="run-a1", name="plan.md", content=b"# Alice's plan",
            kind="markdown", written_by="research", description="alice plan",
            user_id=alice.id,
        )
        await default_artifact_store.write(
            run_id="run-b1", name="plan.md", content=b"# Bob's plan",
            kind="markdown", written_by="research", description="bob plan",
            user_id=bob.id,
        )

    asyncio.run(write_three())

    reporter.section("reading with wrong user must FileNotFoundError")

    async def cross_read() -> tuple[bool, bool]:
        a_leaks_to_b = True
        b_leaks_to_a = True
        try:
            await default_artifact_store.read("run-a1", "plan.md", bob.id)
        except FileNotFoundError:
            a_leaks_to_b = False
        try:
            await default_artifact_store.read("run-b1", "plan.md", alice.id)
        except FileNotFoundError:
            b_leaks_to_a = False
        return a_leaks_to_b, b_leaks_to_a

    a_leaks, b_leaks = asyncio.run(cross_read())
    reporter.checked("alice's file not readable by bob's id", not a_leaks)
    reporter.checked("bob's file not readable by alice's id", not b_leaks)
    assert not a_leaks and not b_leaks

    reporter.section("inspect on-disk layout")
    runs_root = api_root / "data" / "runs" / "users"
    found = sorted(p.relative_to(api_root).as_posix() for p in runs_root.rglob("*") if p.is_file())
    for p in found:
        reporter.event("file", p)
    alice_paths = [p for p in found if alice.id in p]
    bob_paths = [p for p in found if bob.id in p]
    reporter.checked("alice has files under data/runs/users/<alice.id>/", bool(alice_paths))
    reporter.checked("bob has files under data/runs/users/<bob.id>/", bool(bob_paths))
    reporter.checked(
        "no file lives under both users (no shared bucket)",
        not (set(alice_paths) & set(bob_paths)),
    )
    assert alice_paths and bob_paths

    reporter.end()


def test_memory_short_term_no_session_id_collision(reporter: Reporter) -> None:
    """Two users with same session_id must NOT see each other's events."""
    from uteki_api.memory.in_memory import InMemoryStore
    from uteki_api.schemas.chat import ChatMessage
    from uteki_api.schemas.events import AgentEvent

    reporter.section("two users, same session_id='shared-session', distinct events")

    async def run() -> tuple[list[str], list[str]]:
        m = InMemoryStore()
        await m.append_event("uid-A", "shared", AgentEvent(type="delta", data={"t": "A-only"}))
        await m.append_event("uid-B", "shared", AgentEvent(type="delta", data={"t": "B-only"}))
        await m.append_message("uid-A", "shared", ChatMessage(role="user", content="A msg"))
        await m.append_message("uid-B", "shared", ChatMessage(role="user", content="B msg"))
        a_ev = [e.data.get("t") for e in await m.get_events("uid-A", "shared")]
        b_ev = [e.data.get("t") for e in await m.get_events("uid-B", "shared")]
        return a_ev, b_ev

    a_ev, b_ev = asyncio.run(run())
    reporter.kv("A's events", a_ev)
    reporter.kv("B's events", b_ev)
    reporter.checked("A sees only A-only", a_ev == ["A-only"])
    reporter.checked("B sees only B-only", b_ev == ["B-only"])
    assert a_ev == ["A-only"]
    assert b_ev == ["B-only"]

    reporter.end()


def test_eval_history_partition(
    client: TestClient, alice: AuthedUser, bob: AuthedUser, reporter: Reporter
) -> None:
    from uteki_api.eval.store import EvalRecord, default_eval_history

    reporter.section("append eval records under three partitions")

    async def seed() -> None:
        await default_eval_history.append(
            alice.id, EvalRecord(case_id="case1", pass_rate=1.0, notes="alice")
        )
        await default_eval_history.append(
            bob.id, EvalRecord(case_id="case1", pass_rate=0.0, notes="bob")
        )
        await default_eval_history.append(
            "system", EvalRecord(case_id="case1", pass_rate=0.5, notes="system")
        )

    asyncio.run(seed())

    reporter.section("/api/eval/history is caller-scoped")
    ra = client.get("/api/eval/history", headers=alice.auth_header())
    rb = client.get("/api/eval/history", headers=bob.auth_header())
    a_notes = [r["notes"] for r in ra.json()["items"]]
    b_notes = [r["notes"] for r in rb.json()["items"]]
    reporter.kv("alice history notes", a_notes)
    reporter.kv("bob history notes", b_notes)
    reporter.checked("alice sees only her own", a_notes == ["alice"])
    reporter.checked("bob sees only his own", b_notes == ["bob"])
    reporter.checked("neither sees 'system' (platform partition)",
                     "system" not in a_notes and "system" not in b_notes)
    assert a_notes == ["alice"]
    assert b_notes == ["bob"]

    reporter.end()
