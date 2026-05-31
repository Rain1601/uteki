"""News search tool.

Real runs use the same shape as uteki.open: Google Custom Search when keys are
configured, with DDGS as a no-key fallback. Mock/test runs keep fixture news.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from uteki_api.core.config import settings
from uteki_api.tools.base import Tool, ToolResult


def _mock_items(query: str, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "title": f"[mock] {query} 相关新闻 #{i + 1}",
            "summary": f"这是一条关于 {query} 的占位新闻摘要。",
            "source": "mock-news",
            "url": f"https://example.com/news/{i + 1}",
        }
        for i in range(limit)
    ]


async def _google_cse_search(query: str, limit: int) -> list[dict[str, Any]]:
    if not settings.google_search_api_key or not settings.google_search_engine_id:
        return []
    params = {
        "key": settings.google_search_api_key,
        "cx": settings.google_search_engine_id,
        "q": query,
        "num": min(limit, 10),
        "dateRestrict": "m6",
    }
    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.get("https://www.googleapis.com/customsearch/v1", params=params)
        resp.raise_for_status()
        payload = resp.json()
    items: list[dict[str, Any]] = []
    for raw in payload.get("items", [])[:limit]:
        url = raw.get("link", "")
        source = urlparse(url).netloc or "google-cse"
        items.append(
            {
                "title": raw.get("title", ""),
                "summary": raw.get("snippet", ""),
                "source": source,
                "url": url,
                "published_at": _published_at_from_pagemap(raw),
                "provider": "google_cse",
            }
        )
    return items


def _published_at_from_pagemap(item: dict[str, Any]) -> str | None:
    pagemap = item.get("pagemap") or {}
    metatags = pagemap.get("metatags") or []
    if metatags and isinstance(metatags, list):
        first = metatags[0] or {}
        for key in (
            "article:published_time",
            "og:article:published_time",
            "article:modified_time",
            "datepublished",
            "publishdate",
        ):
            value = first.get(key)
            if value:
                return str(value)
    for key in ("newsarticle", "article", "blogposting"):
        records = pagemap.get(key) or []
        if records and isinstance(records, list):
            value = (records[0] or {}).get("datepublished") or (records[0] or {}).get(
                "datemodified"
            )
            if value:
                return str(value)
    return None


async def _ddgs_search(query: str, limit: int) -> list[dict[str, Any]]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _ddgs_search_sync, query, limit)


def _ddgs_search_sync(query: str, limit: int) -> list[dict[str, Any]]:
    from ddgs import DDGS

    client = DDGS()
    raw_items = client.news(query, max_results=limit) or client.text(query, max_results=limit)
    items: list[dict[str, Any]] = []
    for raw in raw_items[:limit]:
        url = raw.get("url") or raw.get("href") or ""
        source = raw.get("source") or urlparse(url).netloc or "ddgs"
        items.append(
            {
                "title": raw.get("title", ""),
                "summary": raw.get("body") or raw.get("snippet") or "",
                "source": source,
                "url": url,
                "published_at": raw.get("date"),
                "provider": "ddgs",
            }
        )
    return items


class NewsSearchTool(Tool):
    name = "news_search"
    description = "搜索与某关键词或标的相关的最新新闻（标题 + 摘要 + 来源）。"
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词，例如公司名、行业、事件"},
            "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
        },
        "required": ["query"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "")
        limit = int(kwargs.get("limit", 5))
        if not query:
            return ToolResult(ok=False, error="query is required")
        limit = max(1, min(limit, 20))

        if settings.use_mock_data:
            return self._items_result(query, _mock_items(query, limit), confidence="low")

        errors: list[str] = []
        for searcher in (_google_cse_search, _ddgs_search):
            try:
                items = await searcher(query, limit)
            except Exception as e:  # noqa: BLE001 - search provider failure should degrade
                errors.append(f"{searcher.__name__}: {e}")
                continue
            if items:
                return self._items_result(query, items)

        fallback = self._items_result(query, _mock_items(query, limit), confidence="low")
        fallback.summary += " · live providers unavailable; fixture fallback"
        fallback.data["provider_errors"] = errors
        return fallback

    @staticmethod
    def _items_result(query: str, items: list[dict[str, Any]], confidence: str = "medium") -> ToolResult:
        fetched_at = datetime.now(UTC).isoformat()
        sources = [
            {
                "key": f"news:{query}:{i + 1}",
                "value": item,
                "source_type": "news",
                "source_url": item["url"],
                "publisher": item["source"],
                "published_at": item.get("published_at"),
                "fetched_at": fetched_at,
                "confidence": confidence,
                "excerpt": item["summary"],
            }
            for i, item in enumerate(items)
        ]
        return ToolResult(
            ok=True,
            summary=f"找到 {len(items)} 条与「{query}」相关的新闻",
            data={"items": items},
            sources=sources,
        )
