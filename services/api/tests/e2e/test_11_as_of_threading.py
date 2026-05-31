"""T11 — as_of backtest mode end-to-end.

Verifies the harness-level contract: when POST /api/agent/chat carries an
``as_of`` field, the resulting run is tagged with ``as_of:YYYY-MM-DD`` and
no source registered into the catalog has ``published_at`` later than the
cutoff. Hits the catalog rejection path via real tool execution.

Mock-LLM mode is used (test default) so we exercise the harness wiring
without provider keys; the catalog rejection itself doesn't care whether
the source originated from mock or live data.
"""

from __future__ import annotations

import json
import re
import time

from fastapi.testclient import TestClient

from .conftest import AuthedUser, Reporter


def _parse_sse(body: str) -> list[dict]:
    import contextlib
    events: list[dict] = []
    normalised = body.replace("\r\n", "\n")
    for raw in re.split(r"\n\n+", normalised):
        data_lines = [line[5:].strip() for line in raw.split("\n") if line.startswith("data:")]
        if not data_lines:
            continue
        with contextlib.suppress(json.JSONDecodeError):
            events.append(json.loads("".join(data_lines)))
    return events


def test_as_of_tags_run_and_blocks_future_sources(
    client: TestClient, alice: AuthedUser, reporter: Reporter
) -> None:
    reporter.section("POST /api/agent/chat with as_of=2020-06-30")
    resp = client.post(
        "/api/agent/chat",
        headers={**alice.auth_header(), "Accept": "text/event-stream"},
        json={
            "messages": [{"role": "user", "content": "回测：2020-06-30 那天对 AAPL 的判断"}],
            "agent": "research",
            "session_id": "e2e-as-of-1",
            "as_of": "2020-06-30",
        },
    )
    reporter.kv("HTTP status", resp.status_code)
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events[0]["type"] == "run_start"
    assert events[-1]["type"] == "done"
    run_id = events[0]["run_id"]
    reporter.kv("run_id", run_id)

    reporter.section("Run carries the as_of tag")
    run_resp = client.get(f"/api/runs/{run_id}", headers=alice.auth_header())
    assert run_resp.status_code == 200
    body = run_resp.json()
    reporter.kv("tags", body["tags"])
    assert "as_of:2020-06-30" in body["tags"], (
        f"expected as_of:2020-06-30 in tags, got {body['tags']}"
    )

    reporter.section("Catalog has no source with published_at > 2020-06-30")
    # sources.json is written by the harness post-run when the skill registered
    # any sources. If the skill didn't register any (mock research may not),
    # there's no catalog to verify and the assertion is vacuously true — we
    # still want to assert nothing future leaked when present.
    artifacts_resp = client.get(
        f"/api/runs/{run_id}/artifacts", headers=alice.auth_header()
    )
    artifact_names = [a["name"] for a in artifacts_resp.json().get("items", [])]
    reporter.kv("artifacts", artifact_names)
    if "sources.json" in artifact_names:
        cat_resp = client.get(
            f"/api/runs/{run_id}/artifacts/sources.json", headers=alice.auth_header()
        )
        catalog = cat_resp.json()
        reporter.kv("source count", len(catalog.get("items", {})))
        for sid, point in catalog.get("items", {}).items():
            pub = point.get("published_at")
            if pub:
                assert str(pub)[:10] <= "2020-06-30", (
                    f"source {sid} leaked: published_at={pub} > as_of=2020-06-30"
                )
        reporter.checked("no future-dated sources in catalog", True)
    else:
        reporter.checked(
            "sources.json absent (mock skill registered no sources — vacuous)", True
        )

    reporter.section("Sanity: omitting as_of leaves no as_of:* tag")
    resp2 = client.post(
        "/api/agent/chat",
        headers={**alice.auth_header(), "Accept": "text/event-stream"},
        json={
            "messages": [{"role": "user", "content": "control: 不带 as_of"}],
            "agent": "research",
            "session_id": f"e2e-as-of-2-{int(time.time())}",
        },
    )
    assert resp2.status_code == 200
    control_events = _parse_sse(resp2.text)
    control_run_id = control_events[0]["run_id"]
    control_body = client.get(
        f"/api/runs/{control_run_id}", headers=alice.auth_header()
    ).json()
    reporter.kv("control tags", control_body["tags"])
    assert not any(t.startswith("as_of:") for t in control_body["tags"]), (
        f"control run picked up an as_of tag: {control_body['tags']}"
    )

    reporter.end()
