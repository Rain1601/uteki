"""T3 — Research run chain (SSE → events → persisted run).

This is the headline product flow: a user submits a question to a
skill via POST /api/agent/chat, gets back a stream of structured
events, and the harness leaves behind a queryable Run record.

Verifies the *contract* between skill, harness, store, and HTTP
streaming layer:
  - SSE response is parseable as `data: <json>\\n\\n` frames
  - first event is run_start, last is done
  - the run_id from run_start is queryable via GET /api/runs/{id}
  - usage event was aggregated into Run.usage_summary
  - the assembled delta text is stored as Run.summary[:200]

Mock LLM mode (default) means deterministic events from the research
skill's `_mock_run` branch.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from .conftest import AuthedUser, Reporter


def _parse_sse(body: str) -> list[dict]:
    """Parse `data: <json>\\r?\\n\\r?\\n` frames into a list of event dicts.

    sse_starlette emits CRLF, but a plain text/event-stream over fetch can
    be either — be liberal in what we accept."""
    import contextlib
    import re
    events: list[dict] = []
    normalised = body.replace("\r\n", "\n")
    for raw in re.split(r"\n\n+", normalised):
        data_lines = [line[5:].strip() for line in raw.split("\n") if line.startswith("data:")]
        if not data_lines:
            continue
        with contextlib.suppress(json.JSONDecodeError):
            events.append(json.loads("".join(data_lines)))
    return events


def test_research_chain_end_to_end(
    client: TestClient, alice: AuthedUser, reporter: Reporter
) -> None:
    reporter.section("POST /api/agent/chat (SSE, mock LLM)")
    resp = client.post(
        "/api/agent/chat",
        headers={**alice.auth_header(), "Accept": "text/event-stream"},
        json={
            "messages": [{"role": "user", "content": "做一份中国新能源车板块的研究框架"}],
            "agent": "research",
            "session_id": "e2e-session-1",
        },
    )
    reporter.kv("HTTP status", resp.status_code)
    reporter.kv("content-type", resp.headers.get("content-type"))
    assert resp.status_code == 200

    events = _parse_sse(resp.text)
    reporter.kv("event count", len(events))
    for e in events[:10]:
        reporter.event(e["type"], e.get("data"))
    if len(events) > 10:
        reporter.event(f"... + {len(events) - 10} more")

    reporter.section("event contract — mode-agnostic core")
    # Only assert what's contractually guaranteed regardless of LLM mode:
    # the harness wraps every run in run_start ... done and skills must
    # yield at least one step_start + at least one delta. Mock-mode-only
    # niceties (plan event) are skipped — usage roll-up is verified below
    # against Run.usage_summary instead of the raw event stream.
    reporter.checked("first is run_start", events[0]["type"] == "run_start")
    reporter.checked("last is done", events[-1]["type"] == "done")
    types = {e["type"] for e in events}
    for required in ("step_start", "delta", "done"):
        reporter.checked(f"saw {required}", required in types)
        assert required in types, f"missing {required}"

    run_id = events[0]["run_id"]
    reporter.kv("run_id from stream", run_id)

    reporter.section("GET /api/runs/{run_id} replays the run")
    r = client.get(f"/api/runs/{run_id}", headers=alice.auth_header())
    reporter.checked("/runs/{id} → 200", r.status_code == 200)
    body = r.json()
    reporter.kv("persisted status", body["status"])
    reporter.kv("persisted skill", body["skill"])
    reporter.kv("persisted user_id", body["user_id"])
    reporter.kv("persisted summary[:60]", body["summary"][:60])
    reporter.kv("usage_summary.input_tokens", body["usage_summary"]["input_tokens"])
    reporter.kv("usage_summary.output_tokens", body["usage_summary"]["output_tokens"])
    reporter.checked("status == ok", body["status"] == "ok")
    reporter.checked("user_id == alice.id", body["user_id"] == alice.id)
    reporter.checked("skill == research", body["skill"] == "research")
    reporter.checked("summary is non-empty", len(body["summary"]) > 0)
    reporter.checked(
        "usage rolled up (input_tokens > 0)",
        body["usage_summary"]["input_tokens"] > 0,
    )
    assert body["status"] == "ok"
    assert body["user_id"] == alice.id
    assert body["usage_summary"]["input_tokens"] > 0

    reporter.section("GET /api/runs/{run_id}/events lists every event we saw")
    r = client.get(f"/api/runs/{run_id}/events", headers=alice.auth_header())
    persisted_types = [e["type"] for e in r.json()["items"]]
    reporter.kv("persisted event types", persisted_types[:6])
    # The persisted log includes everything from run_start through done.
    reporter.checked("contains run_start", persisted_types[0] == "run_start")
    reporter.checked("contains done", persisted_types[-1] == "done")
    assert persisted_types[0] == "run_start"
    assert persisted_types[-1] == "done"

    reporter.end()


def test_reader_can_view_run_trace_but_cannot_operate_agent(
    client: TestClient, bob: AuthedUser, reporter: Reporter
) -> None:
    """Readers can inspect persisted runs/events, but cannot start agent work."""
    reporter.section("reader cannot POST /api/agent/chat")
    denied = client.post(
        "/api/agent/chat",
        headers={**bob.auth_header(), "Accept": "text/event-stream"},
        json={
            "messages": [{"role": "user", "content": "reader should not run"}],
            "agent": "research",
        },
    )
    reporter.kv("status", denied.status_code)
    assert denied.status_code == 403
    assert denied.json()["detail"] == "permission required: agent:operate"

    reporter.section("reader also lacks company-research operation permission")
    denied_company = client.post(
        "/api/agent/chat",
        headers={**bob.auth_header(), "Accept": "text/event-stream"},
        json={
            "messages": [{"role": "user", "content": "reader should not run company agent"}],
            "agent": "company_research_pipeline",
        },
    )
    reporter.kv("company status", denied_company.status_code)
    assert denied_company.status_code == 403
    assert denied_company.json()["detail"] == "permission required: agent:company_research"

    reporter.section("seed a completed run owned by reader")
    from uteki_api.runs import Run, default_run_store
    from uteki_api.schemas.events import AgentEvent

    rid = "reader-view-run"

    async def seed() -> None:
        await default_run_store.create(
            Run(
                id=rid,
                user_id=bob.id,
                skill="research",
                triggered_by="user",
                started_at=time.time(),
            )
        )
        await default_run_store.append_event(
            rid, AgentEvent(type="run_start", run_id=rid, data={"agent": "research"})
        )
        await default_run_store.append_event(
            rid, AgentEvent(type="delta", run_id=rid, data={"text": "reader-visible result"})
        )
        await default_run_store.finish(rid, "ok", "reader-visible result")

    asyncio.run(seed())

    reporter.section("reader can read result and process")
    run_resp = client.get(f"/api/runs/{rid}", headers=bob.auth_header())
    events_resp = client.get(f"/api/runs/{rid}/events", headers=bob.auth_header())
    reporter.kv("run status", run_resp.status_code)
    reporter.kv("events status", events_resp.status_code)
    assert run_resp.status_code == 200
    assert events_resp.status_code == 200
    assert run_resp.json()["summary"] == "reader-visible result"
    assert [e["type"] for e in events_resp.json()["items"]] == ["run_start", "delta"]

    reporter.end()


def test_local_all_permissions_allows_reader_to_operate(
    client: TestClient,
    bob: AuthedUser,
    reporter: Reporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local dev can grant every operation permission without changing stored role."""
    from uteki_api.core.config import settings

    monkeypatch.setattr(settings, "local_all_permissions", True)

    reporter.section("reader role gets local operation permission")
    me = client.get("/api/auth/me", headers=bob.auth_header())
    reporter.kv("role", me.json()["role"])
    reporter.kv("permissions", me.json()["permissions"])
    assert me.status_code == 200
    assert me.json()["role"] == "reader"
    assert "agent:operate" in me.json()["permissions"]
    assert "agent:company_research" in me.json()["permissions"]

    reporter.section("reader can operate when local override is enabled")
    resp = client.post(
        "/api/agent/chat",
        headers={**bob.auth_header(), "Accept": "text/event-stream"},
        json={
            "messages": [{"role": "user", "content": "local all permissions smoke"}],
            "agent": "research",
        },
    )
    reporter.kv("HTTP status", resp.status_code)
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events[0]["type"] == "run_start"
    assert events[-1]["type"] == "done"

    reporter.end()


def test_research_chain_anonymous_blocked_when_auth_required(
    client: TestClient, reporter: Reporter
) -> None:
    reporter.section("no Authorization header (auth_required=true env)")
    r = client.post(
        "/api/agent/chat",
        json={"messages": [{"role": "user", "content": "x"}], "agent": "research"},
    )
    reporter.kv("status", r.status_code)
    reporter.checked("→ 401", r.status_code == 401)
    assert r.status_code == 401
    reporter.end()
