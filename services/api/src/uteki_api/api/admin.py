"""Admin endpoints — operational tooling that isn't part of the user flow.

``POST /api/admin/reload-skills`` clears the skill prompt cache and rebinds
``skill.system_prompt`` for every registered skill. This is the keystone of
the prompt-tuning loop (``scripts/tune-prompt.sh``): edit a SKILL.md or a
shared guardrail file, POST this endpoint, run eval — no API restart.

``POST /api/admin/review/{run_id}`` is the M1 self-evolution loop trigger —
creates a Proposal record for a Run.

``POST /api/admin/proposals/{proposal_id}/run-cc`` (M1.3) drives the
self-evolution pipeline from ``triggered`` → ``pending_review``. Snapshots
the skill + run artifacts, builds brief.md, spawns the ``claude`` CLI
(or canned mock when ``UTEKI_USE_MOCK_CC=true``), and collects critique.md
+ patch.diff. Runs in a background task — the endpoint returns immediately
with ``{status:'spawning'}`` and the caller polls the proposal.

M4+: gated behind admin role so anonymous/read-only callers can't hot-reload
prompts or trigger self-evolution. Configure admins with UTEKI_ADMIN_EMAILS or
GitHub allowlists.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from uteki_api.auth.deps import require_admin
from uteki_api.core.db import get_db
from uteki_api.evolution.cc_runner import run_cc_review
from uteki_api.evolution.proposals import default_proposal_store
from uteki_api.runs import default_run_store
from uteki_api.skills import default_skills
from uteki_api.skills.loader import load_skill_prompt
from uteki_api.users.models import User
from uteki_api.users.store import default_user_store

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
)

# Track in-flight cc_runner tasks so they aren't garbage-collected mid-run.
# Mirrors the pattern in api/agent.py's _inflight_runs.
_inflight_cc_reviews: set[asyncio.Task] = set()


@router.post("/reload-skills")
async def reload_skills(_user: User = Depends(require_admin)) -> dict:
    """Clear the loader cache and refresh each skill's `system_prompt`."""
    load_skill_prompt.cache_clear()
    cleared: list[str] = []
    skipped: list[str] = []
    for entry in default_skills.list():
        name = entry["name"]
        skill = default_skills.get(name)
        if not hasattr(skill, "system_prompt"):
            skipped.append(name)
            continue
        try:
            new_text, new_refs = load_skill_prompt(name)
        except FileNotFoundError:
            skipped.append(name)
            continue
        skill.system_prompt = new_text
        skill.refs = new_refs
        cleared.append(name)
    return {"cleared": cleared, "skipped": skipped, "count": len(cleared)}


@router.post("/review/{run_id}")
async def trigger_review(
    run_id: str,
    reason: str = "manual trigger",
    user: User = Depends(require_admin),
) -> dict:
    """Create a self-evolution Proposal for ``run_id``.

    M1.1: only writes bookkeeping (meta.json + decisions/001-triggered.json).
    The actual CC-review pipeline (snapshot → spawn → critique → validate)
    lands in M1.2-M1.4. Returns the freshly-allocated ``proposal_id`` so
    callers can poll status later via a (future) ``GET /api/admin/proposals``.

    Auth: caller must be admin and own the run. Ownership is enforced by
    ``run_store.get(run_id, user.id)`` raising KeyError on cross-user access —
    same 404 shape as "doesn't exist".
    """
    try:
        run = await default_run_store.get(run_id, user.id)
    except KeyError as e:
        raise HTTPException(404, detail=str(e)) from e

    proposal = default_proposal_store.create(
        source_run_id=run.id,
        source_skill=run.skill,
        source_user_id=run.user_id,
        triggered_by=f"user:{user.id}",
        trigger_reason=reason,
    )
    return {
        "proposal_id": proposal.proposal_id,
        "status": proposal.status,
        "source_skill": proposal.source_skill,
        "source_run_id": proposal.source_run_id,
    }


@router.post("/proposals/{proposal_id}/run-cc")
async def run_cc(
    proposal_id: str,
    _user: User = Depends(require_admin),
) -> dict:
    """Kick off the cc_runner pipeline for a triggered proposal.

    Returns immediately after validating the proposal exists and is in
    ``triggered`` state; the actual snapshot → spawn → collect flow runs
    in a background asyncio task. Callers poll
    ``GET /api/admin/proposals/{proposal_id}`` (M1.5) — or directly read
    ``meta.json`` — to observe progress through the state machine.

    Idempotency: refuses if the proposal is anything other than
    ``triggered``. A failed/invalidated proposal needs a fresh trigger
    (per the state-machine spec — ``invalidated`` is terminal).
    """
    try:
        proposal = default_proposal_store.get(proposal_id)
    except KeyError as e:
        raise HTTPException(404, detail=str(e)) from e
    if proposal.status != "triggered":
        raise HTTPException(
            409,
            detail=(
                f"proposal {proposal_id} is {proposal.status}, expected triggered"
            ),
        )

    async def _drive() -> None:
        try:
            await run_cc_review(proposal_id)
        except Exception:  # noqa: BLE001 — cc_runner logs internally
            logger.exception("background cc_runner failed for %s", proposal_id)

    task = asyncio.create_task(_drive(), name=f"cc-review-{proposal_id}")
    _inflight_cc_reviews.add(task)
    task.add_done_callback(_inflight_cc_reviews.discard)

    return {
        "proposal_id": proposal_id,
        "status": "spawning",
        "background": True,
    }


@router.get("/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: str,
    _user: User = Depends(require_admin),
) -> dict:
    """Read the current meta.json of a proposal.

    Lightweight inspection endpoint — the full G1 review UI (M1.5) will
    layer richer projections (critique excerpt, patch stats, etc) on top.
    This one is just "give me the current state machine truth".
    """
    try:
        proposal = default_proposal_store.get(proposal_id)
    except KeyError as e:
        raise HTTPException(404, detail=str(e)) from e
    return proposal.model_dump()


class UserRow(BaseModel):
    id: str
    email: str
    display_name: str
    avatar_url: str | None
    role: str
    status: str
    created_at: str
    providers: list[str]


class UsersListResponse(BaseModel):
    items: list[UserRow]
    total: int
    limit: int
    offset: int


class UpdateRoleBody(BaseModel):
    role: str = Field(..., pattern=r"^(admin|reader)$")


def _row(db: Session, user: User) -> UserRow:
    return UserRow(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        role=user.role,
        status=user.status,
        created_at=user.created_at.isoformat(),
        providers=default_user_store.providers_for(db, user.id),
    )


@router.get("/users", response_model=UsersListResponse)
async def list_users(
    limit: int = 50,
    offset: int = 0,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UsersListResponse:
    """List all real users (demo@local hidden) with their identity providers.

    Paginated. Newest first by ``created_at``. Used by the ``/admin/users``
    console page; not part of the public API contract.
    """
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    rows, total = default_user_store.list(db, limit=limit, offset=offset)
    return UsersListResponse(
        items=[_row(db, u) for u in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/users/{user_id}", response_model=UserRow)
async def update_user_role(
    user_id: str,
    body: UpdateRoleBody,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserRow:
    """Promote / demote a user. Two guards against lockout:

    1. An admin cannot demote themselves — must be done by another admin.
    2. Cannot demote the last remaining admin (system would have zero).
    """
    if user_id == actor.id and body.role != "admin":
        raise HTTPException(
            409, detail="cannot demote yourself; ask another admin"
        )

    target = default_user_store.get(db, user_id)
    if target is None:
        raise HTTPException(404, detail=f"user {user_id} not found")

    if target.role == "admin" and body.role != "admin":
        admin_count = default_user_store.count_admins(db)
        if admin_count <= 1:
            raise HTTPException(
                409,
                detail="refusing to demote the last admin",
            )

    if target.role == body.role:
        # No-op; still return current state so the UI can reconcile.
        return _row(db, target)

    updated = default_user_store.update_role(db, user_id, body.role)
    if updated is None:
        raise HTTPException(404, detail=f"user {user_id} not found")
    logger.info(
        "admin role change actor=%s target=%s %s→%s",
        actor.id, updated.id, target.role, updated.role,
    )
    return _row(db, updated)


# ── Search-strategy inspection + side-by-side compare ────────────────
#
# Admin /tools page surfaces this: list the strategies registered in the
# web_search chain (vertex_grounding → google_cse → ddgs → mock), show
# which are configured, and run the same query across multiple strategies
# in parallel so the admin can compare result quality before deciding
# which to promote / demote.
#
# Strategies are dispatched per-name via _dispatch_strategy() rather than
# the production WebSearchTool chain — compare needs to call each one
# directly even if it's not the current primary.


class SearchStrategyInfo(BaseModel):
    name: str
    label: str
    configured: bool
    in_chain: bool
    use_case: str
    cost_note: str | None
    config_note: str | None = None


class SearchCompareHit(BaseModel):
    title: str
    url: str
    snippet: str
    source: str


class SearchCompareStrategy(BaseModel):
    name: str
    ok: bool
    elapsed_ms: int
    items: list[SearchCompareHit]
    error: str | None = None


class SearchCompareRequest(BaseModel):
    query: str = Field(min_length=1)
    strategies: list[str]
    limit: int = Field(default=5, ge=1, le=10)


class SearchCompareResponse(BaseModel):
    query: str
    results: list[SearchCompareStrategy]


# Strategy catalog. ``in_chain`` reflects what web_search.py currently
# tries in order; the others ride along here for comparison only. To
# promote one into the chain, edit web_search.py — there's no runtime
# switch yet (deliberate: the chain order is a deployment decision, not
# a per-request one).
_STRATEGY_CATALOG: list[dict[str, Any]] = [
    {
        "name": "vertex_grounding",
        "label": "Vertex AI Grounding",
        "in_chain": True,
        "use_case": "Gemini 2.5 Flash + google_search 工具,通用网搜的 CSE 替代。",
        "cost_note": "~$0.04/搜索",
        "config_env": ["GOOGLE_CLOUD_PROJECT"],
    },
    {
        "name": "google_cse",
        "label": "Google Custom Search",
        "in_chain": True,
        "use_case": "Legacy。2025 起对新客户关闭,老 key 已开始返回 400。",
        "cost_note": "$5 / 1000 query(免费 100/天)",
        "config_env": ["GOOGLE_SEARCH_API_KEY", "GOOGLE_SEARCH_ENGINE_ID"],
    },
    {
        "name": "ddgs",
        "label": "DuckDuckGo (DDGS)",
        "in_chain": True,
        "use_case": "无 key fallback。质量低、不稳定,适合兜底。",
        "cost_note": "免费",
        "config_env": [],
    },
    {
        "name": "tavily",
        "label": "Tavily",
        "in_chain": False,
        "use_case": "LLM-optimized 输出,markdown extract。投研 transcript / 报告类查询表现稳。",
        "cost_note": "$0.005/搜索",
        "config_env": ["TAVILY_API_KEY"],
    },
    {
        "name": "agent_search",
        "label": "Vertex AI Search (Discovery Engine)",
        "in_chain": False,
        "use_case": "在预先 provision 的 Website Data Store 索引内搜。适合白名单收敛后。",
        "cost_note": "按 query 计费",
        "config_env": ["GOOGLE_CLOUD_PROJECT", "AGENT_SEARCH_DATA_STORE_ID"],
    },
    {
        "name": "mock",
        "label": "Mock fixture",
        "in_chain": True,
        "use_case": "所有真 backend 都失败时的兜底。e2e 测试也走这条。",
        "cost_note": "—",
        "config_env": [],
    },
]


def _strategy_configured(entry: dict[str, Any]) -> tuple[bool, str | None]:
    import os
    missing = [v for v in entry["config_env"] if not os.environ.get(v)]
    if not missing:
        return True, None
    return False, f"缺 env: {', '.join(missing)}"


@router.get("/search/strategies", response_model=list[SearchStrategyInfo])
async def list_search_strategies(
    _user: User = Depends(require_admin),
) -> list[SearchStrategyInfo]:
    out: list[SearchStrategyInfo] = []
    for entry in _STRATEGY_CATALOG:
        configured, note = _strategy_configured(entry)
        out.append(
            SearchStrategyInfo(
                name=entry["name"],
                label=entry["label"],
                configured=configured,
                in_chain=entry["in_chain"],
                use_case=entry["use_case"],
                cost_note=entry["cost_note"],
                config_note=note,
            )
        )
    return out


async def _dispatch_strategy(name: str, query: str, limit: int) -> list[dict[str, Any]]:
    """Run a single strategy by name. Raises on configuration / runtime errors —
    caller wraps in try/except so one strategy's failure doesn't kill the
    rest of the compare batch.
    """
    from uteki_api.tools.web_search import (
        _ddgs_general,
        _google_cse_general,
        _mock_results,
        _vertex_grounding_general,
    )
    if name == "vertex_grounding":
        return await _vertex_grounding_general(query, limit)
    if name == "google_cse":
        return await _google_cse_general(query, limit)
    if name == "ddgs":
        return await _ddgs_general(query, limit)
    if name == "mock":
        return _mock_results(query, limit)
    if name in {"tavily", "agent_search"}:
        # Both ride on market_utils SearchEngine. Strategy id is the same
        # as market_utils' registry name.
        from market_utils.search import SearchEngine
        engine = SearchEngine.from_env(strategy=name)
        rows = await engine.search(query, max_results=limit)
        from urllib.parse import urlparse
        items = []
        for row in rows[:limit]:
            url = row.url or ""
            source = (row.source or urlparse(url).netloc or name).lower()
            items.append({
                "title": row.title or "",
                "snippet": row.snippet or "",
                "source": source,
                "url": url,
                "provider": name,
            })
        return items
    raise ValueError(f"unknown strategy: {name}")


@router.post("/search/compare", response_model=SearchCompareResponse)
async def compare_search(
    body: SearchCompareRequest,
    _user: User = Depends(require_admin),
) -> SearchCompareResponse:
    """Run the same query across multiple strategies concurrently. Each
    strategy is captured independently — a failure on one returns an
    error string but doesn't drop the rest. Timing is per-strategy so
    the UI can show "vertex 1200ms vs ddgs 280ms" side-by-side."""
    valid_names = {entry["name"] for entry in _STRATEGY_CATALOG}
    unknown = [s for s in body.strategies if s not in valid_names]
    if unknown:
        raise HTTPException(
            400, detail=f"unknown strategies: {unknown!r}; pick from {sorted(valid_names)!r}"
        )

    loop = asyncio.get_running_loop()

    async def _run_one(name: str) -> SearchCompareStrategy:
        start = loop.time()
        try:
            items = await _dispatch_strategy(name, body.query, body.limit)
            elapsed_ms = int((loop.time() - start) * 1000)
            return SearchCompareStrategy(
                name=name,
                ok=True,
                elapsed_ms=elapsed_ms,
                items=[
                    SearchCompareHit(
                        title=i.get("title") or "",
                        url=i.get("url") or "",
                        snippet=i.get("snippet") or "",
                        source=i.get("source") or "",
                    )
                    for i in items
                ],
            )
        except Exception as exc:  # noqa: BLE001 — compare must survive partial failure
            elapsed_ms = int((loop.time() - start) * 1000)
            return SearchCompareStrategy(
                name=name,
                ok=False,
                elapsed_ms=elapsed_ms,
                items=[],
                error=f"{type(exc).__name__}: {exc}",
            )

    results = await asyncio.gather(*(_run_one(s) for s in body.strategies))
    return SearchCompareResponse(query=body.query, results=list(results))


# Re-export so test conftest can rebind it alongside default_proposal_store.
# (cc_runner reaches into module-level singletons; tests that swap the
# proposal store in must also swap this module's reference so the API
# handler and the background task see the same instance.)
__all__ = ["router", "run_cc_review"]
