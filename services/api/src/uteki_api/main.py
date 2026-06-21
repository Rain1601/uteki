"""FastAPI entrypoint.

Wires all routers, configures CORS, and runs a startup hook that snapshots
each registered skill's signature into the evolution store (auto-bumping to
the next `vN` when the signature changes).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from uteki_api import __version__
from uteki_api.api import (
    admin,
    agent,
    companies,
    compare,
    earnings,
    health,
    news,
    symbols,
    tag_groups,
    triggers,
)
from uteki_api.api import agents as agents_api
from uteki_api.api import artifacts as artifacts_api
from uteki_api.api import auth as auth_api
from uteki_api.api import eval as eval_api
from uteki_api.api import runs as runs_api
from uteki_api.core.config import settings
from uteki_api.core.db import init_db
from uteki_api.core.logging import setup_logging
from uteki_api.evolution import SkillVersion, compute_changelog, default_evolution_store
from uteki_api.skills import default_skills
from uteki_api.users import ensure_demo_user

setup_logging()


def _next_version_id(prev_version: str | None) -> str:
    if not prev_version or not prev_version.startswith("v"):
        return "v1"
    try:
        n = int(prev_version[1:])
        return f"v{n + 1}"
    except ValueError:
        return "v1"


async def _seed_evolution_versions() -> None:
    """Snapshot each skill's current signature into the evolution store.

    If the latest stored version matches the current signature, do nothing.
    Otherwise record a new `vN` with a human-readable changelog.
    """
    for entry in default_skills.list():
        name = entry["name"]
        skill = default_skills.get(name)
        sig = skill.current_signature() or {
            "prompt": "",
            "tool_names": entry.get("default_tools", []),
            "model": entry.get("default_model", ""),
            "params": {},
        }

        prev = await default_evolution_store.latest(name)
        if prev is not None:
            same = (
                prev.prompt == sig.get("prompt", "")
                and list(prev.tool_names) == list(sig.get("tool_names", []) or [])
                and prev.model == sig.get("model", "")
                and prev.params == (sig.get("params", {}) or {})
            )
            if same:
                continue

        new_version_id = _next_version_id(prev.version if prev else None)
        changelog = compute_changelog(prev, sig)
        version = SkillVersion(
            skill=name,
            version=new_version_id,
            prompt=sig.get("prompt", "") or "",
            tool_names=list(sig.get("tool_names", []) or []),
            model=sig.get("model", "") or "",
            params=dict(sig.get("params", {}) or {}),
            created_at=time.time(),
            parent_version=prev.version if prev else None,
            changelog=changelog,
        )
        await default_evolution_store.record(version)


async def _seed_default_bench_suite() -> None:
    """015 PR α — idempotently materialize the ``mega-cap baseline`` suite.

    10 US mega-cap tickers (R1 decision in design.md), one canonical
    long-term-value question each. Skipped silently if any suite with the
    same name already exists. Re-runs are no-ops.

    Each query has the same ``peers`` mapping the eval-bench will hand
    to ``company_research_pipeline`` so the peer-comparison gate has
    something to compare against.
    """
    from sqlmodel import Session

    from uteki_api.core.db import engine
    from uteki_api.eval.bench_store import default_suite_store
    from uteki_api.users import ensure_demo_user

    SEED_NAME = "mega-cap baseline"
    # Question template — DRY'd: 10 rows used to repeat the same shape.
    # Change wording in one place; add/remove tickers without touching question text.
    SEED_QUESTION_TEMPLATE = (
        "分析 {ticker} 的长期投资价值,对比 {peers_csv},给出 BUY/WATCH/AVOID 建议"
    )
    SEED_TICKERS_AND_PEERS: list[tuple[str, list[str]]] = [
        ("GOOGL", ["MSFT", "META"]),
        ("MSFT",  ["GOOGL", "AMZN"]),
        ("NVDA",  ["AMD", "AVGO"]),
        ("AAPL",  ["MSFT", "GOOGL"]),
        ("META",  ["GOOGL", "NFLX"]),
        ("AMZN",  ["MSFT", "GOOGL"]),
        ("TSLA",  ["GM", "FORD"]),
        ("AMD",   ["NVDA", "INTC"]),
        ("AVGO",  ["NVDA", "AMD"]),
        ("NFLX",  ["DIS", "AMZN"]),
    ]
    SEED_QUERIES = [
        {
            "ticker": ticker,
            "peers": peers,
            "question": SEED_QUESTION_TEMPLATE.format(
                ticker=ticker, peers_csv=", ".join(peers)
            ),
        }
        for ticker, peers in SEED_TICKERS_AND_PEERS
    ]
    with Session(engine) as db:
        existing = default_suite_store.get_by_name(db, SEED_NAME, include_archived=True)
        if existing is not None:
            return
        # ``created_by`` is informational; use the demo user so prod and
        # dev share the same provenance shape. In prod the admin will see
        # "created_by=<demo-uid>" + can rename / take ownership via PATCH.
        demo = ensure_demo_user(db)
        default_suite_store.create(
            db,
            name=SEED_NAME,
            skill_name="company_research_pipeline",
            queries=SEED_QUERIES,
            description=(
                "US mega-cap tickers · seed suite for prompt-tuning A/B compare. "
                "10 queries · GOOGL/MSFT/NVDA/AAPL/META/AMZN/TSLA/AMD/AVGO/NFLX."
            ),
            created_by=demo.id,
        )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # M4: build/migrate schema + materialize the demo fallback user.
    init_db()
    from sqlmodel import Session

    from uteki_api.core.db import engine

    with Session(engine) as db:
        ensure_demo_user(db)
        # 010 — pre-create the owner record from settings.owner_emails so
        # data partitioning under owner.id works from the very first request,
        # before the owner has ever OAuth'd in. No-op if owner_emails is
        # unset (acceptable in dev / tests).
        from uteki_api.users import ensure_owner_user

        ensure_owner_user(db)

    await _seed_evolution_versions()
    await _seed_default_bench_suite()
    yield


app = FastAPI(
    title="uteki-api",
    version=__version__,
    description="uteki — 投研智能体后端",
    openapi_url="/openapi.json",
    docs_url="/docs",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth_api.router)
app.include_router(agent.router)
app.include_router(agents_api.router)
app.include_router(runs_api.router)
app.include_router(artifacts_api.router)
app.include_router(compare.router)
app.include_router(triggers.router)
app.include_router(news.router)
app.include_router(companies.router)
app.include_router(symbols.router)
app.include_router(earnings.router)
app.include_router(eval_api.router)
app.include_router(admin.router)
app.include_router(tag_groups.router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": "uteki-api", "version": __version__, "docs": "/docs"}
