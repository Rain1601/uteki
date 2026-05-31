"""联网搜索工具 — mock implementation.

Future: plug into Tavily / Serper / Bing Search API。
环境变量（接入真实后端时使用）：
- TAVILY_API_KEY
- SERPER_API_KEY
"""

from __future__ import annotations

from typing import Any

from uteki_api.tools.base import Tool, ToolResult


class WebSearchTool(Tool):
    name = "web_search"
    description = "联网搜索（Tavily / Serper 兼容接口，目前为 mock 数据）。"
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
        # web_search can't reliably filter by publish date (we don't own the
        # crawl). Best we can do in backtest mode is hint the search engine
        # via the query — the LLM also sees this and self-attenuates claims.
        # web_extract registering DataPoints into the catalog is the actual
        # enforcement layer.
        as_of = kwargs.get("as_of")
        if not query:
            return ToolResult(ok=False, error="query is required")
        limit = max(1, min(limit, 20))

        effective_query = f"{query} (information available as of {as_of})" if as_of else query
        results = [
            {
                "title": f"[mock] {effective_query} 搜索结果 #{i + 1}",
                "url": f"https://example.com/search/{i + 1}",
                "snippet": f"关于 {effective_query} 的占位摘要内容片段 #{i + 1}。",
                "source": "mock-web-search",
            }
            for i in range(limit)
        ]
        sources = [
            {
                "key": f"web_search:{query}:{i + 1}",
                "value": result,
                "source_type": "web_search",
                "source_url": result["url"],
                "publisher": result["source"],
                "confidence": "low",
                "excerpt": result["snippet"],
            }
            for i, result in enumerate(results)
        ]
        data: dict[str, Any] = {"query": effective_query, "results": results}
        if as_of:
            data["as_of"] = as_of
        return ToolResult(
            ok=True,
            summary=f"搜到 {len(results)} 条结果",
            data=data,
            sources=sources,
        )
