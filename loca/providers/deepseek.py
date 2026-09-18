"""DeepSeek provider.

DeepSeek exposes an OpenAI-compatible Chat Completions API, so everything the
wire protocol needs is in :mod:`loca.providers.openai_compat` — this module is
just the vendor's identity: an endpoint and a default model.

DeepSeek-specific behaviour worth knowing:

- ``reasoning_content`` is delivered alongside ``content`` for thinking models
  (DeepSeek-R1). The shared parser forwards it into
  ``Message.reasoning_content`` so the harness can display it separately
  instead of mixing it into user-visible text. Non-thinking endpoints simply
  never send the field.
- Tool calls use the same JSON-Schema-driven function-calling protocol as
  OpenAI, including the fragmented-delta streaming shape.

Overrides: ``LOCA_DEEPSEEK_BASE_URL`` and ``LOCA_DEEPSEEK_MODEL``, or the
constructor's ``base_url`` / ``default_model``. A ``--model`` flag always wins
because it travels on the request.
"""

from __future__ import annotations

from loca.providers.openai_compat import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek chat completions (``deepseek-chat`` / ``deepseek-reasoner``)."""

    name = "deepseek"
    default_base_url = "https://api.deepseek.com"
    default_model = "deepseek-chat"
