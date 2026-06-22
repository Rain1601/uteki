"""Run inspection endpoints — user-scoped (M4).

GET    /api/runs                       list — current user's runs
                                        ``?flagged=1`` → only runs I've 🚩-flagged (013)
GET    /api/runs/{run_id}              full Run including events (404 if not yours)
GET    /api/runs/{run_id}/events       events only (404 if not yours)
DELETE /api/runs/{run_id}              drop the row + its artifact dir (owner only)
GET    /api/runs/{run_id}/feedback     my rating + (auto_score only after I've labelled)
POST   /api/runs/{run_id}/feedback     upsert my rating + reveals auto_score
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from uteki_api.artifacts import Artifact, default_artifact_store
from uteki_api.auth.deps import current_user, require_perm
from uteki_api.auth.roles import PERM_ANNOTATE_RUNS, can_annotate_runs
from uteki_api.core.db import get_db
from uteki_api.runs import default_run_store
from uteki_api.runs.feedback_store import default_run_feedback_store
from uteki_api.runs.models import Run
from uteki_api.users.models import User

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _artifact_ref(artifact: Artifact) -> dict:
    return {
        "name": artifact.name,
        "kind": artifact.kind,
        "size_bytes": artifact.size_bytes,
        "written_by": artifact.written_by,
        "description": artifact.description,
        "url": f"/api/runs/{artifact.run_id}/artifacts/{artifact.name}",
        "role": artifact.role,
        "display_name": artifact.display_name,
        "source_refs": artifact.source_refs,
    }


def _primary_artifact(artifacts: list[Artifact]) -> Artifact | None:
    for artifact in artifacts:
        if artifact.role == "primary":
            return artifact
    for name in ("final-report.md", "investment-memo.md", "final-research.md", "research.md"):
        for artifact in artifacts:
            if artifact.name == name:
                return artifact
    return artifacts[0] if artifacts else None


def _events_summary(run: Run) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in run.events:
        counts[event.type] = counts.get(event.type, 0) + 1
    return counts


async def _artifact_index(run: Run) -> list[Artifact]:
    try:
        return await default_artifact_store.list(run.id, run.user_id)
    except Exception:
        return []


async def _summary(run: Run) -> dict:
    artifacts = await _artifact_index(run)
    primary = _primary_artifact(artifacts)
    return {
        "id": run.id,
        "skill": run.skill,
        "skill_version": run.skill_version,
        "triggered_by": run.triggered_by,
        "trigger_reason": run.trigger_reason,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "status": run.status,
        "summary": run.summary,
        "user_input": run.user_input,
        "tags": run.tags,
        "artifact_count": len(artifacts),
        "primary_artifact": _artifact_ref(primary) if primary is not None else None,
    }


@router.get("")
async def list_runs(
    skill: str | None = None,
    triggered_by: str | None = None,
    flagged: int = 0,
    limit: int = 50,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """List the calling user's runs.

    013: ``?flagged=1`` AND-filters to runs the caller has 🚩-flagged for
    re-review (which is just RunFeedback rows where ``flagged=True`` and
    ``user_id == caller``). Anyone without ``runs:annotate`` calling this
    will simply see an empty list — they can't have flagged anything to
    begin with, so no separate 403 is required.
    """
    runs = await default_run_store.list(
        user_id=user.id, skill=skill, triggered_by=triggered_by, limit=limit
    )
    if flagged:
        flagged_ids = set(
            default_run_feedback_store.list_flagged_run_ids(db, user_id=user.id)
        )
        runs = [r for r in runs if r.id in flagged_ids]
    return {"items": [await _summary(r) for r in runs]}


@router.get("/{run_id}")
async def get_run(
    run_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        run = await default_run_store.get(run_id, user.id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    payload = run.model_dump()
    artifacts = await _artifact_index(run)
    primary = _primary_artifact(artifacts)
    payload["artifacts"] = [_artifact_ref(a) for a in artifacts]
    payload["primary_artifact"] = _artifact_ref(primary) if primary is not None else None
    payload["artifact_count"] = len(artifacts)
    payload["events_summary"] = _events_summary(run)
    # 013 — reveal-after-label semantics. Default is conservative: hide
    # the score until the annotator has submitted feedback ("blind"
    # mode). Only when the existing feedback row is itself in "review"
    # mode does the score become visible regardless of label — and the
    # annotator's role in that case is to accept/reject the judge, not
    # to produce calibration-grade data.
    #
    # Phase 1 wires the mode entirely through the feedback row's own
    # ``rating_mode`` field; a query param could be added later for the
    # UI to pre-toggle before the first POST. The masked default keeps
    # casual readers (incl. would-be annotators on a fresh run) from
    # being anchored by the judge.
    payload["auto_score"] = None
    payload["score_breakdown"] = None
    if can_annotate_runs(user):
        existing = default_run_feedback_store.get(
            db, user_id=user.id, run_id=run_id
        )
        if existing is not None and existing.rating_mode == "review":
            payload["auto_score"] = run.auto_score
            payload["score_breakdown"] = run.score_breakdown
        elif existing is not None:
            # "blind" row that's been labelled already — score is revealed.
            payload["auto_score"] = run.auto_score
            payload["score_breakdown"] = run.score_breakdown
    return payload


@router.get("/{run_id}/events")
async def get_run_events(run_id: str, user: User = Depends(current_user)) -> dict:
    try:
        run = await default_run_store.get(run_id, user.id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"items": [e.model_dump() for e in run.events]}


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(run_id: str, user: User = Depends(current_user)) -> None:
    """Owner-scoped delete: drops the Run row, evicts in-flight cache, wipes the
    artifact directory. Cross-user attempts return 404 (same shape as
    "doesn't exist" — deliberately avoids leaking existence)."""
    # Resolve user partition before purging artifacts. ``get`` raises KeyError
    # for both unknown ids and cross-user reads, which we map to 404.
    try:
        run = await default_run_store.get(run_id, user.id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    # Artifacts first — if the run row goes away but artifacts remain, the
    # files become unreferenceable. Failure here is logged but doesn't block
    # the row delete; better to have orphan files than an orphan row that
    # blocks the UI.
    try:
        await default_artifact_store.delete_run(run_id, run.user_id)
    except Exception:  # noqa: BLE001 — best-effort cleanup
        pass

    await default_run_store.delete(run_id, user.id)


# ─── 013 · Feedback endpoints ────────────────────────────────────────


class FeedbackBody(BaseModel):
    rating: Literal["up", "down"]
    notes: str = Field(default="", max_length=4096)
    flagged: bool = False
    # 013 δ.1 — which annotation mode this submission used. ``blind``
    # = the annotator did NOT see the auto-score before labelling
    # (calibration-grade). ``review`` = the annotator saw the score
    # and was reacting to it (review/accept/reject workflow).
    rating_mode: Literal["blind", "review"] = "blind"


class FeedbackOut(BaseModel):
    run_id: str
    rating: str
    notes: str
    flagged: bool
    rating_mode: str = "blind"
    created_at: str
    updated_at: str
    # 013 — populated when the caller is allowed to see the score under
    # current masking rules. See ``_build_feedback_out`` for the matrix.
    auto_score: float | None = None
    score_breakdown: dict | None = None


async def _build_feedback_out(
    db: Session,
    run: Run,
    feedback,
    *,
    # The "intent" mode tells GET which masking rule to apply on a row
    # that doesn't exist yet. Without it, a GET on a brand-new run can't
    # know whether the annotator is about to label blind or review, so
    # the safer default is "blind" (hide). The frontend passes
    # ``?mode=review`` when the annotator toggles into review-mode
    # BEFORE submitting their first label so the score appears.
    intent_mode: str | None = None,
) -> FeedbackOut:
    if feedback is not None:
        # Submitted rows: reveal regardless of mode — the annotator has
        # already provided their label, anchoring is moot.
        return FeedbackOut(
            run_id=run.id,
            rating=feedback.rating,
            notes=feedback.notes,
            flagged=feedback.flagged,
            rating_mode=feedback.rating_mode,
            created_at=feedback.created_at.isoformat(),
            updated_at=feedback.updated_at.isoformat(),
            auto_score=run.auto_score,
            score_breakdown=run.score_breakdown,
        )
    # No submitted row yet. Mask blind; reveal review (intent declared).
    reveal = intent_mode == "review"
    return FeedbackOut(
        run_id=run.id,
        rating="",
        notes="",
        flagged=False,
        rating_mode=intent_mode or "blind",
        created_at="",
        updated_at="",
        auto_score=run.auto_score if reveal else None,
        score_breakdown=run.score_breakdown if reveal else None,
    )


@router.get("/{run_id}/feedback", response_model=FeedbackOut)
async def get_feedback(
    run_id: str,
    mode: Literal["blind", "review"] = "blind",
    user: User = Depends(require_perm(PERM_ANNOTATE_RUNS)),
    db: Session = Depends(get_db),
) -> FeedbackOut:
    """My rating on this run.

    Returns a row of empty fields if I haven't labelled yet. The
    ``?mode=`` query param declares which annotation mode the caller is
    about to use; ``review`` reveals the auto-score immediately (review
    workflow), ``blind`` keeps it hidden until POST (calibration-grade).
    """
    try:
        run = await default_run_store.get(run_id, user.id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    feedback = default_run_feedback_store.get(db, user_id=user.id, run_id=run_id)
    return await _build_feedback_out(db, run, feedback, intent_mode=mode)


@router.post("/{run_id}/feedback", response_model=FeedbackOut)
async def upsert_feedback(
    run_id: str,
    body: FeedbackBody,
    user: User = Depends(require_perm(PERM_ANNOTATE_RUNS)),
    db: Session = Depends(get_db),
) -> FeedbackOut:
    """Upsert my rating on this run. Reveals the auto-score on the response
    body so the caller can immediately compare their label to the judge's."""
    try:
        run = await default_run_store.get(run_id, user.id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    feedback = default_run_feedback_store.upsert(
        db,
        user_id=user.id,
        run_id=run_id,
        rating=body.rating,
        notes=body.notes,
        flagged=body.flagged,
        rating_mode=body.rating_mode,
    )
    return await _build_feedback_out(db, run, feedback)


# ── 015 PR ε MVP · Backtest widget data ────────────────────────────────
#
# Returns the prediction row for this run + a live current-price snapshot
# + SPY comparison. The widget on /runs/[id] right pane binds to this.
#
# This endpoint deliberately combines "frozen at t0" data (from the
# Prediction row) with "live right now" data (from market_quote) — UI
# gets exactly what it needs in one shot without juggling two stores.


import time as _time  # local alias to avoid colliding with Run.started_at-shaped fields  # noqa: E402

from uteki_api.eval.market_price import spot_price  # noqa: E402
from uteki_api.eval.prediction_store import default_prediction_store  # noqa: E402


class PredictionOut(BaseModel):
    run_id: str
    ticker: str
    action: str
    conviction: float
    quality_verdict: str | None
    t0: float
    t0_price: float | None
    t0_currency: str

    # Live snapshot — fetched on demand, may be None if market_quote fails.
    now_price: float | None
    spy_now_price: float | None
    spy_t0_price: float | None  # not stored MVP-wise; None for now

    # Computed deltas — None when any input is missing.
    stock_pct: float | None  # (now - t0) / t0
    spy_pct: float | None
    relative_pct: float | None  # stock_pct - spy_pct

    # Horizon countdowns — pure time arithmetic from t0.
    horizons: list[dict]
    # [{"horizon_days": 30, "due_at": <epoch>, "days_remaining": 29,
    #   "outcome": null (MVP)}, ...]


async def _live_price(ticker: str) -> float | None:
    """Best-effort live close price via yfinance ``history()``.

    See ``eval/market_price.py`` for why we bypass the market_quote tool
    here. None on any failure — UI handles gracefully.
    """
    return await spot_price(ticker)


@router.get("/{run_id}/prediction", response_model=PredictionOut)
async def get_prediction(
    run_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> PredictionOut:
    """Return the backtest data for this run.

    Combines the frozen Prediction row (action / t0_price / conviction)
    with live current prices for the ticker + SPY benchmark.
    Cross-user reads return 404 via the same shape as 'no such run' —
    deliberately not leaking existence.
    """
    try:
        run = await default_run_store.get(run_id, user.id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    prediction = default_prediction_store.get(db, run_id)
    if prediction is None:
        raise HTTPException(
            status_code=404,
            detail=f"no prediction for run {run_id!r} (skill not predictive or "
            "verdict was missing/malformed at finish time)",
        )

    # Ownership sanity — the run lookup above already enforces this, but
    # belt-and-braces (the Prediction table is not user-partitioned).
    if prediction.user_id != run.user_id:
        raise HTTPException(status_code=404, detail=str(run_id))

    # Live snapshots (fire two requests in parallel — both already best-effort)
    import asyncio as _asyncio  # noqa: PLC0415

    now_price, spy_now = await _asyncio.gather(
        _live_price(prediction.ticker),
        _live_price("SPY"),
    )

    # Deltas — only computed when t0 + now snapshots are both available.
    stock_pct: float | None = None
    if prediction.t0_price and now_price:
        stock_pct = (now_price - prediction.t0_price) / prediction.t0_price * 100.0

    # SPY t0 isn't snapshotted in MVP (we'd need to call market_quote for SPY
    # at finish time too — easy add but I'm scoping to "stock price first"
    # in this slice). For now report SPY only as live; relative_pct stays None.
    spy_pct: float | None = None
    relative_pct: float | None = None

    # Horizon countdowns from t0
    now_ts = _time.time()
    horizons: list[dict] = []
    for h in prediction.horizons_to_score:
        due_at = prediction.t0 + h * 86400
        days_remaining = max(0.0, (due_at - now_ts) / 86400.0)
        outcome = prediction.outcomes.get(f"{h}d") if prediction.outcomes else None
        horizons.append({
            "horizon_days": h,
            "due_at": due_at,
            "days_remaining": days_remaining,
            "outcome": outcome,  # None until cron lands (PR ε.2)
        })

    return PredictionOut(
        run_id=run_id,
        ticker=prediction.ticker,
        action=prediction.action,
        conviction=prediction.conviction,
        quality_verdict=prediction.quality_verdict,
        t0=prediction.t0,
        t0_price=prediction.t0_price,
        t0_currency=prediction.t0_currency,
        now_price=now_price,
        spy_now_price=spy_now,
        spy_t0_price=None,
        stock_pct=stock_pct,
        spy_pct=spy_pct,
        relative_pct=relative_pct,
        horizons=horizons,
    )
