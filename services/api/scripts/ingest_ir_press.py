"""Pull IR newsroom feeds for every watchlist company that has an
``ir_rss_url`` filled, ingest into news_article, and bind to trg-news-002.

This is the fastest free signal layer — most IR feeds publish a
release within seconds of going live, which beats SEC EDGAR by 5-30
minutes. Combined with the SEC ingest and Google News ingest, we get
multi-layer coverage of company events.

Tag mapping per article:
    重要度 = high      (IR-direct = source-of-truth, treat as high)
    类别  = equities
    事件  = guidance   (most IR releases are guidance / product /
                        leadership announcements; admin can re-tag)

Idempotent — articles use the feed's guid as primary key.

Usage (from services/api/):
    uv run python scripts/ingest_ir_press.py
    uv run python scripts/ingest_ir_press.py --symbol AAPL
    uv run python scripts/ingest_ir_press.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
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
from uteki_api.news_sources.ir_rss import IRNewsItem, fetch_ir_feed  # noqa: E402


TARGET_TRIGGER_ID = "trg-news-002"
SOURCE = "ir_rss"


def build_tag_lookup(db: Session) -> dict[str, str]:
    out: dict[str, str] = {}
    for group in db.exec(select(TagGroup)).all():
        for tag in db.exec(select(Tag).where(Tag.group_id == group.id)).all():
            out[f"{group.name}:{tag.name}"] = tag.id
    return out


def stable_article_id(guid: str, symbol: str) -> str:
    """IR guids can be 100+ chars or contain ":" / "/" — hash to a
    64-char-friendly identifier. Includes symbol so two feeds that
    accidentally use the same guid don't collide."""
    h = hashlib.sha1(f"{symbol}:{guid}".encode()).hexdigest()[:24]
    return f"ir-{h}"


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def ingest_item(
    db: Session,
    item: IRNewsItem,
    *,
    symbol: str,
    tag_ids: dict[str, str],
    dry_run: bool,
) -> tuple[bool, bool, int]:
    article_id = stable_article_id(item.guid, symbol)
    existing = db.get(NewsArticle, article_id)
    was_new = existing is None
    if was_new and not dry_run:
        article = NewsArticle(
            id=article_id,
            title=truncate(item.title, 512),
            title_zh=None,
            summary=truncate(item.summary, 2000),
            summary_zh=None,
            content=item.summary,
            content_zh=None,
            url=item.link,
            author=None,
            source=SOURCE,
            symbols=symbol,
            published_at=item.published_at,
            ingested_at=datetime.now(UTC),
            ai_analysis_status="pending",
        )
        db.add(article)

    # Tag attachment.
    desired_tags: list[str] = []
    for key in ("重要度:high", "类别:equities", "事件:guidance"):
        if key in tag_ids:
            desired_tags.append(tag_ids[key])
    tags_added = 0
    if desired_tags and not dry_run:
        already = {
            link.tag_id
            for link in db.exec(
                select(ArticleTag).where(ArticleTag.article_id == article_id)
            ).all()
        }
        for tag_id in desired_tags:
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


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", help="Only ingest this ticker.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    init_db()
    with Session(engine) as db:
        tag_ids = build_tag_lookup(db)
        if "重要度:high" not in tag_ids:
            print(
                "ERR: tag taxonomy missing — run scripts/seed_news_demo.py first.",
                file=sys.stderr,
            )
            return 3

        companies = default_company_store.list(db, watch_only=True)
        if args.symbol:
            companies = [c for c in companies if c.symbol == args.symbol.upper()]

        targets = [c for c in companies if c.ir_rss_url]
        skipped = [c.symbol for c in companies if not c.ir_rss_url]
        if skipped:
            print(
                f"⚠ skipping {len(skipped)} companies without ir_rss_url: "
                f"{', '.join(skipped)}"
            )
        if not targets:
            print("no companies with IR RSS URL to ingest")
            return 0

        print(f"▶ ingesting {len(targets)} companies")
        if args.dry_run:
            print("(dry-run) — no writes")

        total_new = 0
        total_hits = 0
        total_tags = 0
        for company in targets:
            assert company.ir_rss_url  # for the type checker
            print(f"▶ {company.symbol:<8} {company.ir_rss_url}")
            try:
                items = await fetch_ir_feed(company.ir_rss_url)
            except Exception as e:
                print(f"  ✗ fetch failed: {e}")
                continue
            print(f"  fetched {len(items)} items")

            for item in items:
                was_new, hit_created, tags_added = ingest_item(
                    db,
                    item,
                    symbol=company.symbol,
                    tag_ids=tag_ids,
                    dry_run=args.dry_run,
                )
                if was_new:
                    total_new += 1
                if hit_created:
                    total_hits += 1
                total_tags += tags_added
                flag = "+" if was_new else "·"
                print(f"  {flag} {item.published_at.date()} {truncate(item.title, 70)}")

            if not args.dry_run:
                db.commit()

        if not args.dry_run:
            db.commit()

    print(
        f"✓ done — new articles: {total_new}, "
        f"trigger hits: {total_hits}, tag links: {total_tags}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
