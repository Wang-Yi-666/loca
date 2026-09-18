"""OpenAI provider.

OpenAI *is* the protocol that :mod:`loca.providers.openai_compat` implements,
so this provider is the base class plus an endpoint and a default model — the
concrete payoff of writing the DeepSeek integration against the wire format
rather than against the vendor.

Useful overrides:
- ``LOCA_OPENAI_BASE_URL`` — point at Azure OpenAI, a proxy, or a gateway.
- ``LOCA_OPENAI_MODEL`` — change the default model.
- ``--model`` on ``loca chat`` always wins, because it travels on the request.
"""

from __future__ import annotations

from loca.providers.openai_compat import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    """OpenAI chat completions."""

    name = "openai"
    default_base_url = "https://api.openai.com/v1"
    default_model = "gpt-4o-mini"
