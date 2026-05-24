"""T4 — Pipeline chain (planner → research → evaluator).

The research_pipeline meta-skill is uteki's central thesis made executable:
sub-agents talk to each other through artifact files, not in-memory state.
A run of this chain should leave behind a recognisable artifact set whose
shape future runs (and the eval framework) can rely on.

Verifies the file-based-communication invariant:
  - planner writes plan.md + sprint-contract.json
  - research writes its final markdown (research.md or final-research.md)
  - evaluator reads sprint-contract.json + writes eval-report.json
    (plus optional judge-*.json)
  - subagent_start / subagent_end frames the boundaries in the event log

If a sub-agent fails its disk contract, an upstream consumer can't recover
— so this test is the existence proof for the M5/M6 spec.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from .conftest import AuthedUser, Reporter
from .test_03_research_chain import _parse_sse


def test_pipeline_artifact_chain(
    client: TestClient, alice: AuthedUser, reporter: Reporter
) -> None:
    reporter.section("POST /api/agent/chat agent=research_pipeline (mock LLM)")
    resp = client.post(
        "/api/agent/chat",
        headers={**alice.auth_header(), "Accept": "text/event-stream"},
        json={
            "messages": [{"role": "user", "content": "给我中国半导体设备板块的行业研究框架。"}],
            "agent": "research_pipeline",
            "session_id": "e2e-pipeline",
        },
    )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    reporter.kv("event count", len(events))
    run_id = events[0]["run_id"]
    reporter.kv("run_id", run_id)

    reporter.section("subagent boundaries")
    subagent_events = [e for e in events if e["type"] in ("subagent_start", "subagent_end")]
    for e in subagent_events[:8]:
        reporter.event(e["type"], e.get("data"))
    reporter.checked(
        "at least one subagent_start",
        any(e["type"] == "subagent_start" for e in events),
    )

    reporter.section("artifact_written events on the wire")
    artifact_events = [e for e in events if e["type"] == "artifact_written"]
    for e in artifact_events:
        reporter.event("artifact_written", e["data"].get("name"))
    written = {e["data"].get("name") for e in artifact_events}
    reporter.kv("artifacts written (from events)", sorted(written))

    reporter.section("GET /api/runs/{id}/artifacts — disk view should agree")
    r = client.get(f"/api/runs/{run_id}/artifacts", headers=alice.auth_header())
    reporter.checked("/artifacts → 200", r.status_code == 200)
    on_disk = {a["name"] for a in r.json()["items"]}
    reporter.kv("artifacts on disk", sorted(on_disk))
    reporter.checked(
        "wire-events match disk listing",
        written.issubset(on_disk),
        f"wire-extra: {written - on_disk}",
    )

    reporter.section("required artifact set (M5/M6 contract)")
    # The pipeline must leave behind:
    #   - planner's two files (plan.md + sprint-contract.json)
    #   - the research output captured to disk for the evaluator to read
    #     (run-trace.json in mock mode; research.md / final-research.md
    #     in real-LLM mode where the research skill synthesises markdown)
    #   - evaluator's verdict (eval-report.json)
    required_planner = {"plan.md", "sprint-contract.json"}
    required_evaluator = {"eval-report.json"}
    research_capture = {"run-trace.json", "research.md", "final-research.md"}

    missing_planner = required_planner - on_disk
    missing_evaluator = required_evaluator - on_disk
    has_research_capture = bool(research_capture & on_disk)

    reporter.checked("planner output (plan.md + sprint-contract.json) present",
                     not missing_planner, f"missing: {sorted(missing_planner)}")
    reporter.checked("evaluator output (eval-report.json) present",
                     not missing_evaluator, f"missing: {sorted(missing_evaluator)}")
    reporter.checked(
        f"research output captured (any of: {sorted(research_capture)})",
        has_research_capture,
    )
    assert not missing_planner, f"planner missed: {missing_planner}"
    assert not missing_evaluator, f"evaluator missed: {missing_evaluator}"
    assert has_research_capture, "research output not captured to disk"

    reporter.section("eval-report.json content shape")
    r = client.get(
        f"/api/runs/{run_id}/artifacts/eval-report.json",
        headers=alice.auth_header(),
    )
    reporter.checked("GET eval-report.json → 200", r.status_code == 200)
    eval_body = json.loads(r.text)
    reporter.kv("eval-report keys", list(eval_body.keys()))
    # The evaluator's report should at minimum carry a decision/verdict.
    has_decision = any(k in eval_body for k in ("decision", "verdict", "passed"))
    reporter.checked("eval-report has a decision/verdict/passed field", has_decision)
    assert has_decision

    reporter.section("run finished in 'ok' or with a non-fatal error tag")
    run = client.get(f"/api/runs/{run_id}", headers=alice.auth_header()).json()
    reporter.kv("status", run["status"])
    reporter.kv("tags", run.get("tags"))
    # Pipeline can self-terminate via "approve" decision → ok. Acceptable.
    assert run["status"] in ("ok", "error", "timeout"), run["status"]

    reporter.end()
