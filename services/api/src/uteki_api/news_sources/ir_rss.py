"""IR newsroom RSS / Atom fetcher.

Reads a per-company ``company.ir_rss_url`` and returns parsed items.
Targets the "fastest free signal" tier — most companies' Investor
Relations / newsroom feeds publish a release within seconds of it
going live, well before it hits SEC EDGAR (which lags 5-30 minutes
on the corresponding 8-K Item 2.02 filing).

Reality check from the P10.3.0 probe:

  ✓ AAPL    apple.com/newsroom/rss-feed.rss        (Atom)
  ✓ NVDA    blogs.nvidia.com/feed/                 (RSS 2.0)
  ✓ GOOGL   blog.google/rss/                       (RSS 2.0)
  ✗ MSFT    news.microsoft.com/feed/               403 anti-bot
  ✗ TSLA    no public RSS                          —
  ✗ TSM     pr.tsmc.com 403                        —

So this layer covers ~50% of a typical US-tech watchlist out of the
box. The other half stays on SEC EDGAR + Google News.

This module is intentionally minimal — one HTTP call, one parser that
handles both Atom and RSS 2.0 (the two formats real IR feeds use).
Same urllib-over-asyncio trick as google_news.py to dodge TLS
fingerprinting that bites httpx for some hosts.
"""

from __future__ import annotations

import asyncio
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

ATOM_NS = "http://www.w3.org/2005/Atom"
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class IRNewsItem:
    guid: str            # canonical link or feed-provided id
    title: str
    summary: str        # plain text (HTML stripped)
    link: str
    published_at: datetime


async def fetch_ir_feed(
    url: str,
    *,
    user_agent: str = DEFAULT_UA,
    timeout_s: float = 20.0,
) -> list[IRNewsItem]:
    """Pull and parse an IR newsroom feed. Returns [] on empty / parse
    failure (caller decides whether that's an error)."""
    raw = await asyncio.to_thread(
        _fetch_sync, url, user_agent=user_agent, timeout_s=timeout_s
    )
    return _parse(raw)


# ─── Internals ───────────────────────────────────────────────────────


def _fetch_sync(url: str, *, user_agent: str, timeout_s: float) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/atom+xml, application/rss+xml, application/xml;q=0.9, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return resp.read()


def _strip_html(s: str) -> str:
    return _TAG_RE.sub("", s).strip() if s else ""


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    # Try ISO 8601 first (Atom / modern RSS).
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        pass
    # RFC 822 (classic RSS pubDate).
    try:
        dt = parsedate_to_datetime(raw)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _parse(xml_bytes: bytes) -> list[IRNewsItem]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    # Atom: <feed><entry>...</entry></feed>
    if root.tag == f"{{{ATOM_NS}}}feed":
        return _parse_atom(root)
    # RSS 2.0: <rss><channel><item>...</item></channel></rss>
    channel = root.find("channel")
    if channel is not None:
        return _parse_rss(channel)
    return []


def _parse_atom(root: ET.Element) -> list[IRNewsItem]:
    def q(name: str) -> str:
        return f"{{{ATOM_NS}}}{name}"

    out: list[IRNewsItem] = []
    for entry in root.findall(q("entry")):
        title = (entry.findtext(q("title")) or "").strip()
        # Atom <link rel="alternate"> is the canonical URL.
        link = ""
        for link_el in entry.findall(q("link")):
            rel = link_el.get("rel", "alternate")
            if rel == "alternate" and link_el.get("href"):
                link = link_el.get("href", "")
                break
        guid = (entry.findtext(q("id")) or link).strip()
        # Atom puts the body in <content> (or sometimes <summary>).
        body = entry.findtext(q("content")) or entry.findtext(q("summary")) or ""
        published = _parse_dt(
            entry.findtext(q("published")) or entry.findtext(q("updated"))
        )
        if not title or not link or published is None:
            continue
        out.append(
            IRNewsItem(
                guid=guid,
                title=title,
                summary=_strip_html(body)[:2000],
                link=link,
                published_at=published,
            )
        )
    return out


def _parse_rss(channel: ET.Element) -> list[IRNewsItem]:
    out: list[IRNewsItem] = []
    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or link).strip()
        description = item.findtext("description") or ""
        published = _parse_dt(item.findtext("pubDate"))
        if not title or not link or published is None:
            continue
        out.append(
            IRNewsItem(
                guid=guid,
                title=title,
                summary=_strip_html(description)[:2000],
                link=link,
                published_at=published,
            )
        )
    return out
