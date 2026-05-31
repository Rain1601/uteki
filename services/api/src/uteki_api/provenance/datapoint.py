"""DataPoint — a source-backed fact registered during one agent run.

The model should only cite facts that have gone through this schema. The
schema keeps source publication time separate from fetch time, because those
timestamps answer different questions in investment research.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SourceType = Literal[
    "tool_result",
    "web_search",
    "web_extract",
    "market_data",
    "financials",
    "filing",
    "news",
    "computed",
    "user_input",
]

ConfidenceLevel = Literal["high", "medium", "low"]


class DataPoint(BaseModel):
    """A single citable data fact within a run-scoped source catalog."""

    id: int = Field(..., description="1-indexed id assigned by SourceCatalog")
    key: str = Field(..., description="Stable fact key, e.g. revenue_2024")
    value: Any = Field(..., description="Fact value: number, string, dict, or list")

    source_type: SourceType
    source_url: str | None = None
    publisher: str | None = None

    published_at: str | None = Field(
        None,
        description="ISO timestamp/date reported by the source itself",
    )
    fetched_at: str = Field(..., description="ISO timestamp when uteki fetched it")
    as_of: str | None = Field(None, description="Backtest/research anchor date")

    derived_from: list[int] = Field(
        default_factory=list,
        description="For computed facts, catalog ids used to derive this fact",
    )
    confidence: ConfidenceLevel = "medium"
    excerpt: str | None = Field(
        None,
        max_length=400,
        description="Short source excerpt supporting the value",
    )

    def is_grounded(self) -> bool:
        """Return whether this fact has a verifiable source trail."""
        if self.source_type == "computed":
            return bool(self.derived_from)
        if self.source_type == "user_input":
            return True
        return bool(self.source_url) or bool(self.publisher)

    def short_label(self) -> str:
        """Compact human-readable label for debug views."""
        pub = f" ({self.published_at[:10]})" if self.published_at else ""
        publisher = self.publisher or self.source_type
        return f"[{self.id}] {publisher}{pub} - {self.key}"
