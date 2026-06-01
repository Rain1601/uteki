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
        "final-verdict.json",
        "company-claims.json",
        "company-source-quality.json",
        "company-run-diagnosis.json",
    }
    reporter.checked("all company artifacts written", expected.issubset(names))
    assert expected.issubset(names)

    # A.2: assert the structured final-verdict.json shape.
    verdict_resp = client.get(
        f"/api/runs/{run_id}/artifacts/final-verdict.json",
        headers=alice.auth_header(),
    )
    reporter.checked("final-verdict.json → 200", verdict_resp.status_code == 200)
    verdict = json.loads(verdict_resp.text)
    assert verdict["schema_version"] == "company_final_verdict.v1"
    assert verdict["symbol"] == "AAPL"
    assert verdict["verdict"]["action"] in {"BUY", "WATCH", "AVOID"}
    assert 0 <= verdict["verdict"]["conviction"] <= 1
    assert len(verdict["fisher_qa"]["questions"]) == 15, (
        "Gate 7 must produce all 15 Fisher questions; "
        f"got {len(verdict['fisher_qa']['questions'])}"
    )
    assert verdict["fisher_qa"]["growth_verdict"] in {
        "compounder", "cyclical", "declining", "turnaround"
    }
    radar = verdict["fisher_qa"]["radar_data"]
    for axis in ("market_potential", "innovation", "profitability",
                 "management", "competitive_edge"):
        assert axis in radar, f"radar_data missing {axis}"
    assert "buffett" in verdict["philosophy_scores"]
    assert "buffett" in verdict["master_comments"]
    reporter.event("verdict shape", f"action={verdict['verdict']['action']}, "
                                     f"fisher_q={len(verdict['fisher_qa']['questions'])}, "
                                     f"philosophy={verdict['philosophy_scores']}")

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
    assert ranking["schema_version"] == "company_research_pipeline.v1"
    assert ranking["target_symbol"] == "AAPL"
    assert len(ranking["ranked_companies"]) <= 4
    assert {"AAPL", "MSFT", "GOOGL", "META"}.issubset(ranked_symbols)

    capital_resp = client.get(
        f"/api/runs/{run_id}/artifacts/capital-plan.json",
        headers=alice.auth_header(),
    )
    reporter.checked("capital-plan.json → 200", capital_resp.status_code == 200)
    capital_plan = json.loads(capital_resp.text)
    assert capital_plan["schema_version"] == "company_research_pipeline.v1"
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
    assert review["schema_version"] == "company_research_pipeline.v1"
    stages = review["stages"]
    assert {entry["stage"] for entry in stages} >= {"evidence", "peer_comparison", "capital_plan"}
    for entry in stages:
        assert "autonomy" in entry
        assert "observability" in entry
        assert "traceability" in entry
        assert "self_iteration" in entry

    decision_resp = client.get(
        f"/api/runs/{run_id}/artifacts/decision.json",
        headers=alice.auth_header(),
    )
    reporter.checked("decision.json → 200", decision_resp.status_code == 200)
    decision = json.loads(decision_resp.text)
    assert decision["schema_version"] == "company_research_pipeline.v1"
    assert decision["symbol"] == "AAPL"
    assert decision["action"] in {"BUY", "WATCH", "AVOID"}
    assert decision["real_order_execution"] is False
    assert decision["source"] == "deterministic_policy"
    assert "policy_inputs" in decision

    claims_resp = client.get(
        f"/api/runs/{run_id}/artifacts/company-claims.json",
        headers=alice.auth_header(),
    )
    reporter.checked("company-claims.json → 200", claims_resp.status_code == 200)
    claims = json.loads(claims_resp.text)
    assert claims["schema_version"] == "company_claim_audit.v1"
    assert claims["summary"]["claim_count"] >= 6
    assert "unsupported_claim_count" in claims["summary"]

    source_quality_resp = client.get(
        f"/api/runs/{run_id}/artifacts/company-source-quality.json",
        headers=alice.auth_header(),
    )
    reporter.checked("company-source-quality.json → 200", source_quality_resp.status_code == 200)
    source_quality = json.loads(source_quality_resp.text)
    assert source_quality["schema_version"] == "company_source_quality.v1"
    assert source_quality["metrics"]["source_count"] >= 1
    assert "tier_4_count" in source_quality["metrics"]

    diagnosis_resp = client.get(
        f"/api/runs/{run_id}/artifacts/company-run-diagnosis.json",
        headers=alice.auth_header(),
    )
    reporter.checked("company-run-diagnosis.json → 200", diagnosis_resp.status_code == 200)
    diagnosis = json.loads(diagnosis_resp.text)
    assert diagnosis["schema_version"] == "company_research_pipeline.v1"
    assert diagnosis["symbol"] == "AAPL"
    assert diagnosis["status"] in {"pass", "warn", "fail"}
    check_names = {check["name"] for check in diagnosis["checks"]}
    assert check_names >= {
        "gate_coverage",
        "decision_contract",
        "structured_consistency",
        "position_boundary",
        "research_boundary",
        "schema_version",
        "source_quality",
        "claim_support",
        "number_traceability",
        "deliverable_hygiene",
    }
    assert diagnosis["metrics"]["gate_count"] == 6
    assert "decision.json" in diagnosis["canonical_outputs"]
    assert "company-claims.json" in diagnosis["canonical_outputs"]
    assert "company-source-quality.json" in diagnosis["canonical_outputs"]
    assert "claim_audit_summary" in diagnosis
    assert "source_quality" in diagnosis
    reporter.end()
