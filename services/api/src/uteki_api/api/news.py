"""User-facing news endpoints.

- ``GET /api/tag-groups`` — read-only taxonomy snapshot used by filter UI.
  Open to any logged-in user (admin owns the mutation surface in
  ``api/tag_groups.py``).
- ``GET /api/triggers/{trigger_id}/news`` — list articles fired by a
  trigger. Supports ``tag_ids`` query (CSV) for AND-filter and standard
  ``limit`` / ``offset`` pagination.
- ``GET /api/news/{article_id}`` — single article with joined tag IDs.

There is no public ``POST`` for articles or trigger hits — those will be
written by the trigger evaluator (when it lands) or by admin scripts
during dev.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from uteki_api.auth.deps import current_user
from uteki_api.core.db import get_db
from uteki_api.news.models import NewsArticle
from uteki_api.news.store import default_news_store
from uteki_api.users.models import User

router = APIRouter(tags=["news"])


# ─── Response models ─────────────────────────────────────────────────


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
    tags: list[TagOut]


class ArticleSummary(BaseModel):
    id: str
    title: str
    title_zh: str | None
    summary: str
    summary_zh: str | None
    source: str
    author: str | None
    url: str
    symbols: list[str]
    published_at: str
    impact: str | None
    ai_analysis_status: str
    like_count: int
    dislike_count: int
    tag_ids: list[str]


class ArticleDetail(ArticleSummary):
    content: str
    content_zh: str | None
    ai_analysis: str | None
    ai_analyzed_at: str | None


class ArticleListResponse(BaseModel):
    items: list[ArticleSummary]
    total: int
    limit: int
    offset: int


def _split_csv(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


def _summary(article: NewsArticle, tag_ids: list[str]) -> ArticleSummary:
    return ArticleSummary(
        id=article.id,
        title=article.title,
        title_zh=article.title_zh,
        summary=article.summary,
        summary_zh=article.summary_zh,
        source=article.source,
        author=article.author,
        url=article.url,
        symbols=_split_csv(article.symbols),
        published_at=article.published_at.isoformat(),
        impact=article.impact,
        ai_analysis_status=article.ai_analysis_status,
        like_count=article.like_count,
        dislike_count=article.dislike_count,
        tag_ids=tag_ids,
    )


# ─── Routes ──────────────────────────────────────────────────────────


@router.get("/api/tag-groups", response_model=list[TagGroupOut])
async def list_tag_groups_public(
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[TagGroupOut]:
    """Read-only taxonomy snapshot for filter UI. Any logged-in user."""
    groups = default_news_store.list_tag_groups(db)
    result: list[TagGroupOut] = []
    for g in groups:
        tags = default_news_store.list_tags(db, group_id=g.id)
        result.append(
            TagGroupOut(
                id=g.id,
                name=g.name,
                description=g.description,
                mode=g.mode,
                sort_order=g.sort_order,
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
        )
    return result


@router.get(
    "/api/triggers/{trigger_id}/news",
    response_model=ArticleListResponse,
)
async def list_articles_for_trigger(
    trigger_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    tag_ids: str = Query("", description="CSV of tag IDs to AND-filter"),
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ArticleListResponse:
    tag_filter = _split_csv(tag_ids) or None
    rows, total = default_news_store.list_articles_for_trigger(
        db,
        trigger_id=trigger_id,
        limit=limit,
        offset=offset,
        tag_ids=tag_filter,
    )
    return ArticleListResponse(
        items=[
            _summary(article, default_news_store.article_tags(db, article.id))
            for article in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/api/news/{article_id}", response_model=ArticleDetail)
async def get_article(
    article_id: str,
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ArticleDetail:
    article = default_news_store.get_article(db, article_id)
    if article is None:
        raise HTTPException(404, detail=f"article {article_id} not found")
    tag_ids = default_news_store.article_tags(db, article_id)
    return ArticleDetail(
        **_summary(article, tag_ids).model_dump(),
        content=article.content,
        content_zh=article.content_zh,
        ai_analysis=article.ai_analysis,
        ai_analyzed_at=(
            article.ai_analyzed_at.isoformat() if article.ai_analyzed_at else None
        ),
    )
