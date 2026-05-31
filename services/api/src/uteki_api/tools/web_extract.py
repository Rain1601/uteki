"""网页正文 / 实体抽取工具 — mock implementation.

Future: plug into trafilatura / readability + NER (spaCy / LLM)。
"""

from __future__ import annotations

import hashlib
import random
from typing import Any

from uteki_api.tools.base import Tool, ToolResult

_MOCK_COMPANIES = ["宁德时代", "比亚迪", "Apple", "NVIDIA", "腾讯", "字节跳动"]
_MOCK_PEOPLE = ["张三", "李四", "Tim Cook", "Jensen Huang", "马化腾"]


class WebExtractTool(Tool):
    name = "web_extract"
    description = "给定 URL，抽取正文与主要 entity（人名、公司名、数字）。"
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "format": "uri",
                "description": "目标网页 URL",
            },
        },
        "required": ["url"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        url = kwargs.get("url", "")
        if not url:
            return ToolResult(ok=False, error="url is required")

        seed = int(hashlib.md5(url.encode()).hexdigest(), 16) % (2**32)
        rng = random.Random(seed)

        title = f"[mock] 网页标题 - {url[:32]}"
        text = (
            f"这是一段从 {url} 抽取出的占位正文。"
            "内容包含若干公司与人物的提及，以及一些关键经营数据，用于演示 entity 抽取效果。"
            "正文长度约 200 字符，可在后续接入真实抽取器后替换。"
        )[:220]

        companies = rng.sample(_MOCK_COMPANIES, k=rng.randint(1, 3))
        people = rng.sample(_MOCK_PEOPLE, k=rng.randint(1, 2))
        numbers = [round(rng.uniform(1, 1000), 2) for _ in range(rng.randint(2, 4))]
        entities = {"companies": companies, "people": people, "numbers": numbers}
        total = len(companies) + len(people) + len(numbers)

        return ToolResult(
            ok=True,
            summary=f"抽取 {total} 个 entity",
            data={"url": url, "title": title, "text": text, "entities": entities},
            sources=[
                {
                    "key": f"web_extract:{url}",
                    "value": {"url": url, "title": title, "entities": entities},
                    "source_type": "web_extract",
                    "source_url": url,
                    "publisher": "mock-web-extract",
                    "confidence": "low",
                    "excerpt": text,
                }
            ],
        )
