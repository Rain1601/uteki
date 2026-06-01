"""网页正文抽取工具 — Phase C.3b real implementation.

httpx fetch + BeautifulSoup article-mode extraction. Closes the citation
chain: news_search / web_search returns a URL → web_extract fetches it
and yields clean text + a published_at the SourceCatalog can rank or
reject (as_of cutoff). No new direct dep — bs4 + lxml + httpx are
already pulled transitively.

Strategy (article-extraction without trafilatura):
1. Fetch HTML via httpx (10s timeout, modern UA).
2. BeautifulSoup parse (lxml backend).
3. Strip <script>, <style>, <noscript>, <iframe>, <nav>, <header>,
   <footer>, <aside>, common ad/cookie banners.
4. Pick best candidate body: <article> > <main> > the longest <div>
   that holds many <p>.
5. Title via <title>, falling back to first <h1>, then og:title meta.
6. published_at via the same meta-tag fallback chain news_search uses
   (article:published_time → og:article:published_time → schema.org
   NewsArticle datepublished).
7. Normalize whitespace, truncate to MAX_BODY_CHARS so LLM tool-result
   payload stays bounded.

When extraction fails (HTTP error, no body candidate) we degrade to mock
output so the agent's tool-use loop keeps moving. The error path is
surfaced via ToolResult.summary so the run trace makes it obvious.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from uteki_api.core.config import settings
from uteki_api.tools.base import Tool, ToolResult

# Cap the LLM-visible body to keep tool_result payloads small. Most useful
# article content fits in 5000 chars; longer payloads get truncated with a
# marker so the LLM knows there's more.
MAX_BODY_CHARS = 5000
MAX_TITLE_CHARS = 200

_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (uteki-research-agent) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_WS_RE = re.compile(r"[ \t ]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")

# Tags that are pure noise for article extraction.
_NOISE_TAGS = ("script", "style", "noscript", "iframe", "nav", "header", "footer", "aside")
# Common ad / cookie / share-widget class snippets — best-effort drop.
_NOISE_SELECTORS = (
    ".cookie", ".cookies", ".ads", ".advertisement", ".share-buttons",
    ".social", ".newsletter", ".paywall", "[role=banner]", "[role=navigation]",
)


def _extract_meta_published_at(soup: Any) -> str | None:
    """Pull a publication timestamp out of the document head. Same priority
    order news_search uses for Google CSE pagemap, applied to live HTML."""
    head = soup.find("head")
    if head is None:
        return None

    # OpenGraph + article meta
    for key in (
        "article:published_time",
        "og:article:published_time",
        "article:modified_time",
        "datepublished",
        "publishdate",
        "pubdate",
    ):
        # check both name= and property=
        for attr in ("property", "name"):
            tag = head.find("meta", {attr: key})
            if tag and tag.get("content"):
                return str(tag["content"])
    # schema.org JSON-LD shortcut: find a NewsArticle / Article datePublished
    for script in head.find_all("script", {"type": "application/ld+json"}):
        body = script.string or script.text or ""
        m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', body)
        if m:
            return m.group(1)
    # <time datetime="...">
    time_tag = soup.find("time", attrs={"datetime": True})
    if time_tag and time_tag.get("datetime"):
        return str(time_tag["datetime"])
    return None


def _extract_title(soup: Any) -> str:
    head = soup.find("head")
    if head is not None:
        # Prefer og:title (usually cleaner than browser <title>).
        og = head.find("meta", {"property": "og:title"})
        if og and og.get("content"):
            return str(og["content"])[:MAX_TITLE_CHARS]
        if head.title and head.title.string:
            return head.title.string.strip()[:MAX_TITLE_CHARS]
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)[:MAX_TITLE_CHARS]
    return ""


def _strip_noise(soup: Any) -> None:
    """In-place: remove non-content tags + selectors."""
    for tag in soup.find_all(_NOISE_TAGS):
        tag.decompose()
    for sel in _NOISE_SELECTORS:
        for tag in soup.select(sel):
            tag.decompose()


def _pick_body(soup: Any) -> Any | None:
    """Pick the best candidate container for article body."""
    # 1) <article> if present and substantive
    article = soup.find("article")
    if article and len(article.get_text(strip=True)) > 200:
        return article
    # 2) <main>
    main = soup.find("main")
    if main and len(main.get_text(strip=True)) > 200:
        return main
    # 3) Longest <div> by paragraph count + text length
    best = None
    best_score = 0
    for div in soup.find_all("div"):
        paras = div.find_all("p")
        if len(paras) < 3:
            continue
        score = sum(len(p.get_text(strip=True)) for p in paras)
        if score > best_score:
            best = div
            best_score = score
    if best and best_score > 300:
        return best
    # 4) Fallback: body
    return soup.body


def _extract_text(container: Any) -> str:
    """Get cleaned text from a container, preserving paragraph breaks."""
    if container is None:
        return ""
    parts: list[str] = []
    for p in container.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote"]):
        text = p.get_text(separator=" ", strip=True)
        if text:
            # H tags get a # prefix so the LLM sees structure
            tag = p.name
            if tag in ("h1", "h2", "h3", "h4"):
                level = "#" * int(tag[1])
                parts.append(f"{level} {text}")
            elif tag == "li":
                parts.append(f"- {text}")
            elif tag == "blockquote":
                parts.append(f"> {text}")
            else:
                parts.append(text)
    raw = "\n\n".join(parts)
    # Collapse internal whitespace
    raw = _WS_RE.sub(" ", raw)
    raw = _BLANK_LINES_RE.sub("\n\n", raw)
    return raw.strip()


async def _fetch_and_parse(url: str) -> dict[str, Any]:
    """Fetch + parse a URL. Returns dict with title / text / published_at /
    publisher / fetched_at. Raises on HTTP error."""
    async with httpx.AsyncClient(
        timeout=10.0, headers=_FETCH_HEADERS, follow_redirects=True
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        html = resp.text

    # Lazy-import bs4 so a missing dep at import time doesn't crash the tool
    # registry (defensive — bs4 is pinned but ymv).
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    title = _extract_title(soup)
    published_at = _extract_meta_published_at(soup)
    _strip_noise(soup)
    body_container = _pick_body(soup)
    text = _extract_text(body_container)
    if len(text) > MAX_BODY_CHARS:
        text = text[:MAX_BODY_CHARS] + f"\n\n…[truncated, full length {len(text)} chars]"

    return {
        "url": url,
        "title": title,
        "text": text,
        "published_at": published_at,
        "publisher": urlparse(url).netloc,
        "fetched_at": datetime.now(UTC).isoformat(),
    }


def _mock_result(url: str) -> dict[str, Any]:
    """Deterministic placeholder when real fetch fails or use_mock_data."""
    return {
        "url": url,
        "title": f"[mock] 网页标题 - {url[:80]}",
        "text": (
            f"这是一段从 {url} 抽取出的占位正文。\n\n"
            "真实模式将通过 httpx + BeautifulSoup 拉取网页并清洗正文。"
        ),
        "published_at": None,
        "publisher": urlparse(url).netloc or "mock-web-extract",
        "fetched_at": datetime.now(UTC).isoformat(),
    }


class WebExtractTool(Tool):
    name = "web_extract"
    description = (
        "给定 URL，抓取网页并抽取干净的正文（移除导航 / 广告 / 脚本），"
        "返回 title / text / published_at。"
        "用于 news_search / web_search 拿到 URL 后深度阅读。"
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "format": "uri",
                "description": "目标网页 URL（http/https）",
            },
        },
        "required": ["url"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        url = kwargs.get("url", "").strip()
        if not url:
            return ToolResult(ok=False, error="url is required")
        if not (url.startswith("http://") or url.startswith("https://")):
            return ToolResult(ok=False, error="url must start with http:// or https://")

        if settings.use_mock_data:
            data = _mock_result(url)
            return self._tool_result(data, confidence="low", note="mock fixture")

        try:
            data = await _fetch_and_parse(url)
        except (httpx.HTTPError, TimeoutError) as e:
            data = _mock_result(url)
            return self._tool_result(
                data, confidence="low",
                note=f"fetch failed ({type(e).__name__}); fixture fallback",
            )
        except Exception as e:  # noqa: BLE001 — any parse failure → degrade
            data = _mock_result(url)
            return self._tool_result(
                data, confidence="low",
                note=f"parse failed ({type(e).__name__}: {e}); fixture fallback",
            )

        if not data["text"]:
            return self._tool_result(
                data, confidence="low",
                note="fetched OK but no extractable body",
            )
        return self._tool_result(data, confidence="medium")

    @staticmethod
    def _tool_result(
        data: dict[str, Any], confidence: str, note: str = ""
    ) -> ToolResult:
        summary = f"抽取 {len(data['text'])} 字符正文 from {data['publisher']}"
        if note:
            summary += f" · {note}"
        return ToolResult(
            ok=True,
            summary=summary,
            data=data,
            sources=[
                {
                    "key": f"web_extract:{data['url']}",
                    "value": {
                        "url": data["url"],
                        "title": data["title"],
                        "publisher": data["publisher"],
                    },
                    "source_type": "web_extract",
                    "source_url": data["url"],
                    "publisher": data["publisher"],
                    "published_at": data.get("published_at"),
                    "fetched_at": data.get("fetched_at"),
                    "confidence": confidence,
                    "excerpt": data["text"][:300],
                }
            ],
        )
