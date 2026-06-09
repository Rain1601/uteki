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

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session

from uteki_api.auth.deps import current_user
from uteki_api.core.config import settings
from uteki_api.core.db import get_db
from uteki_api.llm.router import default_router
from uteki_api.llm.usage import UsageDelta
from uteki_api.schemas.chat import ChatMessage
from uteki_api.news.models import NewsArticle
from uteki_api.news.store import default_news_store
from uteki_api.users.models import User

logger = logging.getLogger(__name__)

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


# ─── AI analysis SSE ─────────────────────────────────────────────────


ANALYZE_SYSTEM = (
    "你是一名资深财经分析师。给定一条新闻，输出一份中文短分析：\n"
    "1) 用 1-2 句概括对市场/相关公司的直接影响；\n"
    "2) 指出此事影响的板块或资产类别；\n"
    "3) 给出方向判断（利多 / 利空 / 中性）和原因。\n"
    "保持精炼，不超过 8 句话；不要复述新闻本身。\n"
    "在最后一行单独写一行 IMPACT=<positive|negative|neutral>（大小写不限），"
    "前端会据此着色。"
)

ANALYZE_MOCK_TEXT = (
    "这条新闻对相关板块的直接影响中性偏正面。\n"
    "短期可能利好科技板块龙头公司，对宏观资产配置影响有限。\n"
    "建议关注后续业绩兑现度，避免追高。\n"
    "IMPACT=positive"
)


def _extract_impact(text: str) -> str | None:
    """Pull the last ``IMPACT=<word>`` line if present."""
    for line in reversed(text.strip().splitlines()):
        stripped = line.strip().upper()
        if stripped.startswith("IMPACT="):
            value = stripped[len("IMPACT=") :].strip().lower()
            if value in {"positive", "negative", "neutral"}:
                return value
    return None


def _build_analyze_messages(article: NewsArticle) -> list[ChatMessage]:
    body_lines = [
        f"# {article.title}",
        f"published_at: {article.published_at.isoformat()}",
        f"source: {article.source}",
        f"symbols: {article.symbols}",
        "",
        article.summary or article.content or "(no content)",
    ]
    if article.title_zh:
        body_lines.insert(1, f"中文标题: {article.title_zh}")
    return [
        ChatMessage(role="system", content=ANALYZE_SYSTEM),
        ChatMessage(role="user", content="\n".join(body_lines)),
    ]


async def _mock_stream() -> AsyncIterator[str]:
    """Deterministic stream used when no LLM provider is configured."""
    import asyncio

    for chunk in ANALYZE_MOCK_TEXT.split(" "):
        await asyncio.sleep(0.02)
        yield chunk + " "


def _sse(event: dict) -> bytes:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode()


@router.post("/api/news/{article_id}/analyze")
async def analyze_article(
    article_id: str,
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream an AI analysis of a news article and persist the result.

    Wire protocol: each frame is ``data: {<json>}\\n\\n``. JSON shapes:

    - ``{"type": "delta", "content": "<text chunk>"}`` — incremental token
    - ``{"type": "done", "impact": "<pos|neg|neutral|null>",
         "analysis": "<full text>"}`` — terminal
    - ``{"type": "error", "message": "..."}`` — terminal on failure

    Persists the full analysis + impact + ``ai_analyzed_at`` on completion;
    article ``ai_analysis_status`` transitions pending → streaming → done.
    """
    article = default_news_store.get_article(db, article_id)
    if article is None:
        raise HTTPException(404, detail=f"article {article_id} not found")

    use_mock = settings.use_mock_llm
    if not use_mock:
        try:
            client = default_router.resolve()
        except Exception as e:  # noqa: BLE001
            logger.warning("router.resolve failed; falling back to mock: %s", e)
            use_mock = True
        else:
            if not client.configured:
                use_mock = True

    async def _stream() -> AsyncIterator[bytes]:
        default_news_store.upsert_article(
            db, article_id=article_id, ai_analysis_status="streaming"
        )
        buf: list[str] = []
        try:
            if use_mock:
                async for chunk in _mock_stream():
                    buf.append(chunk)
                    yield _sse({"type": "delta", "content": chunk})
            else:
                client = default_router.resolve()
                messages = _build_analyze_messages(article)
                async for chunk in client.stream_chat(messages):
                    if isinstance(chunk, UsageDelta):
                        continue
                    buf.append(chunk)
                    yield _sse({"type": "delta", "content": chunk})

            full = "".join(buf).strip()
            impact = _extract_impact(full)
            default_news_store.upsert_article(
                db,
                article_id=article_id,
                ai_analysis=full,
                impact=impact,
                ai_analysis_status="done",
                ai_analyzed_at=datetime.now(UTC),
            )
            yield _sse({"type": "done", "impact": impact, "analysis": full})
        except Exception as e:  # noqa: BLE001
            logger.exception("analyze_article failed for %s", article_id)
            default_news_store.upsert_article(
                db, article_id=article_id, ai_analysis_status="error"
            )
            yield _sse({"type": "error", "message": str(e)})

    return StreamingResponse(_stream(), media_type="text/event-stream")


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
