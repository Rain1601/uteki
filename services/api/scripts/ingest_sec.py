"""Pull SEC EDGAR filings for every watchlist company with a CIK.

Form → trigger / event-tag mapping:

    8-K   → trg-event-003       事件 = per items_desc (m_and_a / earnings /
                                  regulation / guidance — derived from
                                  Item codes; see ITEM_TO_EVENT_TAG)
    10-Q  → trg-earnings-002    事件 = earnings, 重要度 = high
    10-K  → trg-earnings-002    事件 = earnings, 重要度 = critical

All filings additionally get 类别 = equities + a symbols field listing
the company's ticker.

Idempotent — articles use ``accession`` as primary key, so re-running
just no-ops on already-ingested filings. Trigger_hits and ArticleTag
links dedup before insert.

Usage (from services/api/):
    export UTEKI_SEC_USER_AGENT="uteki research <your@email>"
    uv run python scripts/ingest_sec.py
    uv run python scripts/ingest_sec.py --symbol AAPL  # just one
    uv run python scripts/ingest_sec.py --dry-run     # no writes
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "src"))

from sqlmodel import Session, select  # noqa: E402

from uteki_api.companies.store import default_company_store  # noqa: E402
from uteki_api.core.config import settings  # noqa: E402
from uteki_api.core.db import engine, init_db  # noqa: E402
from uteki_api.news.models import (  # noqa: E402
    ArticleTag,
    NewsArticle,
    Tag,
    TagGroup,
    TriggerHit,
)
from uteki_api.news.store import default_news_store  # noqa: E402
from uteki_api.news_sources.sec_edgar import (  # noqa: E402
    Filing,
    clean_summary,
    fetch_filings,
)


# Trigger binding per form. Note: 8-K material events all flow to
# trg-event-003; earnings-flavored 8-K items still go there (the 8-K is
# the legal event), with 10-Q/10-K landing on the dedicated earnings
# trigger. If you want 8-K Item 2.02 to also fire trg-earnings-002 we
# can dual-bind in a follow-up.
# All company-specific SEC filings flow into the unified company-stream
# trigger (P8.5 IA refactor). The earlier per-form triggers
# (trg-event-003 / trg-earnings-002) became filtered views of this one
# stream — the 事件 tag (earnings / regulation / m_and_a / guidance,
# derived from 8-K Item codes) carries the discrimination instead.
TRIGGER_FOR_FORM: dict[str, str] = {
    "8-K": "trg-news-002",
    "10-Q": "trg-news-002",
    "10-K": "trg-news-002",
}

IMPORTANCE_FOR_FORM: dict[str, str] = {
    "8-K": "high",
    "10-Q": "high",
    "10-K": "critical",
}


def _normalize_form(form: str) -> str:
    """Collapse amended variants (10-K/A, 10-Q/A, 8-K/A) onto their base form."""
    return form.split("/", 1)[0].strip()


# ─── Tag lookup ──────────────────────────────────────────────────────


def build_tag_lookup(db: Session) -> dict[str, str]:
    """Return ``<group_name>:<tag_name>`` → tag_id map."""
    out: dict[str, str] = {}
    for group in db.exec(select(TagGroup)).all():
        for tag in db.exec(select(Tag).where(Tag.group_id == group.id)).all():
            out[f"{group.name}:{tag.name}"] = tag.id
    return out


def tags_for_filing(
    filing: Filing,
    tag_ids: dict[str, str],
) -> list[str]:
    """Return the tag IDs to attach to a filing's NewsArticle."""
    out: list[str] = []
    base_form = _normalize_form(filing.form)
    importance = IMPORTANCE_FOR_FORM.get(base_form)
    if importance:
        key = f"重要度:{importance}"
        if key in tag_ids:
            out.append(tag_ids[key])
    if "类别:equities" in tag_ids:
        out.append(tag_ids["类别:equities"])
    # 10-Q / 10-K are always earnings; 8-K gets a list from item codes.
    if base_form in {"10-Q", "10-K"}:
        if "事件:earnings" in tag_ids:
            out.append(tag_ids["事件:earnings"])
    else:
        for ev in filing.event_tags:
            key = f"事件:{ev}"
            if key in tag_ids:
                out.append(tag_ids[key])
    # Dedup, preserve order.
    seen: list[str] = []
    for t in out:
        if t not in seen:
            seen.append(t)
    return seen


# ─── Article ingestion ───────────────────────────────────────────────


def make_title(filing: Filing, symbol: str) -> str:
    if filing.items:
        items = ", ".join(filing.items)
        return f"{symbol} · {filing.form} · Items {items}"
    return f"{symbol} · {filing.form} · {filing.title.replace(filing.form, '').replace('-', '').strip()}"


def ingest_filing(
    db: Session,
    filing: Filing,
    *,
    symbol: str,
    tag_ids_for_taxonomy: dict[str, str],
    dry_run: bool,
) -> tuple[bool, bool, int]:
    """Insert / link the filing. Returns (was_new, hit_created, tags_added)."""
    article_id = filing.accession  # PK across re-runs.
    existing = db.get(NewsArticle, article_id)
    was_new = existing is None
    if was_new and not dry_run:
        summary_plain = clean_summary(filing.summary_html)
        article = NewsArticle(
            id=article_id,
            title=make_title(filing, symbol),
            title_zh=None,
            summary=summary_plain[:2000],
            summary_zh=None,
            content=summary_plain,
            content_zh=None,
            url=filing.url,
            author="SEC EDGAR",
            source="sec_edgar",
            symbols=symbol,
            published_at=filing.filed_at,
            ingested_at=datetime.now(UTC),
            ai_analysis_status="pending",
        )
        db.add(article)

    # Tag links.
    desired_tags = tags_for_filing(filing, tag_ids_for_taxonomy)
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
    trigger_id = TRIGGER_FOR_FORM.get(_normalize_form(filing.form))
    hit_created = False
    if trigger_id and not dry_run:
        exists = db.exec(
            select(TriggerHit).where(
                TriggerHit.trigger_id == trigger_id,
                TriggerHit.article_id == article_id,
            )
        ).first()
        if exists is None:
            db.add(
                TriggerHit(
                    id=uuid.uuid4().hex[:12],
                    trigger_id=trigger_id,
                    article_id=article_id,
                    fired_at=filing.filed_at,
                )
            )
            hit_created = True

    return was_new, hit_created, tags_added


# ─── Driver ──────────────────────────────────────────────────────────


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", help="Only ingest this ticker.")
    parser.add_argument(
        "--limit-per-form",
        type=int,
        default=40,
        help="Number of filings per (CIK, form). Default 40.",
    )
    parser.add_argument(
        "--forms",
        nargs="+",
        default=["8-K", "10-Q", "10-K"],
        help="Which forms to pull.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    user_agent = settings.sec_user_agent
    if not user_agent:
        print(
            "ERR: UTEKI_SEC_USER_AGENT not set. Required by SEC Fair Access.\n"
            "    Set it in services/api/.env, e.g.:\n"
            "    UTEKI_SEC_USER_AGENT='uteki research your@email.com'",
            file=sys.stderr,
        )
        return 2

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
        targets = [c for c in companies if c.cik]
        skipped_no_cik = [c.symbol for c in companies if not c.cik]
        if skipped_no_cik:
            print(f"⚠ skipping {len(skipped_no_cik)} companies without CIK: "
                  f"{', '.join(skipped_no_cik)}")
        if not targets:
            print("no companies with CIK to ingest")
            return 0

        print(f"▶ ingesting {len(targets)} companies × {len(args.forms)} forms")
        if args.dry_run:
            print("(dry-run) — no writes")

        total_new = 0
        total_hits = 0
        total_tags = 0
        for company in targets:
            print(f"▶ {company.symbol:<8} CIK={company.cik}")
            try:
                filings = await fetch_filings(
                    company.cik,
                    forms=args.forms,
                    limit_per_form=args.limit_per_form,
                    user_agent=user_agent,
                )
            except Exception as e:
                print(f"  ✗ fetch failed: {e}")
                continue

            for filing in filings:
                was_new, hit_created, tags_added = ingest_filing(
                    db,
                    filing,
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
                    f"  {flag} {filing.form:6} {filing.filed_at.date()} "
                    f"{filing.accession}  items={filing.items}"
                )

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
