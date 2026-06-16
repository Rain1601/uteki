"""Health endpoints.

Two flavors:
- ``GET /health`` — original liveness, returns 200 with no DB roundtrip.
  Kept for backward compat (older tooling polls it).
- ``GET /healthz`` — readiness, does a ``SELECT 1`` against the DB so a
  cold-started Cloud Run revision that can't reach Cloud SQL fails fast
  with a 5xx. This is what ``scripts/smoke_test.sh`` calls after a
  ``--no-traffic`` deploy to decide whether to flip 100% traffic.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlmodel import Session

from uteki_api.core.db import get_db

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/healthz")
async def healthz(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.exec(text("SELECT 1"))
    except Exception as e:
        # Surface as 503 so Cloud Run's load balancer + the smoke step
        # both treat it as "not ready" — a 500 would look like an app
        # bug, but a DB-not-reachable is genuinely a not-ready signal.
        raise HTTPException(status_code=503, detail=f"db unreachable: {e}") from e
    return {"status": "ok", "db": "ok"}
