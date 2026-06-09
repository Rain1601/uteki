"""Pull per-ticker company news from Google News RSS for every watchlist
company and land it under trg-news-002.

This is deliberately separate from trg-news-001 (which carries the
macro CNBC jeff-cox feed). The split is conceptual: trg-news-001
listens for non-company economic events; trg-news-002 is the per-
ticker company channel.

Tag mapping per article:
    重要度 = medium   (general company news; SEC filings own high/critical)
    类别  = equities
    (no 事件 tag — events fire through SEC 8-K → trg-event-003)

Idempotent — articles use the Google News ``guid`` as primary key, so
re-running just no-ops on already-ingested items. Trigger_hit and
ArticleTag links dedup before insert.

Usage (from services/api/):
    uv run python scripts/ingest_company_news.py
    uv run python scripts/ingest_company_news.py --symbol AAPL
    uv run python scripts/ingest_company_news.py --dry-run
    uv run python scripts/ingest_company_news.py --count 50
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "src"))

from sqlmodel import Session, select  # noqa: E402

from uteki_api.companies.store import default_company_store  # noqa: E402
from uteki_api.core.db import engine, init_db  # noqa: E402
from uteki_api.news.models import (  # noqa: E402
    ArticleTag,
    NewsArticle,
    Tag,
    TagGroup,
    TriggerHit,
)
from uteki_api.news_sources.google_news import (  # noqa: E402
    GoogleNewsItem,
    build_query,
    fetch_news_for_query,
    is_relevant_to,
)


TARGET_TRIGGER_ID = "trg-news-002"
DEFAULT_IMPORTANCE = "medium"
DEFAULT_CATEGORY = "equities"


# ─── Helpers ─────────────────────────────────────────────────────────


def build_tag_lookup(db: Session) -> dict[str, str]:
    out: dict[str, str] = {}
    for group in db.exec(select(TagGroup)).all():
        for tag in db.exec(select(Tag).where(Tag.group_id == group.id)).all():
            out[f"{group.name}:{tag.name}"] = tag.id
    return out


# Derive a couple of keywords from the canonical name: strip Inc / Corp /
# Group / Ltd suffixes and use the leading 1-2 tokens. Conservative on
# purpose — too-loose keywords cause false positives.
_SUFFIX_STRIP = re.compile(
    r"\b(Inc\.?|Corp\.?|Corporation|Ltd\.?|Limited|Co\.?|Group|Holdings|PLC|S\.A\.|N\.V\.|LLC|Manufacturing)\b",
    re.IGNORECASE,
)


def company_keywords(name: str) -> list[str]:
    cleaned = _SUFFIX_STRIP.sub("", name).strip().rstrip(",")
    if not cleaned:
        return []
    parts = cleaned.split()
    primary = parts[0]
    return [primary, cleaned] if cleaned != primary else [primary]


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ─── Ingest one item ─────────────────────────────────────────────────


def ingest_item(
    db: Session,
    item: GoogleNewsItem,
    *,
    symbol: str,
    tag_ids_for_taxonomy: dict[str, str],
    dry_run: bool,
) -> tuple[bool, bool, int]:
    article_id = item.guid[:64]  # PK length cap.
    existing = db.get(NewsArticle, article_id)
    was_new = existing is None

    if was_new and not dry_run:
        article = NewsArticle(
            id=article_id,
            title=truncate(item.title, 512),
            title_zh=None,
            summary="",  # Google News RSS gives no real summary; description is just an HTML link.
            summary_zh=None,
            content="",
            content_zh=None,
            url=item.link,
            author=item.publisher or None,
            source="google_news",
            symbols=symbol,
            published_at=item.published_at,
            ingested_at=datetime.now(UTC),
            ai_analysis_status="pending",
        )
        db.add(article)

    # Tag attachment.
    tags_to_apply: list[str] = []
    for key in (f"重要度:{DEFAULT_IMPORTANCE}", f"类别:{DEFAULT_CATEGORY}"):
        if key in tag_ids_for_taxonomy:
            tags_to_apply.append(tag_ids_for_taxonomy[key])

    tags_added = 0
    if tags_to_apply and not dry_run:
        already = {
            link.tag_id
            for link in db.exec(
                select(ArticleTag).where(ArticleTag.article_id == article_id)
            ).all()
        }
        for tag_id in tags_to_apply:
            if tag_id in already:
                continue
            db.add(ArticleTag(article_id=article_id, tag_id=tag_id))
            tags_added += 1

    # Trigger hit.
    hit_created = False
    if not dry_run:
        existing_hit = db.exec(
            select(TriggerHit).where(
                TriggerHit.trigger_id == TARGET_TRIGGER_ID,
                TriggerHit.article_id == article_id,
            )
        ).first()
        if existing_hit is None:
            db.add(
                TriggerHit(
                    id=uuid.uuid4().hex[:12],
                    trigger_id=TARGET_TRIGGER_ID,
                    article_id=article_id,
                    fired_at=item.published_at,
                )
            )
            hit_created = True

    return was_new, hit_created, tags_added


# ─── Driver ──────────────────────────────────────────────────────────


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", help="Only ingest this ticker.")
    parser.add_argument(
        "--count",
        type=int,
        default=30,
        help="Max items per ticker (Google caps around 100).",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    init_db()
    with Session(engine) as db:
        tag_ids = build_tag_lookup(db)
        if "重要度:medium" not in tag_ids or "类别:equities" not in tag_ids:
            print(
                "ERR: tag taxonomy missing — run scripts/seed_news_demo.py first.",
                file=sys.stderr,
            )
            return 3

        companies = default_company_store.list(db, watch_only=True)
        if args.symbol:
            companies = [c for c in companies if c.symbol == args.symbol.upper()]
        if not companies:
            print("no watchlist companies match the filter")
            return 0

        print(f"▶ ingesting {len(companies)} companies → trg-news-002")
        if args.dry_run:
            print("(dry-run) — no writes")

        total_new = 0
        total_hits = 0
        total_tags = 0
        total_skipped = 0

        for company in companies:
            query = build_query(company.symbol, company.name)
            print(f"▶ {company.symbol:<8} q={query!r}")
            try:
                items = await fetch_news_for_query(query)
            except Exception as e:
                print(f"  ✗ fetch failed: {e}")
                continue

            kws = company_keywords(company.name)
            # Slice to args.count after relevance filter so we keep the
            # top N actually-relevant items, not the top N including noise.
            relevant: list[GoogleNewsItem] = [
                it for it in items
                if is_relevant_to(it, ticker=company.symbol, company_keywords=kws)
            ]
            dropped = len(items) - len(relevant)
            relevant = relevant[: args.count]
            print(
                f"  fetched={len(items)} relevant={len(relevant)} dropped={dropped}"
            )

            for it in relevant:
                was_new, hit_created, tags_added = ingest_item(
                    db,
                    it,
                    symbol=company.symbol,
                    tag_ids_for_taxonomy=tag_ids,
                    dry_run=args.dry_run,
                )
                if was_new:
                    total_new += 1
                if hit_created:
                    total_hits += 1
                total_tags += tags_added
                flag = "+" if was_new else "·"
                print(
                    f"  {flag} [{it.publisher[:14]:14}] {truncate(it.title, 70)}"
                )

            total_skipped += dropped

            if not args.dry_run:
                db.commit()

        if not args.dry_run:
            db.commit()

    print(
        f"✓ done — new articles: {total_new}, "
        f"trigger hits: {total_hits}, "
        f"tag links: {total_tags}, "
        f"dropped as off-topic: {total_skipped}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
