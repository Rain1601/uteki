"""Admin CRUD for the global tag taxonomy.

Two tables: ``tag_group`` (a bucket like "重要度") + ``tag`` (an option in
that bucket like "high"). All mutations are admin-only. Read is exposed
separately via ``api/news.py:list_tag_groups`` for the filter UI so any
authenticated user can hydrate filter chips without admin scope.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from uteki_api.auth.deps import require_admin
from uteki_api.core.db import get_db
from uteki_api.news.store import default_news_store
from uteki_api.users.models import User

router = APIRouter(prefix="/api/admin", tags=["admin-tags"])


# ─── Schemas ─────────────────────────────────────────────────────────


class TagOut(BaseModel):
    id: str
    group_id: str
    name: str
    description: str
    sort_order: int
    color: str | None


class TagGroupOut(BaseModel):
    id: str
    name: str
    description: str
    mode: str
    sort_order: int
    created_at: str
    tags: list[TagOut]


class TagGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: str = ""
    mode: str = Field("multi", pattern=r"^(single|multi)$")
    sort_order: int = 0


class TagGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = None
    mode: str | None = Field(default=None, pattern=r"^(single|multi)$")
    sort_order: int | None = None


class TagCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: str = ""
    sort_order: int = 0
    color: str | None = Field(default=None, max_length=16)


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = None
    sort_order: int | None = None
    color: str | None = Field(default=None, max_length=16)


def _group_out(db: Session, group_id: str) -> TagGroupOut:
    group = default_news_store.get_tag_group(db, group_id)
    if group is None:
        raise HTTPException(404, detail=f"tag group {group_id} not found")
    tags = default_news_store.list_tags(db, group_id=group_id)
    return TagGroupOut(
        id=group.id,
        name=group.name,
        description=group.description,
        mode=group.mode,
        sort_order=group.sort_order,
        created_at=group.created_at.isoformat(),
        tags=[
            TagOut(
                id=t.id,
                group_id=t.group_id,
                name=t.name,
                description=t.description,
                sort_order=t.sort_order,
                color=t.color,
            )
            for t in tags
        ],
    )


# ─── TagGroup routes ─────────────────────────────────────────────────


@router.get("/tag-groups", response_model=list[TagGroupOut])
async def list_tag_groups(
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[TagGroupOut]:
    groups = default_news_store.list_tag_groups(db)
    return [_group_out(db, g.id) for g in groups]


@router.post("/tag-groups", response_model=TagGroupOut, status_code=201)
async def create_tag_group(
    body: TagGroupCreate,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TagGroupOut:
    group = default_news_store.create_tag_group(
        db,
        name=body.name,
        description=body.description,
        mode=body.mode,
        sort_order=body.sort_order,
    )
    return _group_out(db, group.id)


@router.patch("/tag-groups/{group_id}", response_model=TagGroupOut)
async def update_tag_group(
    group_id: str,
    body: TagGroupUpdate,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TagGroupOut:
    updated = default_news_store.update_tag_group(
        db,
        group_id,
        name=body.name,
        description=body.description,
        mode=body.mode,
        sort_order=body.sort_order,
    )
    if updated is None:
        raise HTTPException(404, detail=f"tag group {group_id} not found")
    return _group_out(db, group_id)


@router.delete("/tag-groups/{group_id}", status_code=204)
async def delete_tag_group(
    group_id: str,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    ok = default_news_store.delete_tag_group(db, group_id)
    if not ok:
        raise HTTPException(404, detail=f"tag group {group_id} not found")


# ─── Tag routes ──────────────────────────────────────────────────────


@router.post("/tag-groups/{group_id}/tags", response_model=TagOut, status_code=201)
async def create_tag(
    group_id: str,
    body: TagCreate,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TagOut:
    if default_news_store.get_tag_group(db, group_id) is None:
        raise HTTPException(404, detail=f"tag group {group_id} not found")
    tag = default_news_store.create_tag(
        db,
        group_id=group_id,
        name=body.name,
        description=body.description,
        sort_order=body.sort_order,
        color=body.color,
    )
    return TagOut(
        id=tag.id,
        group_id=tag.group_id,
        name=tag.name,
        description=tag.description,
        sort_order=tag.sort_order,
        color=tag.color,
    )


@router.patch("/tags/{tag_id}", response_model=TagOut)
async def update_tag(
    tag_id: str,
    body: TagUpdate,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TagOut:
    updated = default_news_store.update_tag(
        db,
        tag_id,
        name=body.name,
        description=body.description,
        sort_order=body.sort_order,
        color=body.color,
    )
    if updated is None:
        raise HTTPException(404, detail=f"tag {tag_id} not found")
    return TagOut(
        id=updated.id,
        group_id=updated.group_id,
        name=updated.name,
        description=updated.description,
        sort_order=updated.sort_order,
        color=updated.color,
    )


@router.delete("/tags/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: str,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    ok = default_news_store.delete_tag(db, tag_id)
    if not ok:
        raise HTTPException(404, detail=f"tag {tag_id} not found")
