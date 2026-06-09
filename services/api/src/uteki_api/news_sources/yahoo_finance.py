"""Yahoo Finance per-ticker news fetcher.

Uses the unofficial-but-stable ``query1.finance.yahoo.com/v1/finance/search``
endpoint. Returns per-article metadata with ``relatedTickers`` so we can
tell when Yahoo is being too generous with cross-sector tagging
(e.g. tagging a Nedap partnership story with AAPL just because both sit
in the same industry node).

**TLS-fingerprint caveat**: Yahoo's gateway 429s anything that looks
like Python's httpx (it ships a recognizable JA3/JA4 signature). The
stdlib ``urllib.request`` uses a different TLS handshake that Yahoo
lets through, so we use that under ``asyncio.to_thread`` instead of
httpx. Curl-based ingestion would also work; this keeps things zero-
dependency. Don't "upgrade" this to httpx without testing — it will
start failing in production.

This is intentionally a thin connector — relevance filtering lives in
the ingest script, not here, because the heuristic depends on the
Company row (we need the human-readable name as well as the ticker).
"""

from __future__ import annotations

import asyncio
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime

# query1 and query2 are alternating clusters; both serve the same data
# but rate-limit independently. We use query1 (less hammered by client
# libraries that default to query2).
SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"

# Yahoo blocks empty / obviously-bot UAs. A standard browser UA is fine.
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


@dataclass
class YahooNewsItem:
    uuid: str            # Yahoo's stable per-article ID
    title: str
    publisher: str       # e.g. "Reuters", "TheStreet"
    link: str            # finance.yahoo.com permalink
    published_at: datetime
    related_tickers: list[str]
    item_type: str       # "STORY" | "VIDEO" | "BUNDLE" | ...


def _fetch_sync(url: str, *, user_agent: str, timeout_s: float) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://finance.yahoo.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return resp.read()


async def fetch_ticker_news(
    ticker: str,
    *,
    count: int = 20,
    user_agent: str = DEFAULT_UA,
    timeout_s: float = 20.0,
) -> list[YahooNewsItem]:
    """Fetch up to ``count`` recent news items for ``ticker``.

    Doesn't filter or score — caller decides relevance. Returns items in
    Yahoo's native order (roughly recency-weighted).
    """
    params = {
        "q": ticker.strip(),
        "newsCount": str(count),
        "quotesCount": "0",
        "enableFuzzyQuery": "false",
        "enableEnhancedTrivialQuery": "true",
    }
    url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"
    raw = await asyncio.to_thread(
        _fetch_sync, url, user_agent=user_agent, timeout_s=timeout_s
    )
    body = json.loads(raw.decode("utf-8"))
    out: list[YahooNewsItem] = []
    for entry in body.get("news", []) or []:
        uuid = entry.get("uuid")
        title = entry.get("title")
        if not uuid or not title:
            continue
        ts = entry.get("providerPublishTime")
        try:
            published = datetime.fromtimestamp(int(ts), tz=UTC)
        except (TypeError, ValueError):
            continue
        out.append(
            YahooNewsItem(
                uuid=uuid,
                title=title.strip(),
                publisher=(entry.get("publisher") or "").strip(),
                link=entry.get("link") or "",
                published_at=published,
                related_tickers=list(entry.get("relatedTickers") or []),
                item_type=entry.get("type") or "STORY",
            )
        )
    return out


# ─── Relevance helper (heuristic) ────────────────────────────────────


def is_relevant_to(
    item: YahooNewsItem,
    *,
    ticker: str,
    company_keywords: list[str],
) -> bool:
    """Heuristic: keep when Yahoo's strongest signal lines up with the
    target ticker.

    Pass when any of:

    1. The article title contains ``ticker`` (uppercase whole-token).
    2. The title contains any element of ``company_keywords`` (case-
       insensitive, substring match) — caller supplies "Apple", "Nvidia",
       etc. derived from the canonical name.
    3. Yahoo's ``relatedTickers[0]`` equals ``ticker`` — Yahoo's primary
       tag is the most trustworthy of the three.

    Returns False on everything else, which is what kills the "Nedap
    partnership with Albert Heijn" noise where AAPL is only a tertiary
    sector tag.
    """
    title = item.title
    title_up = title.upper()
    tk = ticker.strip().upper()

    # 1) Ticker explicit in title (whole-token, so "AAPLE" doesn't pass).
    for token in title_up.replace(",", " ").replace(".", " ").split():
        if token.strip("()[]'\"$:#") == tk:
            return True

    # 2) Any human-readable company keyword in the title.
    title_lower = title.lower()
    for kw in company_keywords:
        kw = kw.strip().lower()
        if kw and kw in title_lower:
            return True

    # 3) Yahoo's primary tag.
    if item.related_tickers and item.related_tickers[0].strip().upper() == tk:
        return True

    return False
