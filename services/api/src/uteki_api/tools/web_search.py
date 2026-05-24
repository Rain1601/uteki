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
        if not query:
            return ToolResult(ok=False, error="query is required")
        limit = max(1, min(limit, 20))

        results = [
            {
                "title": f"[mock] {query} 搜索结果 #{i + 1}",
                "url": f"https://example.com/search/{i + 1}",
                "snippet": f"关于 {query} 的占位摘要内容片段 #{i + 1}。",
                "source": "mock-web-search",
            }
            for i in range(limit)
        ]
        return ToolResult(
            ok=True,
            summary=f"搜到 {len(results)} 条结果",
            data={"query": query, "results": results},
        )
