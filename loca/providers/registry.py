"""Provider registry.

Resolves a provider instance from environment variables. All three providers
are fully implemented; DeepSeek is the default because it is the one loca is
developed and tested against end to end (see ``pytest -m live``).

Credentials come from ``LOCA_<NAME>_API_KEY``. Endpoint and model can be
overridden per provider with ``LOCA_<NAME>_BASE_URL`` / ``LOCA_<NAME>_MODEL``,
which is what makes OpenAI-compatible gateways and self-hosted models usable
without touching code.
"""

from __future__ import annotations

import os

from loca.providers.anthropic import AnthropicProvider
from loca.providers.base import LLMProvider
from loca.providers.deepseek import DeepSeekProvider
from loca.providers.openai import OpenAIProvider

_ENV_PREFIX = "LOCA_"
_DEFAULT_PROVIDER = "deepseek"

_PROVIDERS: dict[str, type[LLMProvider]] = {
    "deepseek": DeepSeekProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}


def get_provider(name: str | None = None) -> LLMProvider:
    """Instantiate a provider by name.

    Reads credentials from environment variables of the form
    ``LOCA_<NAME>_API_KEY`` and selects ``LOCA_DEFAULT_PROVIDER`` (defaulting
    to ``deepseek``) when ``name`` is None.
    """
    provider_name = (
        name or os.environ.get(f"{_ENV_PREFIX}DEFAULT_PROVIDER") or _DEFAULT_PROVIDER
    ).lower()
    if provider_name not in _PROVIDERS:
        raise KeyError(
            f"Unknown provider {provider_name!r}. Available: {sorted(_PROVIDERS)}"
        )
    cls = _PROVIDERS[provider_name]
    env_var = f"{_ENV_PREFIX}{provider_name.upper()}_API_KEY"
    api_key = os.environ.get(env_var, "")
    # All providers raise on construction with an empty key — that's the cue
    # to ask the user to set the env var.
    return cls(api_key=api_key)


def available_providers() -> list[str]:
    """Names of providers that can currently be constructed (have a key set)."""
    out: list[str] = []
    for name in _PROVIDERS:
        env_var = f"{_ENV_PREFIX}{name.upper()}_API_KEY"
        if os.environ.get(env_var):
            out.append(name)
    return out
