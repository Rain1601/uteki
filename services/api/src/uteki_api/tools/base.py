"""Tool framework.

A Tool exposes:
- `name`: unique identifier the LLM uses to call it.
- `description`: shown to the LLM.
- `parameters`: JSON-Schema fragment for arguments (OpenAI tool-call compatible).
- `run(**kwargs) -> ToolResult`: async execution.

The ToolRegistry holds a set of tools and produces OpenAI-tool-spec JSON for
LLM function-calling endpoints.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    ok: bool = True
    summary: str = ""
    data: Any = None
    error: str | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)


ToolRiskLevel = Literal["low", "medium", "high"]


class Tool(ABC):
    name: str
    description: str
    parameters: dict[str, Any]
    risk_level: ToolRiskLevel = "low"

    @abstractmethod
    async def run(self, **kwargs: Any) -> ToolResult: ...

    def to_openai_spec(self) -> dict[str, Any]:
        """OpenAI / OpenRouter / AiHubMix function-call spec."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": f"{self.description}\nRisk level: {self.risk_level}.",
                "parameters": self.parameters,
            },
        }

    def to_anthropic_spec(self) -> dict[str, Any]:
        """Anthropic Messages API tool spec.

        Anthropic uses a flatter shape (no "function" wrapper) and renames
        `parameters` → `input_schema`. Same JSON Schema content.
        """
        return {
            "name": self.name,
            "description": f"{self.description}\nRisk level: {self.risk_level}.",
            "input_schema": self.parameters,
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        return self._tools[name]

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def openai_specs(self) -> list[dict[str, Any]]:
        return [t.to_openai_spec() for t in self._tools.values()]

    def anthropic_specs(self) -> list[dict[str, Any]]:
        return [t.to_anthropic_spec() for t in self._tools.values()]
