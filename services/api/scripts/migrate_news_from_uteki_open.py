"""One-shot migration: pull CNBC news from uteki.open's SQLite into uteki's
news_article + article_tag + trigger_hit tables.

Source:  /Users/rain/PycharmProjects/uteki.open/backend/data/uteki.db
         table news_articles, filtered WHERE source = 'cnbc_jeff_cox'
         (~423 rows, 2024-04 → 2026-02)
Target:  this project's news_article / article_tag / trigger_hit, all
         bound to trigger_id="trg-news-001".

Idempotent — articles are upserted by primary key (the source's
hash-based id); article_tag / trigger_hit are skipped if already there.

Usage (from services/api/):
    uv run python scripts/migrate_news_from_uteki_open.py [--source-db PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "src"))

from sqlmodel import Session, select  # noqa: E402

from uteki_api.core.db import engine, init_db  # noqa: E402
from uteki_api.news.models import (  # noqa: E402
    ArticleTag,
    NewsArticle,
    Tag,
    TagGroup,
    TriggerHit,
)


DEFAULT_SOURCE_DB = (
    "/Users/rain/PycharmProjects/uteki.open/backend/data/uteki.db"
)
TARGET_TRIGGER_ID = "trg-news-001"
NORMALIZED_SOURCE = "cnbc"

# Category mapping. CNBC's free-text "category" → our taxonomy tag name.
EQUITIES_CATEGORIES = {"stocks", "Playbooks", "Pro Talks"}
# Everything else (finance, Economy, Markets, The Fed, Macro Insights for
# Investing, Asia Markets, Politics, Banks, etc.) lands under "macro".


def normalize_impact(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip().lower()
    if raw in {"positive", "bullish"}:
        return "positive"
    if raw in {"negative", "bearish"}:
        return "negative"
    if raw == "neutral":
        return "neutral"
    return None


def normalize_importance(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip().lower()
    if raw in {"critical", "high", "medium", "low"}:
        return raw
    return None


def normalize_category(raw: str | None) -> str | None:
    if not raw:
        return None
    if raw in EQUITIES_CATEGORIES:
        return "equities"
    return "macro"


def parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    # SQLite stores as ISO-ish without timezone.
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None


def first_nonempty(*candidates: str | None, fallback: str = "") -> str:
    for c in candidates:
        if c and c.strip():
            return c.strip()
    return fallback


def build_tag_lookup(db: Session) -> dict[str, str]:
    """Map ``<group_name>:<tag_name>`` → tag_id for taxonomy already seeded
    by ``seed_news_demo.py``. Missing entries are warned (caller decides)."""
    out: dict[str, str] = {}
    for group in db.exec(select(TagGroup)).all():
        for tag in db.exec(select(Tag).where(Tag.group_id == group.id)).all():
            out[f"{group.name}:{tag.name}"] = tag.id
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", default=DEFAULT_SOURCE_DB)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count + report what would happen, write nothing.",
    )
    args = parser.parse_args(argv)

    src_path = Path(args.source_db)
    if not src_path.exists():
        print(f"ERR: source DB not found at {src_path}", file=sys.stderr)
        return 2

    print(f"▶ ensuring target tables exist")
    init_db()

    print(f"▶ opening source DB: {src_path}")
    src = sqlite3.connect(str(src_path))
    src.row_factory = sqlite3.Row

    rows = list(
        src.execute(
            """
            SELECT id, title, title_zh, content, content_zh,
                   url, author, symbols, published_at, scraped_at,
                   summary_keypoints, summary_keypoints_zh,
                   ai_impact, ai_analysis, ai_analysis_status, ai_analyzed_at,
                   ai_feedback_like_count, ai_feedback_dislike_count,
                   importance_level, category
            FROM news_articles
            WHERE source = 'cnbc_jeff_cox'
            ORDER BY published_at DESC
            """
        )
    )
    src.close()

    print(f"▶ source rows: {len(rows)}")
    if args.dry_run:
        print("(dry-run) — no writes")

    inserted = 0
    skipped = 0
    tagged = 0
    hit_added = 0

    with Session(engine) as db:
        tags = build_tag_lookup(db)
        # Resolve well-known tag ids; if seed script wasn't run, fail loud.
        required = {
            "重要度:critical", "重要度:high", "重要度:medium", "重要度:low",
            "类别:macro", "类别:equities",
        }
        missing = required - tags.keys()
        if missing:
            print(
                f"ERR: taxonomy missing tags: {missing}\n"
                "    Run scripts/seed_news_demo.py first.",
                file=sys.stderr,
            )
            return 3

        for row in rows:
            existing = db.get(NewsArticle, row["id"])
            if existing is None:
                published = parse_dt(row["published_at"])
                if published is None:
                    skipped += 1
                    continue
                ingested = parse_dt(row["scraped_at"]) or published
                article = NewsArticle(
                    id=row["id"],
                    title=row["title"] or "",
                    title_zh=row["title_zh"],
                    summary=first_nonempty(
                        row["summary_keypoints"],
                        (row["content"] or "")[:200],
                    ),
                    summary_zh=first_nonempty(
                        row["summary_keypoints_zh"],
                        (row["content_zh"] or "")[:200],
                    )
                    or None,
                    content=row["content"] or "",
                    content_zh=row["content_zh"],
                    url=row["url"] or "",
                    author=row["author"],
                    source=NORMALIZED_SOURCE,
                    symbols=row["symbols"] or "",
                    published_at=published,
                    ingested_at=ingested,
                    impact=normalize_impact(row["ai_impact"]),
                    ai_analysis=row["ai_analysis"],
                    ai_analysis_status=row["ai_analysis_status"] or "pending",
                    ai_analyzed_at=parse_dt(row["ai_analyzed_at"]),
                    like_count=int(row["ai_feedback_like_count"] or 0),
                    dislike_count=int(row["ai_feedback_dislike_count"] or 0),
                )
                if not args.dry_run:
                    db.add(article)
                inserted += 1
            else:
                # Don't clobber existing row — user may have voted on it
                # locally already. Just refresh tag links + trigger hit.
                pass

            # Tag assignment.
            applied: list[str] = []
            imp = normalize_importance(row["importance_level"])
            if imp:
                applied.append(tags[f"重要度:{imp}"])
            cat = normalize_category(row["category"])
            if cat:
                applied.append(tags[f"类别:{cat}"])

            if applied and not args.dry_run:
                # Idempotent re-bind: skip pairs that already exist.
                already = {
                    link.tag_id
                    for link in db.exec(
                        select(ArticleTag).where(
                            ArticleTag.article_id == row["id"]
                        )
                    ).all()
                }
                for tag_id in applied:
                    if tag_id in already:
                        continue
                    db.add(ArticleTag(article_id=row["id"], tag_id=tag_id))
                    tagged += 1

            # Trigger hit.
            if not args.dry_run:
                existing_hit = db.exec(
                    select(TriggerHit).where(
                        TriggerHit.trigger_id == TARGET_TRIGGER_ID,
                        TriggerHit.article_id == row["id"],
                    )
                ).first()
                if existing_hit is None:
                    import uuid as _uuid

                    db.add(
                        TriggerHit(
                            id=_uuid.uuid4().hex[:12],
                            trigger_id=TARGET_TRIGGER_ID,
                            article_id=row["id"],
                            fired_at=parse_dt(row["published_at"]) or datetime.now(UTC),
                        )
                    )
                    hit_added += 1

            # Commit per batch to keep memory bounded; SQLite small enough to
            # not really matter, but cleaner for failure recovery.
            if (inserted + skipped) % 100 == 0 and not args.dry_run:
                db.commit()
                print(f"  · checkpoint: inserted={inserted} skipped={skipped}")

        if not args.dry_run:
            db.commit()

    print(
        f"✓ done — inserted={inserted}, skipped={skipped}, "
        f"tagged={tagged}, hits={hit_added}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
