from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant", "tool"]


class ToolCallSpec(BaseModel):
    """OpenAI-style tool_call object embedded on assistant messages.

    ``function.arguments`` is a JSON-encoded string (per upstream spec). We
    keep that exact shape so messages round-trip back to the chat-completions
    endpoint without translation.
    """

    id: str
    type: Literal["function"] = "function"
    function: dict


class ChatMessage(BaseModel):
    role: Role
    # Tool-result messages legitimately have no content beyond the result
    # body. Make optional so we don't fight the upstream protocol.
    content: str | None = ""
    name: str | None = None
    # Set on ``role="assistant"`` messages that requested tools.
    tool_calls: list[ToolCallSpec] | None = None
    # Set on ``role="tool"`` messages that carry a tool result.
    tool_call_id: str | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1)
    session_id: str | None = None
    agent: str = "research"
    model: str | None = None  # override model router default
    # Backtest / "as-of-date" mode. When set, the harness threads this date
    # into tool kwargs so fetchers slice at the source (yfinance history end,
    # news/financials filtering) instead of pulling current data only to have
    # the SourceCatalog reject future-dated points after the fact.
    as_of: date | None = None
    # Operator-facing origin label for the LOG list. Maps 1:1 to the Run's
    # triggered_by. Defaults to "user" (= MANUAL). Callers pass "test" when
    # running through Claude Code / Codex automation, "cron"/"event" when a
    # scheduled trigger fires.
    origin: Literal["user", "cron", "event", "eval", "compare", "test"] | None = None
