"""T22 — Async run-judge dispatcher (013 PR β).

Walks the post-run scoring path end-to-end (with the runner stubbed so we
don't hit a real LLM):

  a) Default settings (run_eval_enabled=False) → dispatcher short-
     circuits, run keeps NULL auto_score.
  b) Flag flipped on + use_mock_llm=True → still short-circuits (mock-
     LLM runs are placebos, nothing meaningful to judge).
  c) Flag on + mock_llm=False + skill not in JUDGE_TARGETS → short-
     circuits on the skill filter.
  d) Flag on + mock_llm=False + skill in targets + triggered_by="test"
     → short-circuits (eval/test runs shouldn't feed back).
  e) Flag on + mock_llm=False + ``research`` + triggered_by="user" +
     stubbed judge returning score=8 → run.auto_score becomes 8.0,
     score_breakdown carries ``{"outcome": 8.0}``.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

import uteki_api.eval.judges.dispatcher as dispatcher_mod
import uteki_api.runs as runs_pkg
from uteki_api.core.config import settings
from uteki_api.eval.judges.runner import JudgeScore
from uteki_api.runs.models import Run

from .conftest import AuthedUser, Reporter


class _StubJudgeRunner:
    """Drop-in for JudgeRunner that always returns the same score.

    The real runner does its own neutral-5 fallback when the LLM is
    unconfigured, which means a vanilla test run would always score 5 and
    we couldn't tell short-circuit-skip from actual-judged. The stub
    returns 8 so an asserted score=8 unambiguously means "the dispatcher
    ran the outcome judge".
    """

    def __init__(self, score: int = 8) -> None:
        self.score = score
        self.calls: list[dict[str, Any]] = []

    async def judge(
        self,
        rubric_name: str,
        draft_text: str,
        run_events: list[dict[str, Any]],
        *,
        avoid_model: str | None = None,
    ) -> JudgeScore:
        self.calls.append(
            {
                "rubric": rubric_name,
                "draft_len": len(draft_text),
                "events": len(run_events),
            }
        )
        return JudgeScore(
            rubric=rubric_name,
            score_1_to_10=self.score,
            pass_threshold=7,
            rationale="stub",
            specific_issues=[],
            judge_model="<stub>",
        )


async def _seed_run(
    *,
    run_id: str,
    user_id: str,
    skill: str,
    triggered_by: str,
) -> None:
    """Insert a finished-shape Run directly via the store, so we can
    exercise the dispatcher without driving a real harness."""
    await runs_pkg.default_run_store.create(
        Run(
            id=run_id,
            user_id=user_id,
            skill=skill,
            triggered_by=triggered_by,  # type: ignore[arg-type]
            started_at=time.time(),
            user_input="analyze AAPL",
            summary="my final take",
        )
    )


@pytest.mark.asyncio
async def test_run_judge_dispatcher_chain(
    client: TestClient,
    alice: AuthedUser,
    reporter: Reporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Each scenario seeds a unique run and calls the dispatcher directly.
    # The harness's actual asyncio.create_task hook is exercised separately
    # by the existing T03/T04 chains; here we only validate the
    # dispatcher's eligibility decisions and the write-back path.

    stub = _StubJudgeRunner(score=8)
    dispatcher = dispatcher_mod.JudgeDispatcher(
        run_store=runs_pkg.default_run_store,
        runner=stub,  # type: ignore[arg-type]
    )

    # ── (a) default flag off ────────────────────────────────────────
    reporter.section("a) run_eval_enabled=False → skip; auto_score stays None")
    await _seed_run(run_id="t22-a", user_id=alice.id, skill="research", triggered_by="user")
    assert settings.run_eval_enabled is False
    await dispatcher.score("t22-a")
    run_a = await runs_pkg.default_run_store.get("t22-a")
    reporter.kv("auto_score", run_a.auto_score)
    reporter.checked("None", run_a.auto_score is None)
    assert run_a.auto_score is None

    # ── (b) flag on but mock-LLM ────────────────────────────────────
    monkeypatch.setattr(settings, "run_eval_enabled", True)
    reporter.section("b) flag on + use_mock_llm=True → skip")
    await _seed_run(run_id="t22-b", user_id=alice.id, skill="research", triggered_by="user")
    assert settings.use_mock_llm is True  # e2e default
    await dispatcher.score("t22-b")
    run_b = await runs_pkg.default_run_store.get("t22-b")
    reporter.kv("auto_score", run_b.auto_score)
    reporter.checked("None (mock-LLM short-circuit)", run_b.auto_score is None)
    assert run_b.auto_score is None
    assert stub.calls == []

    # ── (c) flag on + non-mock + wrong skill ────────────────────────
    monkeypatch.setattr(settings, "use_mock_llm", False)
    reporter.section("c) skill 'planner' not in targets → skip")
    await _seed_run(run_id="t22-c", user_id=alice.id, skill="planner", triggered_by="user")
    await dispatcher.score("t22-c")
    run_c = await runs_pkg.default_run_store.get("t22-c")
    reporter.kv("auto_score", run_c.auto_score)
    reporter.checked("None (skill filter)", run_c.auto_score is None)
    assert run_c.auto_score is None
    assert stub.calls == []

    # ── (d) triggered_by="test" → skip ──────────────────────────────
    reporter.section("d) triggered_by='test' → skip")
    await _seed_run(run_id="t22-d", user_id=alice.id, skill="research", triggered_by="test")
    await dispatcher.score("t22-d")
    run_d = await runs_pkg.default_run_store.get("t22-d")
    reporter.kv("auto_score", run_d.auto_score)
    reporter.checked("None (test triggered_by)", run_d.auto_score is None)
    assert run_d.auto_score is None
    assert stub.calls == []

    # ── (e) all eligible → judge writes ─────────────────────────────
    reporter.section("e) research + user + flag on + non-mock + stub returns 8 → score=8.0")
    await _seed_run(run_id="t22-e", user_id=alice.id, skill="research", triggered_by="user")
    await dispatcher.score("t22-e")
    run_e = await runs_pkg.default_run_store.get("t22-e")
    reporter.kv("auto_score", run_e.auto_score)
    reporter.kv("score_breakdown", run_e.score_breakdown)
    reporter.kv("stub.calls", len(stub.calls))
    reporter.checked("auto_score=8.0", run_e.auto_score == 8.0)
    reporter.checked(
        "score_breakdown={'outcome': 8.0}",
        run_e.score_breakdown == {"outcome": 8.0},
    )
    reporter.checked("stub called once", len(stub.calls) == 1)
    reporter.checked("rubric=outcome", stub.calls[0]["rubric"] == "outcome")
    assert run_e.auto_score == 8.0
    assert run_e.score_breakdown == {"outcome": 8.0}
    assert len(stub.calls) == 1

    reporter.end()
