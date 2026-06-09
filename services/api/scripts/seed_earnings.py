"""Seed earnings_event from the SEC 10-Q / 10-K filings already in
news_article. For each watchlist company:

  - the 4 most-recent quarterly/annual filings → status=delivered events
  - one predicted next event (90 days after the last filing) → scheduled

The fiscal_period label uses the calendar year + month of the filing
date (e.g. "10-Q · 2026-04"), which is stable across re-runs without
needing company-specific fiscal calendars. Admin can rename to "FY2026
Q1" or whatever convention they prefer later.

Idempotent — the (symbol, fiscal_period) UniqueConstraint on
EarningsEvent + EarningsStore.upsert make re-running safe.

Usage (from services/api/):
    uv run python scripts/seed_earnings.py
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "src"))

from sqlmodel import Session, select  # noqa: E402

from uteki_api.companies.store import default_company_store  # noqa: E402
from uteki_api.core.db import engine, init_db  # noqa: E402
from uteki_api.earnings.store import default_earnings_store  # noqa: E402
from uteki_api.news.models import NewsArticle  # noqa: E402


HISTORICAL_LIMIT = 4


def _label_period(form: str, dt: datetime) -> str:
    return f"{form} · {dt.year}-{dt.month:02d}"


def _historical_filings(
    db: Session, symbol: str, limit: int = HISTORICAL_LIMIT
) -> list[NewsArticle]:
    """Pull recent 10-K / 10-Q filings for ``symbol`` from news_article.

    Title prefix convention from ingest_sec.py is
    ``"<SYM> · <FORM> · …"``; we match on that with a LIKE so we don't
    need a structured form column.
    """
    rows = list(
        db.exec(
            select(NewsArticle)
            .where(NewsArticle.source == "sec_edgar")
            .where(
                NewsArticle.title.like(f"{symbol} · 10-K · %")  # type: ignore[attr-defined]
                | NewsArticle.title.like(f"{symbol} · 10-Q · %")  # type: ignore[attr-defined]
            )
            .order_by(NewsArticle.published_at.desc())  # type: ignore[attr-defined]
            .limit(limit)
        ).all()
    )
    return rows


def _form_from_title(symbol: str, title: str) -> str | None:
    prefix = f"{symbol} · "
    if not title.startswith(prefix):
        return None
    rest = title[len(prefix):]
    form, _, _ = rest.partition(" ·")
    return form.strip() or None


def main() -> int:
    init_db()
    with Session(engine) as db:
        companies = default_company_store.list(db, watch_only=True)
        delivered_count = 0
        predicted_count = 0
        for company in companies:
            filings = _historical_filings(db, company.symbol)
            if not filings:
                print(f"⚠ {company.symbol}: no SEC filings to seed from")
                continue

            print(f"▶ {company.symbol}")
            for article in filings:
                form = _form_from_title(company.symbol, article.title)
                if form is None:
                    continue
                period = _label_period(form, article.published_at)
                ev = default_earnings_store.upsert(
                    db,
                    symbol=company.symbol,
                    fiscal_period=period,
                    expected_date=article.published_at,
                    bmo_amc="DURING",
                    status="delivered",
                    delivered_at=article.published_at,
                    related_accession=article.id,
                    notes=f"seeded from SEC accession {article.id}",
                )
                delivered_count += 1
                print(f"  ✓ delivered {period:<24} {article.published_at.date()}")

            # Next-quarter prediction.
            latest = filings[0]
            predicted_date = latest.published_at + timedelta(days=90)
            # Round to the same hour as the last delivered filing for
            # display consistency, but stamp UTC so timezone math stays sane.
            predicted_date = predicted_date.replace(tzinfo=UTC)
            predicted_form = _form_from_title(company.symbol, latest.title) or "10-Q"
            # Cycle: 10-K → next quarter is 10-Q again; 10-Q → next is 10-Q or 10-K.
            # Simplest model: next is 10-Q unless we just did 3 10-Q in a row,
            # in which case it's a 10-K. Punt on the heuristic — call it 10-Q;
            # admin can switch to 10-K if needed.
            next_form = "10-Q"
            next_period = f"{next_form} · {predicted_date.year}-{predicted_date.month:02d} (predicted)"
            default_earnings_store.upsert(
                db,
                symbol=company.symbol,
                fiscal_period=next_period,
                expected_date=predicted_date,
                bmo_amc="AMC",
                status="scheduled",
                notes=(
                    f"auto-predicted from prior filing {latest.id} "
                    f"({latest.published_at.date()}) + 90 days"
                ),
            )
            predicted_count += 1
            print(f"  + scheduled  {next_period:<32} {predicted_date.date()}")

    print(
        f"\n✓ done — delivered={delivered_count}, predicted={predicted_count}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
