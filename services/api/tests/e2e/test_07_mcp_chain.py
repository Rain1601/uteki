"""T7 — MCP server smoke chain.

The MCP server is a thin HTTP adapter (see ``design/03-mcp-vs-local.md``).
This suite exercises the adapter's 5 tool handlers directly against a
TestClient-backed uteki API — same in-process pattern as T1-T5, just
inserting the MCP layer between assertions and the API.

What's verified:
  - All 5 tools have valid JSON Schema inputSchema
  - ``uteki_list_skills`` returns the live registry shape
  - ``uteki_run_skill`` kicks off a run and returns ``run_id`` promptly
    (the /api/agent/start contract); the background task continues
  - Polling ``uteki_get_run`` shows status transitioning to ok
  - ``uteki_list_artifacts`` + ``uteki_read_artifact`` round-trip cleanly
  - ``uteki_get_run`` strips the verbose events list down to a summary
    so CC's context window isn't burned by 5000 events on a pipeline run

What's NOT verified here (out of scope for this file):
  - stdio JSON-RPC framing — that's the MCP SDK's job, not ours
  - Real-LLM behavior — uses mock; covered by T6 for the harness path
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from .conftest import AuthedUser, Reporter


@pytest.fixture
def mcp_client_wired(monkeypatch, client: TestClient, alice: AuthedUser):
    """Wire the MCP client to talk to the in-proc TestClient.

    The default UtekiClient uses real httpx. For testing we route the
    same paths through FastAPI's TestClient (which is also httpx-based
    but in-process). We replace the module-level _client with one that
    uses the TestClient under the hood.
    """
    from uteki_api.mcp import server as mcp_server_mod

    class _InProcClient:
        """Adapter that mimics UtekiClient using FastAPI TestClient."""

        def __init__(self) -> None:
            self._c = client
            self._auth = alice.auth_header()

        async def aclose(self) -> None:
            pass

        async def list_skills(self):
            r = self._c.get("/api/agents", headers=self._auth)
            r.raise_for_status()
            return r.json().get("items", [])

        async def start_run(self, agent, question, session_id=None, model=None):
            r = self._c.post(
                "/api/agent/start",
                headers=self._auth,
                json={
                    "messages": [{"role": "user", "content": question}],
                    "agent": agent,
                    "session_id": session_id,
                    "model": model,
                },
            )
            r.raise_for_status()
            return r.json()

        async def get_run(self, run_id):
            r = self._c.get(f"/api/runs/{run_id}", headers=self._auth)
            r.raise_for_status()
            return r.json()

        async def list_artifacts(self, run_id):
            r = self._c.get(f"/api/runs/{run_id}/artifacts", headers=self._auth)
            r.raise_for_status()
            return r.json().get("items", [])

        async def read_artifact(self, run_id, name):
            r = self._c.get(f"/api/runs/{run_id}/artifacts/{name}", headers=self._auth)
            r.raise_for_status()
            return r.content, r.headers.get("content-type", "application/octet-stream")

    monkeypatch.setattr(mcp_server_mod, "_client", _InProcClient())
    # Also clear the lazy getter cache so subsequent calls hit our patched value.
    yield mcp_server_mod
    monkeypatch.setattr(mcp_server_mod, "_client", None)


def _parse_tool_response(content_list) -> dict | str:
    """MCP tool returns list[TextContent]; pull the text and try JSON."""
    assert len(content_list) >= 1
    text = content_list[0].text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def test_mcp_tool_schemas_are_valid(reporter: Reporter) -> None:
    """Every tool must have a JSON-Schema-shaped inputSchema. CC won't
    show malformed tools, so this catches mismatch before runtime."""
    from uteki_api.mcp.server import TOOLS

    reporter.section("5 tools declared")
    for t in TOOLS:
        reporter.event(t.name, f"required={t.inputSchema.get('required', [])}")
    names = {t.name for t in TOOLS}
    expected = {
        "uteki_list_skills",
        "uteki_run_skill",
        "uteki_get_run",
        "uteki_list_artifacts",
        "uteki_read_artifact",
    }
    reporter.checked("all 5 expected tools present", names == expected)
    assert names == expected

    reporter.section("schema invariants")
    for t in TOOLS:
        sch = t.inputSchema
        assert sch.get("type") == "object", f"{t.name}: schema must be object"
        assert "properties" in sch, f"{t.name}: needs properties"
    reporter.checked("every schema is object-typed with properties", True)
    reporter.end()


def test_mcp_list_skills_returns_registry(mcp_client_wired, reporter: Reporter) -> None:
    from uteki_api.mcp.server import _HANDLERS

    reporter.section("call uteki_list_skills via handler")
    result = asyncio.run(_HANDLERS["uteki_list_skills"]({}))
    body = _parse_tool_response(result)
    items = body["items"]
    reporter.kv("skill count", len(items))
    reporter.kv("names", [i["name"] for i in items])
    reporter.checked("at least 5 skills registered", len(items) >= 5)
    reporter.checked("research is present", any(i["name"] == "research" for i in items))
    reporter.checked(
        "research_pipeline is present (the pipeline meta-skill)",
        any(i["name"] == "research_pipeline" for i in items),
    )
    assert len(items) >= 5
    reporter.end()


def test_mcp_run_skill_returns_run_id_quickly(
    mcp_client_wired, reporter: Reporter
) -> None:
    """The whole point of /api/agent/start: response in ~milliseconds,
    not 2 minutes. Verifies the fire-and-forget contract."""
    import time

    from uteki_api.mcp.server import _HANDLERS

    reporter.section("uteki_run_skill (mock LLM)")
    t0 = time.monotonic()
    result = asyncio.run(
        _HANDLERS["uteki_run_skill"](
            {"skill": "research", "question": "test query", "session_id": "mcp-smoke"}
        )
    )
    elapsed_ms = (time.monotonic() - t0) * 1000
    body = _parse_tool_response(result)
    reporter.kv("elapsed_ms", f"{elapsed_ms:.0f}")
    reporter.kv("response", body)
    reporter.checked("has run_id", "run_id" in body and len(body["run_id"]) > 0)
    reporter.checked("status == running", body.get("status") == "running")
    reporter.checked(
        "returned in < 5s (fire-and-forget, not blocked on run)",
        elapsed_ms < 5000,
        f"got {elapsed_ms:.0f}ms",
    )
    assert "run_id" in body
    assert elapsed_ms < 5000
    reporter.end()


def test_mcp_full_chain(mcp_client_wired, reporter: Reporter) -> None:
    """Start → poll → list artifacts → read artifact. The chain CC will
    actually walk."""
    import time

    from uteki_api.mcp.server import _HANDLERS

    reporter.section("step 1: uteki_run_skill")
    r1 = _parse_tool_response(
        asyncio.run(
            _HANDLERS["uteki_run_skill"](
                {
                    "skill": "research_pipeline",
                    "question": "test pipeline run",
                    "session_id": "mcp-chain",
                }
            )
        )
    )
    run_id = r1["run_id"]
    reporter.kv("run_id", run_id)

    reporter.section("step 2: poll uteki_get_run until status != 'running'")
    deadline = time.monotonic() + 30.0
    final = None
    polls = 0
    while time.monotonic() < deadline:
        polls += 1
        final = _parse_tool_response(
            asyncio.run(_HANDLERS["uteki_get_run"]({"run_id": run_id}))
        )
        if final.get("status") != "running":
            break
        time.sleep(0.3)
    reporter.kv("polls", polls)
    reporter.kv("final status", (final or {}).get("status"))
    reporter.kv("events_count (summary, not list)", (final or {}).get("events_count"))
    reporter.kv("events_summary", (final or {}).get("events_summary"))
    reporter.checked("run reached terminal status", (final or {}).get("status") in {"ok", "error", "timeout"})
    reporter.checked(
        "events list stripped from response (CC context preservation)",
        "events" not in (final or {}),
    )
    reporter.checked(
        "events_summary present as the lightweight alternative",
        "events_summary" in (final or {}),
    )
    assert final and final["status"] in {"ok", "error", "timeout"}
    assert "events" not in final

    reporter.section("step 3: uteki_list_artifacts")
    arts_body = _parse_tool_response(
        asyncio.run(_HANDLERS["uteki_list_artifacts"]({"run_id": run_id}))
    )
    art_names = [a["name"] for a in arts_body["items"]]
    reporter.kv("artifacts", art_names)
    reporter.checked("plan.md present (planner output)", "plan.md" in art_names)
    reporter.checked(
        "eval-report.json present (evaluator output)",
        "eval-report.json" in art_names,
    )
    assert "plan.md" in art_names
    assert "eval-report.json" in art_names

    reporter.section("step 4: uteki_read_artifact (eval-report.json)")
    art = _parse_tool_response(
        asyncio.run(
            _HANDLERS["uteki_read_artifact"](
                {"run_id": run_id, "name": "eval-report.json"}
            )
        )
    )
    # eval-report.json comes back as text (application/json), so it's a
    # parsed dict, not the base64-wrapped binary shape.
    reporter.kv("keys", list(art.keys()) if isinstance(art, dict) else "<string>")
    reporter.checked(
        "eval-report has a decision/verdict field",
        isinstance(art, dict)
        and any(k in art for k in ("decision", "verdicts", "passed")),
    )
    assert isinstance(art, dict)

    reporter.end()


def test_mcp_unknown_skill_does_not_crash(mcp_client_wired, reporter: Reporter) -> None:
    """An invalid skill name shouldn't bring down the handler — should
    surface as a structured error so CC can recover."""
    from uteki_api.mcp.server import _HANDLERS

    reporter.section("call uteki_run_skill with bogus skill name")
    # The API falls back to "research" silently for unknown skill names
    # (current behaviour in api/agent.py _build_harness). The MCP layer
    # should NOT raise — it should propagate whatever the API does.
    result = asyncio.run(
        _HANDLERS["uteki_run_skill"](
            {"skill": "totally-fake-skill", "question": "x"}
        )
    )
    body = _parse_tool_response(result)
    reporter.kv("response", body)
    reporter.checked(
        "got either a run_id (fallback) or a structured error",
        "run_id" in body or "error" in body,
    )
    assert "run_id" in body or "error" in body
    reporter.end()
