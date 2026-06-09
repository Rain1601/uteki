"""SQLModel tables for the news domain.

Five tables:

- ``tag_group``  — a taxonomy bucket (e.g. "重要度") with single/multi mode.
- ``tag``        — an option inside a group (e.g. "high").
- ``news_article`` — a story. AI fields (impact / ai_analysis) stay nullable
  until the analysis SSE pipeline writes them.
- ``article_tag`` — M:N article ↔ tag.
- ``trigger_hit`` — M:N article ↔ trigger. ``trigger_id`` is currently a
  free-form string because triggers live in the in-memory registry; when
  triggers become DB rows it can be promoted to a foreign key in a
  follow-up migration without changing the column shape.

CSV-encoded ``symbols`` matches the pattern used by ``Run.user_input`` —
the only consumers are display + substring search, so JSON would be
overkill. If we ever need to query by symbol we'll move it to a join
table at that point.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel, UniqueConstraint


class TagGroup(SQLModel, table=True):
    __tablename__ = "tag_group"

    id: str = Field(primary_key=True, max_length=64)
    name: str = Field(unique=True, index=True, max_length=64)
    description: str = Field(default="", max_length=512)
    mode: str = Field(default="multi", max_length=8)  # single | multi
    sort_order: int = Field(default=0)
    created_at: datetime


class Tag(SQLModel, table=True):
    __tablename__ = "tag"
    __table_args__ = (UniqueConstraint("group_id", "name"),)

    id: str = Field(primary_key=True, max_length=64)
    group_id: str = Field(foreign_key="tag_group.id", index=True, max_length=64)
    name: str = Field(max_length=64)
    description: str = Field(default="", max_length=512)
    sort_order: int = Field(default=0)
    color: str | None = Field(default=None, max_length=16)


class NewsArticle(SQLModel, table=True):
    __tablename__ = "news_article"

    id: str = Field(primary_key=True, max_length=64)  # url hash or uuid
    title: str = Field(max_length=512)
    title_zh: str | None = Field(default=None, max_length=512)
    summary: str = Field(default="", max_length=2048)
    summary_zh: str | None = Field(default=None, max_length=2048)
    content: str = Field(default="")
    content_zh: str | None = Field(default=None)
    url: str = Field(default="", max_length=1024)
    author: str | None = Field(default=None, max_length=128)
    source: str = Field(default="", max_length=64)  # e.g. "cnbc"
    symbols: str = Field(default="", max_length=512)  # CSV
    published_at: datetime = Field(index=True)
    ingested_at: datetime

    # AI-derived (populated by /analyze SSE)
    impact: str | None = Field(default=None, max_length=16)  # positive | negative | neutral
    ai_analysis: str | None = Field(default=None)
    ai_analysis_status: str = Field(default="pending", max_length=16)  # pending | streaming | done | error
    ai_analyzed_at: datetime | None = Field(default=None)

    # Feedback counters (incremented via /feedback POST)
    like_count: int = Field(default=0)
    dislike_count: int = Field(default=0)


class ArticleTag(SQLModel, table=True):
    __tablename__ = "article_tag"

    article_id: str = Field(
        foreign_key="news_article.id", primary_key=True, max_length=64
    )
    tag_id: str = Field(foreign_key="tag.id", primary_key=True, max_length=64)


class TriggerHit(SQLModel, table=True):
    __tablename__ = "trigger_hit"

    id: str = Field(primary_key=True, max_length=64)
    # trigger_id is currently a free-form string (in-memory trigger registry);
    # promote to FK when triggers become DB rows.
    trigger_id: str = Field(index=True, max_length=64)
    article_id: str = Field(
        foreign_key="news_article.id", index=True, max_length=64
    )
    fired_at: datetime = Field(index=True)


class NewsFeedback(SQLModel, table=True):
    __tablename__ = "news_feedback"
    __table_args__ = (UniqueConstraint("user_id", "article_id"),)

    id: str = Field(primary_key=True, max_length=64)
    user_id: str = Field(foreign_key="user.id", index=True, max_length=64)
    article_id: str = Field(
        foreign_key="news_article.id", index=True, max_length=64
    )
    kind: str = Field(max_length=8)  # like | dislike
    created_at: datetime
    updated_at: datetime
