"""Agent (skill) catalog + evolution-history endpoints.

GET /api/agents              list all registered skills with current version
GET /api/agents/{name}       single skill detail
GET /api/agents/{name}/versions
GET /api/agents/{name}/versions/{version}
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from uteki_api.auth.deps import current_user
from uteki_api.evolution import default_evolution_store
from uteki_api.skills import default_skills

router = APIRouter(
    prefix="/api/agents",
    tags=["agents"],
    dependencies=[Depends(current_user)],
)


@router.get("")
async def list_skills() -> dict:
    items = []
    for entry in default_skills.list():
        latest = await default_evolution_store.latest(entry["name"])
        items.append(
            {
                **entry,
                "current_version": latest.model_dump() if latest else None,
            }
        )
    return {"items": items}


@router.get("/{name}")
async def get_skill(name: str) -> dict:
    try:
        entry = default_skills.entry(name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    latest = await default_evolution_store.latest(name)
    return {
        **entry.to_dict(),
        "current_version": latest.model_dump() if latest else None,
    }


@router.get("/{name}/versions")
async def list_versions(name: str, limit: int = 20) -> dict:
    try:
        default_skills.entry(name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    versions = await default_evolution_store.list(name, limit=limit)
    return {"items": [v.model_dump() for v in versions]}


@router.get("/{name}/versions/{version}")
async def get_version(name: str, version: str) -> dict:
    try:
        default_skills.entry(name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    versions = await default_evolution_store.list(name, limit=1000)
    for v in versions:
        if v.version == version:
            return v.model_dump()
    raise HTTPException(status_code=404, detail=f"version not found: {version}")
