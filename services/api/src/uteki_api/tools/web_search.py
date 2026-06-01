"""联网搜索工具 — Google CSE primary + DDGS fallback.

Phase C.3 migration. Same provider stack the news_search tool uses, just
without the news-recency bias: web_search returns general results
(documentation, blog posts, SEC filings, etc.), news_search filters to
recent news.

When no Google CSE key is configured the tool degrades to DDGS (DuckDuckGo)
and, if that also fails, to deterministic mock results so the rest of the
agent run continues. This is the same graceful-degradation contract
news_search uses.

Future: Tavily would be the upgrade (LLM-optimized markdown output), but
Google CSE + DDGS already gives the agent meaningful real results today
without an extra API key purchase.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from uteki_api.core.config import settings
from uteki_api.tools.base import Tool, ToolResult


async def _google_cse_general(query: str, limit: int) -> list[dict[str, Any]]:
    """Google Custom Search — general-purpose (no dateRestrict).

    The news flavor uses dateRestrict='m6' to bias toward fresh content;
    web_search wants the full corpus (docs, filings, blog posts), so we
    drop that filter.
    """
    if not settings.google_search_api_key or not settings.google_search_engine_id:
        return []
    params = {
        "key": settings.google_search_api_key,
        "cx": settings.google_search_engine_id,
        "q": query,
        "num": min(limit, 10),
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
                "snippet": raw.get("snippet", ""),
                "source": source,
                "url": url,
                "provider": "google_cse",
            }
        )
    return items


async def _ddgs_general(query: str, limit: int) -> list[dict[str, Any]]:
    """DDGS text search — no-key fallback."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _ddgs_general_sync, query, limit)


def _ddgs_general_sync(query: str, limit: int) -> list[dict[str, Any]]:
    try:
        from ddgs import DDGS
    except ImportError:
        return []
    try:
        client = DDGS()
        raw_items = client.text(query, max_results=limit) or []
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for raw in raw_items[:limit]:
        url = raw.get("url") or raw.get("href") or ""
        source = raw.get("source") or urlparse(url).netloc or "ddgs"
        out.append(
            {
                "title": raw.get("title", ""),
                "snippet": raw.get("body") or raw.get("snippet") or "",
                "source": source,
                "url": url,
                "provider": "ddgs",
            }
        )
    return out


def _mock_results(query: str, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "title": f"[mock] {query} 搜索结果 #{i + 1}",
            "snippet": f"关于 {query} 的占位摘要 #{i + 1}。",
            "source": "mock-web-search",
            "url": f"https://example.com/search/{i + 1}",
            "provider": "mock",
        }
        for i in range(limit)
    ]


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "联网搜索（Google Custom Search primary + DDGS fallback）。"
        "返回通用网页结果（文档、博客、SEC 文件等），不偏新闻。"
        "搜索关键词建议用英文以获得更多结果。"
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "limit": {
                "type": "integer",
                "default": 5,
                "minimum": 1,
                "maximum": 20,
                "description": "返回结果条数",
            },
        },
        "required": ["query"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "")
        limit = int(kwargs.get("limit", 5))
        # Backtest hint: web_search can't filter externally — soft-inject the
        # as_of into the query so the search engine + the LLM both see the
        # constraint. The catalog enforces hard rejection on extracted text.
        as_of = kwargs.get("as_of")
        if not query:
            return ToolResult(ok=False, error="query is required")
        limit = max(1, min(limit, 20))

        effective_query = (
            f"{query} (information available as of {as_of})" if as_of else query
        )

        if settings.use_mock_data:
            return self._items_result(
                effective_query, _mock_results(effective_query, limit),
                confidence="low", as_of=as_of,
            )

        errors: list[str] = []
        for searcher in (_google_cse_general, _ddgs_general):
            try:
                items = await searcher(effective_query, limit)
            except Exception as e:  # noqa: BLE001 — provider failure should degrade
                errors.append(f"{searcher.__name__}: {e}")
                continue
            if items:
                return self._items_result(effective_query, items, as_of=as_of)

        fallback = self._items_result(
            effective_query, _mock_results(effective_query, limit),
            confidence="low", as_of=as_of,
        )
        fallback.summary += " · live providers unavailable; fixture fallback"
        fallback.data["provider_errors"] = errors
        return fallback

    @staticmethod
    def _items_result(
        query: str,
        items: list[dict[str, Any]],
        confidence: str = "medium",
        as_of: str | None = None,
    ) -> ToolResult:
        fetched_at = datetime.now(UTC).isoformat()
        sources = [
            {
                "key": f"web_search:{query}:{i + 1}",
                "value": item,
                "source_type": "web_search",
                "source_url": item["url"],
                "publisher": item["source"],
                "fetched_at": fetched_at,
                "confidence": confidence,
                "excerpt": item["snippet"],
            }
            for i, item in enumerate(items)
        ]
        data: dict[str, Any] = {"query": query, "results": items}
        if as_of:
            data["as_of"] = as_of
        return ToolResult(
            ok=True,
            summary=f"搜到 {len(items)} 条结果",
            data=data,
            sources=sources,
        )
