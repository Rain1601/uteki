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


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # M4: build/migrate schema + materialize the demo fallback user.
    init_db()
    from sqlmodel import Session

    from uteki_api.core.db import engine

    with Session(engine) as db:
        ensure_demo_user(db)

    await _seed_evolution_versions()
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
app.include_router(earnings.router)
app.include_router(eval_api.router)
app.include_router(admin.router)
app.include_router(tag_groups.router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": "uteki-api", "version": __version__, "docs": "/docs"}
