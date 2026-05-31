"""Company research pipeline smoke tests."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from .conftest import AuthedUser, Reporter
from .test_03_research_chain import _parse_sse


def test_company_research_pipeline_artifacts(
    client: TestClient, alice: AuthedUser, reporter: Reporter
) -> None:
    reporter.section("company_research_pipeline · artifact contract")
    resp = client.post(
        "/api/agent/chat",
        headers={**alice.auth_header(), "Accept": "text/event-stream"},
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "分析 AAPL，并对比 MSFT, GOOGL, META，给出排序和仓位建议。",
                }
            ],
            "agent": "company_research_pipeline",
            "session_id": "e2e-company",
        },
    )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    run_id = events[0]["run_id"]
    names = {
        e["data"].get("name")
        for e in events
        if e["type"] == "artifact_written"
    }
    reporter.kv("run_id", run_id)
    reporter.kv("artifact events", sorted(names))

    expected = {
        "gate-01-business_analysis.md",
        "gate-02-fisher_qa.md",
        "gate-03-moat_assessment.md",
        "gate-04-management_assessment.md",
        "gate-05-reverse_test.md",
        "gate-06-valuation.md",
        "peer-comparison.json",
        "ranking.json",
        "capital-plan.json",
        "agent-capability-review.json",
        "final-report.md",
        "decision.json",
    }
    reporter.checked("all company artifacts written", expected.issubset(names))
    assert expected.issubset(names)

    run = client.get(f"/api/runs/{run_id}", headers=alice.auth_header()).json()
    reporter.kv("primary_artifact", run.get("primary_artifact"))
    assert run["status"] == "ok"
    assert run["primary_artifact"]["name"] == "final-report.md"
    assert run["primary_artifact"]["role"] == "primary"
    assert run["artifact_count"] >= len(expected)

    artifact_names = {a["name"] for a in run["artifacts"]}
    assert expected.issubset(artifact_names)

    ranking_resp = client.get(
        f"/api/runs/{run_id}/artifacts/ranking.json",
        headers=alice.auth_header(),
    )
    reporter.checked("ranking.json → 200", ranking_resp.status_code == 200)
    ranking = json.loads(ranking_resp.text)
    ranked_symbols = {row["symbol"] for row in ranking["ranked_companies"]}
    reporter.kv("ranked symbols", sorted(ranked_symbols))
    assert ranking["target_symbol"] == "AAPL"
    assert len(ranking["ranked_companies"]) <= 4
    assert {"AAPL", "MSFT", "GOOGL", "META"}.issubset(ranked_symbols)

    capital_resp = client.get(
        f"/api/runs/{run_id}/artifacts/capital-plan.json",
        headers=alice.auth_header(),
    )
    reporter.checked("capital-plan.json → 200", capital_resp.status_code == 200)
    capital_plan = json.loads(capital_resp.text)
    assert capital_plan["real_order_execution"] is False
    assert capital_plan["max_position_pct"] <= 10
    assert "risk_budget" in capital_plan
    assert capital_plan["add_triggers"]
    assert capital_plan["trim_triggers"]
    assert capital_plan["sell_triggers"]

    review_resp = client.get(
        f"/api/runs/{run_id}/artifacts/agent-capability-review.json",
        headers=alice.auth_header(),
    )
    reporter.checked("agent-capability-review.json → 200", review_resp.status_code == 200)
    review = json.loads(review_resp.text)
    stages = review["stages"]
    assert {entry["stage"] for entry in stages} >= {"evidence", "peer_comparison", "capital_plan"}
    for entry in stages:
        assert "autonomy" in entry
        assert "observability" in entry
        assert "traceability" in entry
        assert "self_iteration" in entry
    reporter.end()
