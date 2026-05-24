"""Anthropic-native LLM client.

Why a separate client (vs. routing through OpenRouter):

- **Prompt caching** — Anthropic offers 90% discount + lower TTFB on cached
  prefix blocks. Skill SKILL.md prompts are large (10-15k tokens) and stable;
  caching them is the difference between cheap and ruinous.
- **Tool-use parity** — Anthropic's `tool_use` content blocks map 1:1 with our
  AgentEvent stream; OpenAI-compat translation loses fidelity on
  multi-tool-call turns.
- **Usage telemetry** — Anthropic returns cache_read / cache_creation tokens
  separately; the harness needs these for accurate cost accounting.

This first cut focuses on text streaming. Native tool-use loop is a follow-up
change (see openspec/changes/004-anthropic-tool-use, planned).

Shape:
    client = AnthropicClient(api_key=..., model="claude-sonnet-4-6")
    async for chunk in client.stream_chat(messages):
        ...   # chunk is either a str (text delta) or a UsageDelta
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

from uteki_api.core.config import settings
from uteki_api.llm.usage import UsageDelta
from uteki_api.schemas.chat import ChatMessage

# Re-export so existing `from uteki_api.llm.anthropic_client import UsageDelta`
# imports keep working during the migration. Prefer importing from
# `uteki_api.llm.usage` in new code.
__all__ = ["AnthropicClient", "UsageDelta"]


class AnthropicClient:
    """Thin wrapper around AsyncAnthropic — same surface as `LLMClient`."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 4096,
        cache_system: bool = True,
    ) -> None:
        self.api_key = api_key or settings.anthropic_api_key
        self.base_url = base_url or settings.anthropic_base_url or None
        self.model = model or "claude-sonnet-4-6"
        self.max_tokens = max_tokens
        self.cache_system = cache_system
        self._client: AsyncAnthropic | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _ensure_client(self) -> AsyncAnthropic:
        if self._client is None:
            kwargs: dict[str, object] = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = AsyncAnthropic(**kwargs)
        return self._client

    @staticmethod
    def _split_system(messages: list[ChatMessage]) -> tuple[str, list[dict[str, str]]]:
        """Anthropic takes `system` separately; collapse role=system messages."""
        system_parts: list[str] = []
        chat: list[dict[str, str]] = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.content)
            else:
                # Anthropic accepts only user / assistant in the messages array
                role = "assistant" if m.role == "assistant" else "user"
                chat.append({"role": role, "content": m.content})
        return "\n\n".join(p for p in system_parts if p), chat

    async def stream_chat(
        self,
        messages: list[ChatMessage],
    ) -> AsyncIterator[str | UsageDelta]:
        """Stream text deltas; yield one final `UsageDelta` at the end.

        Mirrors `LLMClient.stream_chat`'s shape (yields strings), but also
        emits a UsageDelta sentinel so the harness can attribute cost.
        Callers that only care about text can filter `isinstance(x, str)`.
        """
        if not self.configured:
            raise RuntimeError(
                "Anthropic not configured. Set ANTHROPIC_API_KEY in env, "
                "or route this model through OpenRouter / AiHubMix."
            )

        system_text, chat = self._split_system(messages)

        # System block with optional cache_control for prompt caching.
        if system_text and self.cache_system:
            system_param: list[dict[str, object]] = [
                {
                    "type": "text",
                    "text": system_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        elif system_text:
            system_param = [{"type": "text", "text": system_text}]
        else:
            system_param = []

        client = self._ensure_client()

        # The SDK's `messages.stream` returns an async context manager whose
        # `text_stream` yields incremental text. Final usage lives on the
        # accumulated `Message` object.
        async with client.messages.stream(
            model=self.model,
            system=system_param,
            messages=chat,
            max_tokens=self.max_tokens,
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    yield text
            final = await stream.get_final_message()

        usage = getattr(final, "usage", None)
        if usage is not None:
            yield UsageDelta(
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            )
