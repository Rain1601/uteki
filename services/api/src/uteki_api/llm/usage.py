"""Shared LLM-stream sentinels: usage report + tool-call lifecycle.

The provider clients (``LLMClient`` / ``AnthropicClient``) all yield from
``stream_chat*`` methods; consumers discriminate on ``isinstance(chunk, ...)``
to handle text deltas, end-of-stream usage, and tool-call lifecycle events
uniformly.

Field semantics (provider notes):

- ``input_tokens`` / ``output_tokens``:
    Total prompt / completion tokens for the call. Both providers report.
- ``cache_read_tokens``:
    Tokens served from a prefix cache (no recompute, billed at a discount).
    Anthropic returns this as ``cache_read_input_tokens``.
    DeepSeek returns it as ``prompt_cache_hit_tokens`` (auto-cached, no opt-in).
- ``cache_creation_tokens``:
    Tokens written to the cache on this call (billed at a small premium).
    Anthropic returns this as ``cache_creation_input_tokens``.
    DeepSeek has no equivalent — always 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class UsageDelta:
    """Streamed token-usage report. Emitted once at the end of a stream."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass(frozen=True)
class ToolCallRequested:
    """LLM asked for a tool. ``arguments`` is already JSON-decoded."""

    call_id: str
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCallFulfilled:
    """Result of executing a requested tool. Always follows ToolCallRequested."""

    call_id: str
    name: str
    ok: bool = True
    summary: str = ""
    preview: Any = None
    error: str | None = None
