"""Eval endpoints — cases, run, and history (M4: user-scoped).

Cases themselves are platform-level (loaded from ``eval/cases/*.json``), but
every *run* and the resulting *history record* lives under the calling user.
Two users running the same suite see independent trend lines.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from uteki_api.auth.deps import current_user
from uteki_api.eval import EvalRunner
from uteki_api.eval.store import default_eval_history
from uteki_api.users.models import User

router = APIRouter(prefix="/api/eval", tags=["eval"])


@router.get("/cases")
async def list_cases() -> dict:
    cases = EvalRunner.load_cases()
    return {"items": [c.model_dump() for c in cases]}


@router.post("/run")
async def run_eval(user: User = Depends(current_user)) -> dict:
    runner = EvalRunner(user_id=user.id)
    report = await runner.run_all()
    return report.model_dump() | {"pass_rate": report.pass_rate}


@router.get("/cases/{case_id}/history")
async def get_case_history(
    case_id: str,
    limit: int = 50,
    user: User = Depends(current_user),
) -> dict:
    """Recent EvalRecords for one case, newest-first — caller-scoped."""
    items = await default_eval_history.list_case(user.id, case_id, limit=limit)
    return {"items": [r.model_dump() for r in items]}


@router.get("/history")
async def get_recent_history(
    limit: int = 100,
    user: User = Depends(current_user),
) -> dict:
    """Recent EvalRecords across all cases, newest-first — caller-scoped."""
    items = await default_eval_history.list_recent(user.id, limit=limit)
    return {"items": [r.model_dump() for r in items]}
