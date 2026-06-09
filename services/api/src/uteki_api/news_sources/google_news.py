"""Google News RSS per-ticker fetcher.

Search query syntax: ``q=AAPL+OR+%22Apple+Inc%22`` returns headlines
matching either token, scoped via ``hl``/``gl``/``ceid``. Google News
RSS is the most reliable free per-ticker company news source today
(Yahoo Finance's JSON API rate-limits aggressively per-IP and rejects
non-browser TLS fingerprints; the static yahoo_finance.py connector
remains in the codebase as a documented fallback).

RSS shape per <item>:

    <title>Apple Wins X — Reuters</title>
    <link>https://news.google.com/rss/articles/... (redirector)</link>
    <guid>CBM...</guid>
    <pubDate>Sun, 08 Jun 2026 17:01:00 GMT</pubDate>
    <description>...<a href="...">Reuters</a>...</description>
    <source url="https://www.reuters.com">Reuters</source>

The ``<source>`` element gives us a clean publisher name and the title
already embeds it (we strip when ingesting). The <link> URL is a Google
redirect; that's fine — the news_article.url field carries it.
"""

from __future__ import annotations

import asyncio
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

SEARCH_URL = "https://news.google.com/rss/search"

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


@dataclass
class GoogleNewsItem:
    guid: str            # Google News stable per-article ID
    title: str           # publisher suffix already stripped
    publisher: str       # e.g. "Reuters", "TheStreet"
    link: str            # Google redirect URL (rss/articles/...)
    published_at: datetime
    description_html: str


# ─── Public API ──────────────────────────────────────────────────────


def build_query(ticker: str, company_name: str | None = None) -> str:
    """Construct the ``q`` parameter for a ticker+name OR search.

    Examples:
      build_query("AAPL", "Apple Inc.")     → "AAPL OR \"Apple Inc.\""
      build_query("AAPL")                   → "AAPL"
      build_query("BABA", "Alibaba Group")  → "BABA OR \"Alibaba Group\""

    Quoting the company name forces phrase matching, which keeps the
    result set on-topic.
    """
    ticker = ticker.strip().upper()
    if company_name and company_name.strip():
        return f'{ticker} OR "{company_name.strip()}"'
    return ticker


async def fetch_news_for_query(
    query: str,
    *,
    hl: str = "en-US",
    gl: str = "US",
    ceid: str = "US:en",
    user_agent: str = DEFAULT_UA,
    timeout_s: float = 20.0,
) -> list[GoogleNewsItem]:
    """Fetch the Google News RSS feed for an arbitrary search query.

    Returns parsed items in their native feed order (recency-weighted).
    """
    params = {"q": query, "hl": hl, "gl": gl, "ceid": ceid}
    url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"
    raw = await asyncio.to_thread(
        _fetch_sync, url, user_agent=user_agent, timeout_s=timeout_s
    )
    return _parse_rss(raw)


# ─── Sync HTTP (stdlib) ──────────────────────────────────────────────


def _fetch_sync(url: str, *, user_agent: str, timeout_s: float) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return resp.read()


# ─── RSS parsing ─────────────────────────────────────────────────────


# Strip a trailing " - Publisher" or " — Publisher" off the article title.
# Publisher names can contain dashes / dots themselves (e.g. "U.S. News &
# World Report"), so we greedily take the LAST " - " split.
_PUBLISHER_TAIL_RE = re.compile(r"\s+[-–—]\s+([^-–—]{2,80})\s*$")


def _strip_publisher(title: str) -> tuple[str, str | None]:
    m = _PUBLISHER_TAIL_RE.search(title)
    if not m:
        return title.strip(), None
    return title[: m.start()].strip(), m.group(1).strip()


def _parse_rss(xml_bytes: bytes) -> list[GoogleNewsItem]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    channel = root.find("channel")
    if channel is None:
        return []
    out: list[GoogleNewsItem] = []
    for item in channel.findall("item"):
        title_raw = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or link).strip()
        description = (item.findtext("description") or "").strip()
        pub_raw = item.findtext("pubDate")

        # <source url="...">Reuters</source>
        source_el = item.find("source")
        publisher_from_tag = (
            source_el.text.strip() if source_el is not None and source_el.text else None
        )

        if not title_raw or not link:
            continue

        title_clean, publisher_from_title = _strip_publisher(title_raw)
        publisher = publisher_from_tag or publisher_from_title or ""

        published = _parse_rfc822(pub_raw)
        if published is None:
            # Fall back to ingest time so the row at least sorts somewhere.
            published = datetime.now(UTC)

        out.append(
            GoogleNewsItem(
                guid=guid,
                title=title_clean,
                publisher=publisher,
                link=link,
                published_at=published,
                description_html=description,
            )
        )
    return out


def _parse_rfc822(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except (TypeError, ValueError):
        return None


# ─── Relevance helper ────────────────────────────────────────────────


def is_relevant_to(
    item: GoogleNewsItem,
    *,
    ticker: str,
    company_keywords: list[str],
) -> bool:
    """Heuristic: keep if the cleaned title contains either the ticker
    (whole-token uppercase) or any of the human-readable keywords
    (case-insensitive substring).

    The Google News search query already does an OR match on these, so
    in practice almost everything returned passes this filter — but
    it catches the occasional partial match where the engine fell back
    on stemming / synonyms.
    """
    tk = ticker.strip().upper()
    title_up = item.title.upper()
    for token in title_up.replace(",", " ").replace(".", " ").split():
        if token.strip("()[]'\"$:#") == tk:
            return True
    title_lower = item.title.lower()
    for kw in company_keywords:
        kw = kw.strip().lower()
        if kw and kw in title_lower:
            return True
    return False
