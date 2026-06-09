"""NewsStore — DB facade for the news domain.

Same pattern as ``UserStore``: thin wrapper over SQLModel sessions so
route handlers don't sprinkle ``select(...)`` everywhere. Returns plain
SQLModel rows; the API layer maps to response models with their own
shapes (so we can join in tag names / providers / etc).
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime

from sqlalchemy import func
from sqlmodel import Session, select

from uteki_api.news.models import (
    ArticleTag,
    NewsArticle,
    NewsFeedback,
    Tag,
    TagGroup,
    TriggerHit,
)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class NewsStore(ABC):
    # ─── TagGroup ─────────────────────────────────────────────────────
    @abstractmethod
    def list_tag_groups(self, db: Session) -> list[TagGroup]: ...

    @abstractmethod
    def get_tag_group(self, db: Session, group_id: str) -> TagGroup | None: ...

    @abstractmethod
    def create_tag_group(
        self,
        db: Session,
        *,
        name: str,
        description: str = "",
        mode: str = "multi",
        sort_order: int = 0,
    ) -> TagGroup: ...

    @abstractmethod
    def update_tag_group(
        self,
        db: Session,
        group_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        mode: str | None = None,
        sort_order: int | None = None,
    ) -> TagGroup | None: ...

    @abstractmethod
    def delete_tag_group(self, db: Session, group_id: str) -> bool: ...

    # ─── Tag ──────────────────────────────────────────────────────────
    @abstractmethod
    def list_tags(self, db: Session, *, group_id: str | None = None) -> list[Tag]: ...

    @abstractmethod
    def create_tag(
        self,
        db: Session,
        *,
        group_id: str,
        name: str,
        description: str = "",
        sort_order: int = 0,
        color: str | None = None,
    ) -> Tag: ...

    @abstractmethod
    def update_tag(
        self,
        db: Session,
        tag_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        sort_order: int | None = None,
        color: str | None = None,
    ) -> Tag | None: ...

    @abstractmethod
    def delete_tag(self, db: Session, tag_id: str) -> bool: ...

    # ─── NewsArticle ──────────────────────────────────────────────────
    @abstractmethod
    def get_article(self, db: Session, article_id: str) -> NewsArticle | None: ...

    @abstractmethod
    def list_articles_for_trigger(
        self,
        db: Session,
        *,
        trigger_id: str,
        limit: int = 50,
        offset: int = 0,
        tag_ids: list[str] | None = None,
    ) -> tuple[list[NewsArticle], int]: ...

    @abstractmethod
    def article_tags(self, db: Session, article_id: str) -> list[str]: ...

    @abstractmethod
    def upsert_article(
        self,
        db: Session,
        *,
        article_id: str | None = None,
        **fields: object,
    ) -> NewsArticle: ...

    @abstractmethod
    def set_article_tags(
        self, db: Session, article_id: str, tag_ids: list[str]
    ) -> None: ...

    @abstractmethod
    def record_trigger_hit(
        self,
        db: Session,
        *,
        trigger_id: str,
        article_id: str,
        fired_at: datetime | None = None,
    ) -> TriggerHit: ...

    # ─── Feedback ─────────────────────────────────────────────────────
    @abstractmethod
    def get_feedback(
        self, db: Session, *, user_id: str, article_id: str
    ) -> NewsFeedback | None: ...

    @abstractmethod
    def set_feedback(
        self, db: Session, *, user_id: str, article_id: str, kind: str | None
    ) -> tuple[NewsArticle, NewsFeedback | None]:
        """Set / toggle / clear a user's feedback on an article.

        Returns the updated ``NewsArticle`` (with refreshed counters) and
        the resulting feedback row (None if cleared).
        """
        ...


class SqlNewsStore(NewsStore):
    # ─── TagGroup ─────────────────────────────────────────────────────
    def list_tag_groups(self, db: Session) -> list[TagGroup]:
        return list(
            db.exec(
                select(TagGroup).order_by(TagGroup.sort_order, TagGroup.name)
            ).all()
        )

    def get_tag_group(self, db: Session, group_id: str) -> TagGroup | None:
        return db.get(TagGroup, group_id)

    def create_tag_group(
        self,
        db: Session,
        *,
        name: str,
        description: str = "",
        mode: str = "multi",
        sort_order: int = 0,
    ) -> TagGroup:
        group = TagGroup(
            id=_new_id(),
            name=name.strip(),
            description=description,
            mode=mode,
            sort_order=sort_order,
            created_at=_utcnow(),
        )
        db.add(group)
        db.commit()
        db.refresh(group)
        return group

    def update_tag_group(
        self,
        db: Session,
        group_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        mode: str | None = None,
        sort_order: int | None = None,
    ) -> TagGroup | None:
        group = db.get(TagGroup, group_id)
        if group is None:
            return None
        if name is not None:
            group.name = name.strip()
        if description is not None:
            group.description = description
        if mode is not None:
            group.mode = mode
        if sort_order is not None:
            group.sort_order = sort_order
        db.add(group)
        db.commit()
        db.refresh(group)
        return group

    def delete_tag_group(self, db: Session, group_id: str) -> bool:
        group = db.get(TagGroup, group_id)
        if group is None:
            return False
        # Cascade: delete tags in this group (and their article_tag links)
        tags = db.exec(select(Tag).where(Tag.group_id == group_id)).all()
        for tag in tags:
            self._delete_tag_links(db, tag.id)
            db.delete(tag)
        db.delete(group)
        db.commit()
        return True

    # ─── Tag ──────────────────────────────────────────────────────────
    def list_tags(self, db: Session, *, group_id: str | None = None) -> list[Tag]:
        stmt = select(Tag)
        if group_id is not None:
            stmt = stmt.where(Tag.group_id == group_id)
        return list(db.exec(stmt.order_by(Tag.sort_order, Tag.name)).all())

    def create_tag(
        self,
        db: Session,
        *,
        group_id: str,
        name: str,
        description: str = "",
        sort_order: int = 0,
        color: str | None = None,
    ) -> Tag:
        tag = Tag(
            id=_new_id(),
            group_id=group_id,
            name=name.strip(),
            description=description,
            sort_order=sort_order,
            color=color,
        )
        db.add(tag)
        db.commit()
        db.refresh(tag)
        return tag

    def update_tag(
        self,
        db: Session,
        tag_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        sort_order: int | None = None,
        color: str | None = None,
    ) -> Tag | None:
        tag = db.get(Tag, tag_id)
        if tag is None:
            return None
        if name is not None:
            tag.name = name.strip()
        if description is not None:
            tag.description = description
        if sort_order is not None:
            tag.sort_order = sort_order
        if color is not None:
            tag.color = color
        db.add(tag)
        db.commit()
        db.refresh(tag)
        return tag

    def delete_tag(self, db: Session, tag_id: str) -> bool:
        tag = db.get(Tag, tag_id)
        if tag is None:
            return False
        self._delete_tag_links(db, tag_id)
        db.delete(tag)
        db.commit()
        return True

    def _delete_tag_links(self, db: Session, tag_id: str) -> None:
        for link in db.exec(
            select(ArticleTag).where(ArticleTag.tag_id == tag_id)
        ).all():
            db.delete(link)

    # ─── NewsArticle ──────────────────────────────────────────────────
    def get_article(self, db: Session, article_id: str) -> NewsArticle | None:
        return db.get(NewsArticle, article_id)

    def list_articles_for_trigger(
        self,
        db: Session,
        *,
        trigger_id: str,
        limit: int = 50,
        offset: int = 0,
        tag_ids: list[str] | None = None,
    ) -> tuple[list[NewsArticle], int]:
        """Standard taxonomy semantics:

        - ``tag_ids`` is a flat list across groups.
        - Tags **within the same group** are OR'd (multi-select).
        - Tags **across groups** are AND'd (must satisfy every active group).

        Implementation: look up each filter tag's ``group_id``, partition by
        group, then for each group emit a subquery "article has any tag in
        this group" and intersect them via WHERE-IN.
        """
        hit_subq = select(TriggerHit.article_id).where(
            TriggerHit.trigger_id == trigger_id
        )
        article_ids: list[str] = list(db.exec(hit_subq).all())
        if not article_ids:
            return [], 0

        stmt = select(NewsArticle).where(NewsArticle.id.in_(article_ids))  # type: ignore[attr-defined]

        if tag_ids:
            tags = list(
                db.exec(select(Tag).where(Tag.id.in_(tag_ids))).all()  # type: ignore[attr-defined]
            )
            by_group: dict[str, list[str]] = {}
            for tag in tags:
                by_group.setdefault(tag.group_id, []).append(tag.id)
            for group_tag_ids in by_group.values():
                in_group_articles = select(ArticleTag.article_id).where(
                    ArticleTag.tag_id.in_(group_tag_ids)  # type: ignore[attr-defined]
                )
                stmt = stmt.where(NewsArticle.id.in_(in_group_articles))  # type: ignore[attr-defined]

        total = db.exec(
            select(func.count()).select_from(stmt.subquery())  # type: ignore[arg-type]
        ).one()

        rows = db.exec(
            stmt.order_by(NewsArticle.published_at.desc())  # type: ignore[attr-defined]
            .offset(offset)
            .limit(limit)
        ).all()
        return list(rows), int(total)

    def article_tags(self, db: Session, article_id: str) -> list[str]:
        return list(
            db.exec(
                select(ArticleTag.tag_id).where(
                    ArticleTag.article_id == article_id
                )
            ).all()
        )

    def upsert_article(
        self,
        db: Session,
        *,
        article_id: str | None = None,
        **fields: object,
    ) -> NewsArticle:
        if article_id is None:
            article_id = _new_id()
        existing = db.get(NewsArticle, article_id)
        if existing is None:
            article = NewsArticle(id=article_id, ingested_at=_utcnow(), **fields)  # type: ignore[arg-type]
            db.add(article)
        else:
            for key, value in fields.items():
                setattr(existing, key, value)
            article = existing
            db.add(article)
        db.commit()
        db.refresh(article)
        return article

    def set_article_tags(
        self, db: Session, article_id: str, tag_ids: list[str]
    ) -> None:
        # Replace the article's tag set wholesale.
        for link in db.exec(
            select(ArticleTag).where(ArticleTag.article_id == article_id)
        ).all():
            db.delete(link)
        for tid in tag_ids:
            db.add(ArticleTag(article_id=article_id, tag_id=tid))
        db.commit()

    def record_trigger_hit(
        self,
        db: Session,
        *,
        trigger_id: str,
        article_id: str,
        fired_at: datetime | None = None,
    ) -> TriggerHit:
        hit = TriggerHit(
            id=_new_id(),
            trigger_id=trigger_id,
            article_id=article_id,
            fired_at=fired_at or _utcnow(),
        )
        db.add(hit)
        db.commit()
        db.refresh(hit)
        return hit

    # ─── Feedback ─────────────────────────────────────────────────────
    def get_feedback(
        self, db: Session, *, user_id: str, article_id: str
    ) -> NewsFeedback | None:
        return db.exec(
            select(NewsFeedback).where(
                NewsFeedback.user_id == user_id,
                NewsFeedback.article_id == article_id,
            )
        ).first()

    def set_feedback(
        self, db: Session, *, user_id: str, article_id: str, kind: str | None
    ) -> tuple[NewsArticle, NewsFeedback | None]:
        existing = self.get_feedback(db, user_id=user_id, article_id=article_id)
        article = db.get(NewsArticle, article_id)
        if article is None:
            raise KeyError(article_id)

        previous_kind = existing.kind if existing else None
        now = _utcnow()

        # Determine the resulting feedback row (or absence).
        result: NewsFeedback | None
        if kind is None:
            # Clear feedback.
            if existing is not None:
                db.delete(existing)
            result = None
        elif existing is None:
            result = NewsFeedback(
                id=_new_id(),
                user_id=user_id,
                article_id=article_id,
                kind=kind,
                created_at=now,
                updated_at=now,
            )
            db.add(result)
        else:
            existing.kind = kind
            existing.updated_at = now
            db.add(existing)
            result = existing

        # Adjust the article's denormalized counters.
        if previous_kind == "like":
            article.like_count = max(0, article.like_count - 1)
        elif previous_kind == "dislike":
            article.dislike_count = max(0, article.dislike_count - 1)
        if kind == "like":
            article.like_count += 1
        elif kind == "dislike":
            article.dislike_count += 1
        db.add(article)

        db.commit()
        db.refresh(article)
        if result is not None:
            db.refresh(result)
        return article, result


default_news_store: NewsStore = SqlNewsStore()
