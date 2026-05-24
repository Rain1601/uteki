"""T5 — Eval chain end-to-end + per-user history scoping.

POST /api/eval/run actually walks every case in eval/cases/, runs each
one through a fresh harness with mock LLM, and records an EvalRecord
per case under the caller's history partition. We check:
  - the call returns a structured report (pass_rate, results[])
  - each case produces a CaseResult
  - the resulting EvalRecord rows show up in GET /api/eval/history for
    the caller and NOWHERE else

Plus: drift_monitor.check_drift() reads the "system" partition, not the
caller's — important so user noise doesn't drown out platform-level
trend signal.
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from .conftest import AuthedUser, Reporter


def test_eval_run_and_history_per_user(
    client: TestClient, alice: AuthedUser, bob: AuthedUser, reporter: Reporter
) -> None:
    reporter.section("alice runs the full eval suite")
    r = client.post("/api/eval/run", headers=alice.auth_header())
    reporter.kv("HTTP", r.status_code)
    assert r.status_code == 200
    report = r.json()
    reporter.kv("pass_rate", report.get("pass_rate"))
    reporter.kv("case count", len(report["results"]))
    for case in report["results"]:
        reporter.event(case["case_id"], f"passed={case['passed']} latency={case['latency_ms']}ms")
    reporter.checked("at least one case ran", len(report["results"]) > 0)
    assert len(report["results"]) > 0

    reporter.section("alice's /eval/history now non-empty")
    ah = client.get("/api/eval/history", headers=alice.auth_header())
    a_records = ah.json()["items"]
    reporter.kv("alice record count", len(a_records))
    case_ids = {r["case_id"] for r in a_records}
    reporter.kv("case_ids in history", sorted(case_ids))
    reporter.checked("history covers every case the runner ran",
                     case_ids == {c["case_id"] for c in report["results"]})
    assert case_ids == {c["case_id"] for c in report["results"]}

    reporter.section("bob's /eval/history is still empty (no eval run)")
    bh = client.get("/api/eval/history", headers=bob.auth_header())
    b_records = bh.json()["items"]
    reporter.kv("bob record count", len(b_records))
    reporter.checked("bob sees zero records", len(b_records) == 0)
    assert b_records == []

    reporter.section("per-case history filtered for alice")
    a_case_id = next(iter(case_ids))
    ch = client.get(f"/api/eval/cases/{a_case_id}/history", headers=alice.auth_header())
    reporter.kv("alice's per-case rows", len(ch.json()["items"]))
    assert len(ch.json()["items"]) >= 1

    bh_case = client.get(f"/api/eval/cases/{a_case_id}/history", headers=bob.auth_header())
    reporter.checked("bob's per-case for same id is empty",
                     bh_case.json()["items"] == [])
    assert bh_case.json()["items"] == []

    reporter.end()


def test_drift_monitor_reads_system_partition(
    client: TestClient, alice: AuthedUser, reporter: Reporter
) -> None:
    """Drift monitor must read 'system' partition, not the caller's.

    Seed today + 7d-ago records in BOTH partitions with deliberately
    different pass_rates — if check_drift mistakenly read alice's, the
    computed pass_rate would be 1.0 instead of 0.5.
    """
    from uteki_api.eval.drift_monitor import check_drift
    from uteki_api.eval.store import default_eval_history, EvalRecord
    import time

    now = time.time()
    week_ago = now - 7 * 86_400
    reporter.section("seed both partitions with today + 7d-ago records")
    reporter.kv("now", int(now))
    reporter.kv("week_ago", int(week_ago))

    async def seed() -> None:
        # Alice's records — high pass_rate so it'd be obvious if drift
        # accidentally read them.
        for _ in range(5):
            await default_eval_history.append(
                alice.id, EvalRecord(case_id="case_a", started_at=now, pass_rate=1.0, notes="alice-today")
            )
            await default_eval_history.append(
                alice.id, EvalRecord(case_id="case_a", started_at=week_ago, pass_rate=1.0, notes="alice-old")
            )
        # System records — these are what drift should actually read.
        for _ in range(5):
            await default_eval_history.append(
                "system", EvalRecord(case_id="case_s", started_at=now, pass_rate=0.4, notes="system-today")
            )
            await default_eval_history.append(
                "system", EvalRecord(case_id="case_s", started_at=week_ago, pass_rate=0.8, notes="system-old")
            )

    asyncio.run(seed())

    reporter.section("call drift_monitor.check_drift()")
    result = asyncio.run(check_drift())
    reporter.kv("today_count", result["today_count"])
    reporter.kv("week_ago_count", result["week_ago_count"])
    reporter.kv("today_pass_rate", result["today_pass_rate"])
    reporter.kv("week_ago_pass_rate", result["week_ago_pass_rate"])
    reporter.kv("drop", result["drop"])
    reporter.kv("alert", result["alert"])

    reporter.checked("today_count == 5 (system only, not 10)", result["today_count"] == 5)
    reporter.checked("week_ago_count == 5", result["week_ago_count"] == 5)
    reporter.checked(
        "today_pass_rate ≈ 0.4 (system, not alice's 1.0)",
        result["today_pass_rate"] is not None
        and abs(result["today_pass_rate"] - 0.4) < 0.01,
        f"got {result['today_pass_rate']}",
    )
    reporter.checked(
        "alert fires (0.8 → 0.4 is a 40pp drop > 10pp threshold)",
        result["alert"] is True,
    )
    assert result["today_count"] == 5
    assert abs(result["today_pass_rate"] - 0.4) < 0.01
    assert result["alert"] is True

    reporter.end()
