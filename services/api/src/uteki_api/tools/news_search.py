"""News search tool — mock implementation.

Future: plug into 同花顺新闻 / 财联社 / Bloomberg News / 自建检索。
"""

from __future__ import annotations

from typing import Any

from uteki_api.tools.base import Tool, ToolResult


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

        items = [
            {
                "title": f"[mock] {query} 相关新闻 #{i + 1}",
                "summary": f"这是一条关于 {query} 的占位新闻摘要。",
                "source": "mock-news",
                "url": f"https://example.com/news/{i + 1}",
            }
            for i in range(limit)
        ]
        return ToolResult(
            ok=True,
            summary=f"找到 {len(items)} 条与「{query}」相关的新闻",
            data={"items": items},
        )
