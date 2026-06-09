"""Earnings calendar domain.

Tracks expected + delivered earnings events per company. Forms the
basis for the "下次财报 N 天" countdown displayed across the
research desk, watchlist views, and the trg-news-002 ticker rail.

Population strategy is intentionally low-friction: admin manually
enters upcoming dates (10 watchlist tickers × ~4 / year is sustainable
by hand), and a seed script reverse-engineers history + a next-quarter
prediction from the SEC 10-Q / 10-K filings already in news_article.

P9.4 follow-up: when ingest_sec.py pulls a fresh 8-K with Item 2.02
(Results of Operations), auto-flip the matching scheduled event to
status=delivered and record the accession.
"""

from uteki_api.earnings.models import EarningsEvent
from uteki_api.earnings.store import EarningsStore, default_earnings_store

__all__ = ["EarningsEvent", "EarningsStore", "default_earnings_store"]
