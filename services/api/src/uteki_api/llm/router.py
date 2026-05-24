"""Multi-model router.

Resolves a logical model id like ``"<provider>/<upstream_model>"`` to a
configured client:

  anthropic/claude-sonnet-4-6        → AnthropicClient (native, supports cache)
  openrouter/anthropic/claude-...    → LLMClient(base_url=openrouter, …)
  aihubmix/gpt-4o-mini               → LLMClient(base_url=aihubmix, …)
  <bare model id>                    → LLMClient(legacy UTEKI_LLM_* config)

A `resolve()` always returns a client with the **same async surface**:
- `.configured: bool`
- `.stream_chat(messages) -> AsyncIterator[str | UsageDelta]`

so the skill can swap providers without code changes. The AnthropicClient
additionally yields a final `UsageDelta` sentinel — non-Anthropic callers can
simply ignore non-str items.

Fallback policy:
  - If the requested provider has no API key in env, log a warning and fall
    back to the OpenRouter equivalent (`openrouter/<original_model_path>`)
    when possible.
  - If even that is unavailable, return a non-configured client; the skill's
    own `client.configured` check will then route to mock.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from uteki_api.core.config import settings
from uteki_api.llm.anthropic_client import AnthropicClient
from uteki_api.llm.client import LLMClient

logger = logging.getLogger(__name__)

Client = LLMClient | AnthropicClient


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str         # hard-coded default; env override takes precedence
    api_key_attr: str     # attribute on Settings
    base_url_attr: str    # attribute on Settings for env override

    def resolved_base_url(self) -> str:
        override = getattr(settings, self.base_url_attr, "") or ""
        return (override or self.base_url).rstrip("/")


# OpenAI-compatible providers (single LLMClient covers them all)
OPENAI_COMPAT_PROVIDERS: dict[str, ProviderConfig] = {
    "openrouter": ProviderConfig(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_attr="openrouter_api_key",
        base_url_attr="openrouter_base_url",
    ),
    "aihubmix": ProviderConfig(
        name="aihubmix",
        base_url="https://aihubmix.com/v1",
        api_key_attr="aihubmix_api_key",
        base_url_attr="aihubmix_base_url",
    ),
    "deepseek": ProviderConfig(
        name="deepseek",
        base_url="https://api.deepseek.com/v1",
        api_key_attr="deepseek_api_key",
        base_url_attr="deepseek_base_url",
    ),
}

# Anthropic-native (separate client, supports cache_control)
ANTHROPIC_PROVIDER = "anthropic"


class ModelRouter:
    """Resolve a logical model id to a configured client."""

    def __init__(self, default_model: str | None = None) -> None:
        self.default_model = default_model or settings.default_model

    def resolve(self, model: str | None = None) -> Client:
        model = (model or self.default_model).strip()
        if not model:
            return LLMClient()

        # Bare model id → legacy UTEKI_LLM_* config
        if "/" not in model:
            return LLMClient(model=model)

        provider_key, _, upstream = model.partition("/")

        # ── Anthropic native ──────────────────────────────────────────
        if provider_key == ANTHROPIC_PROVIDER:
            client = AnthropicClient(model=upstream)
            if client.configured:
                return client
            logger.warning(
                "ANTHROPIC_API_KEY not set; falling back to openrouter for model=%s",
                model,
            )
            return self._openrouter_fallback(upstream)

        # ── OpenAI-compatible providers ───────────────────────────────
        provider = OPENAI_COMPAT_PROVIDERS.get(provider_key)
        if provider is not None:
            api_key = getattr(settings, provider.api_key_attr, "")
            return LLMClient(
                base_url=provider.resolved_base_url(),
                api_key=api_key,
                model=upstream,
            )

        # Unknown prefix → treat whole id as bare model on legacy backend
        logger.warning("Unknown provider prefix %r; falling back to legacy LLM config", provider_key)
        return LLMClient(model=model)

    def _openrouter_fallback(self, anthropic_model: str) -> Client:
        """When Anthropic is unconfigured, try OpenRouter's mirror of the model.

        OpenRouter aliases anthropic models as ``anthropic/<id>`` — convenient
        because our `anthropic/<id>` becomes `openrouter` with upstream
        ``anthropic/<id>``.
        """
        provider = OPENAI_COMPAT_PROVIDERS["openrouter"]
        api_key = getattr(settings, provider.api_key_attr, "")
        return LLMClient(
            base_url=provider.resolved_base_url(),
            api_key=api_key,
            model=f"anthropic/{anthropic_model}",
        )


default_router = ModelRouter()
