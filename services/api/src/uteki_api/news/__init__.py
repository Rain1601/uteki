"""News domain — articles, tag taxonomy, and trigger-hit linkage.

Migrated from uteki.open's standalone news-timeline page; reshaped to fit
uteki's trigger-driven model. News is no longer a passive feed — it lives
under a specific trigger as the trigger's "what fired me" record.

Tag taxonomy is user-defined (admin manages TagGroup + Tag), so the
category/importance enums from the source project are gone. Tags are
applied to articles via the ArticleTag join.
"""

from uteki_api.news.models import (
    ArticleTag,
    NewsArticle,
    Tag,
    TagGroup,
    TriggerHit,
)
from uteki_api.news.store import NewsStore, default_news_store

__all__ = [
    "ArticleTag",
    "NewsArticle",
    "NewsStore",
    "Tag",
    "TagGroup",
    "TriggerHit",
    "default_news_store",
]
