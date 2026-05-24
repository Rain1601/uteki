"""财报 / 研报解析工具 — mock implementation.

Future: plug into PDF 解析 (pdfplumber / unstructured) + LLM summarizer。
"""

from __future__ import annotations

from typing import Any

from uteki_api.tools.base import Tool, ToolResult

_FOCUS_HEADINGS = {
    "summary": ["核心摘要", "业绩总览", "管理层观点"],
    "risks": ["主要风险", "宏观风险", "经营风险"],
    "opportunities": ["增长机会", "市场扩张", "新产品 / 新业务"],
    "financials": ["营收结构", "盈利能力", "现金流"],
}


class ReportAnalysisTool(Tool):
    name = "report_analysis"
    description = "解析财报 / 研报 PDF（或纯文本），输出结构化要点。"
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "format": "uri",
                "description": "财报 / 研报的 URL（PDF 或网页）",
            },
            "text": {
                "type": "string",
                "description": "财报 / 研报的纯文本（与 url 二选一）",
            },
            "focus": {
                "type": "string",
                "enum": ["summary", "risks", "opportunities", "financials"],
                "default": "summary",
                "description": "聚焦的解析维度",
            },
        },
        "oneOf": [{"required": ["url"]}, {"required": ["text"]}],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        url = kwargs.get("url")
        text = kwargs.get("text")
        focus = kwargs.get("focus", "summary")
        if not url and not text:
            return ToolResult(ok=False, error="either url or text is required")
        if focus not in _FOCUS_HEADINGS:
            return ToolResult(ok=False, error=f"invalid focus: {focus}")

        source = url if url else "inline-text"
        title = f"[mock] 研报解析 - {focus}"
        sections: list[dict[str, Any]] = []
        bullet_count = 0
        for heading in _FOCUS_HEADINGS[focus]:
            bullets = [
                f"{heading} 要点 #{i + 1}：这是一段占位的结构化结论。"
                for i in range(3)
            ]
            bullet_count += len(bullets)
            sections.append({"heading": heading, "bullets": bullets})

        return ToolResult(
            ok=True,
            summary=f"提取到 {bullet_count} 个要点",
            data={"title": title, "source": source, "sections": sections},
        )
