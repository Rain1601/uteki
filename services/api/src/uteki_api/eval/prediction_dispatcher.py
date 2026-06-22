"""015 PR ε MVP · Post-run prediction dispatcher.

Fires after ``RunStore.finish()`` for skill = ``company_research_pipeline``.
Reads the run's ``final-verdict.json``, snapshots the current market price
of the target ticker via ``market_quote``, and writes a Prediction row.

Failure-mode policy (matches JudgeDispatcher · 013 PR β):
- never raise back to the harness
- if final-verdict.json is missing or malformed → log + skip
- if market_quote fails → still write the prediction with ``t0_price=None``
  so the row exists; UI renders "entry price unavailable"

Idempotent: re-firing on the same run upserts in place rather than appending.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from sqlmodel import Session

from uteki_api.artifacts import default_artifact_store
from uteki_api.core.db import engine
from uteki_api.eval.market_price import spot_price
from uteki_api.eval.prediction_store import default_prediction_store
from uteki_api.runs import default_run_store

logger = logging.getLogger(__name__)

# Only these skills produce predictions. Other skills (research / earnings /
# etc.) don't carry an actionable BUY/WATCH/AVOID verdict.
PREDICTION_TARGETS: tuple[str, ...] = ("company_research_pipeline",)


class PredictionDispatcher:
    """Spawn-and-forget prediction recorder. One per process."""

    async def record(self, run_id: str) -> None:
        """Read final-verdict.json + snapshot t0_price, write Prediction row.

        Called from harness AFTER RunStore.finish() resolves. Wrapped in
        broad try/except in the harness caller; this method's own errors
        log but never re-raise."""
        try:
            await self._record_inner(run_id)
        except Exception:  # noqa: BLE001
            logger.exception(
                "prediction_dispatcher.record failed for run_id=%s", run_id
            )

    async def _record_inner(self, run_id: str) -> None:
        try:
            run = await default_run_store.get(run_id)
        except KeyError:
            logger.debug("prediction_dispatcher.skip: unknown run_id=%s", run_id)
            return
        if run is None:
            return
        if run.skill not in PREDICTION_TARGETS:
            return  # not a target skill; skip silently
        if run.status != "ok":
            logger.debug(
                "prediction_dispatcher.skip: run_id=%s status=%s (not ok)",
                run_id, run.status,
            )
            return

        # Read final-verdict.json off the artifact store
        try:
            _meta, body = await default_artifact_store.read(
                run_id, "final-verdict.json", user_id=run.user_id
            )
        except FileNotFoundError:
            logger.info(
                "prediction_dispatcher.skip: run_id=%s missing final-verdict.json",
                run_id,
            )
            return

        try:
            verdict = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(
                "prediction_dispatcher.skip: run_id=%s bad final-verdict.json: %s",
                run_id, e,
            )
            return

        ticker = str(verdict.get("symbol") or "").upper().strip()
        verdict_block = verdict.get("verdict") or {}
        action = str(verdict_block.get("action") or "").upper().strip()
        if not ticker or action not in {"BUY", "WATCH", "AVOID"}:
            logger.info(
                "prediction_dispatcher.skip: run_id=%s ticker=%r action=%r",
                run_id, ticker, action,
            )
            return

        conviction = self._coerce_float(verdict_block.get("conviction"), default=0.0)
        quality = verdict_block.get("quality_verdict")
        if isinstance(quality, str):
            quality = quality.strip() or None
        else:
            quality = None

        # Snapshot t0_price — best-effort, never blocks the write
        t0 = time.time()
        t0_price = await self._snapshot_price(ticker)

        with Session(engine) as db:
            default_prediction_store.upsert(
                db,
                run_id=run_id,
                user_id=run.user_id,
                skill_name=run.skill,
                skill_version=getattr(run, "skill_version", None),
                ticker=ticker,
                action=action,
                conviction=conviction,
                quality_verdict=quality,
                t0=t0,
                t0_price=t0_price,
            )
        logger.info(
            "prediction_dispatcher.recorded run_id=%s ticker=%s action=%s "
            "conv=%.2f t0_price=%s",
            run_id, ticker, action, conviction,
            f"${t0_price:.2f}" if t0_price else "<none>",
        )

    async def _snapshot_price(self, ticker: str) -> float | None:
        """Snapshot the closing price via the dedicated ``spot_price`` helper.

        We deliberately bypass the ``market_quote`` tool here — that tool
        uses yfinance ``info`` / ``fast_info`` for skill analysis fields,
        and those endpoints occasionally return stale or cross-ticker
        prices (observed in PR ε MVP: GOOGL phantom $122.72). The
        backtest layer needs ONLY the close price, and ``history()``
        gives us that reliably.
        """
        return await spot_price(ticker)

    @staticmethod
    def _coerce_float(v: Any, *, default: float) -> float:
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default


default_prediction_dispatcher = PredictionDispatcher()
