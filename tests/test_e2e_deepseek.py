"""End-to-end smoke test against the real DeepSeek API.

Skipped unless ``LOCA_DEEPSEEK_API_KEY`` is set in the environment. Run with:

    LOCA_DEEPSEEK_API_KEY=sk-... pytest tests/test_e2e_deepseek.py -v

Or put the key in ``.env`` and use python-dotenv to load it before pytest:

    pip install python-dotenv
    set -a && source .env && set +a && pytest tests/ -v
"""

from __future__ import annotations

import os

import pytest

from loca.providers import ChatRequest, FinishReason, Message, Role
from loca.providers.deepseek import DeepSeekProvider
from loca.providers.registry import get_provider

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("LOCA_DEEPSEEK_API_KEY"),
        reason="LOCA_DEEPSEEK_API_KEY not set; skipping live DeepSeek call",
    ),
]


def test_simple_chat_returns_text() -> None:
    provider = DeepSeekProvider(api_key=os.environ["LOCA_DEEPSEEK_API_KEY"])
    resp = provider.chat(
        ChatRequest(
            messages=[Message(role=Role.USER, content="用一句话回答：1+1=几？")],
            temperature=0.0,
        )
    )
    assert resp.finish_reason == FinishReason.STOP
    assert resp.message.content
    assert "2" in resp.message.content
    assert resp.usage.total_tokens > 0


def test_streaming_accumulates_full_text() -> None:
    provider = DeepSeekProvider(api_key=os.environ["LOCA_DEEPSEEK_API_KEY"])
    request = ChatRequest(
        messages=[Message(role=Role.USER, content="一句话自我介绍")],
        stream=True,
    )
    pieces: list[str] = []
    finish = None
    for chunk in provider.stream_chat(request):
        pieces.append(chunk.delta_content)
        if chunk.finish_reason is not None:
            finish = chunk.finish_reason
    assert finish == FinishReason.STOP
    joined = "".join(pieces).strip()
    assert joined, "streamed content was empty"
    assert len(joined) > 5


def test_registry_resolves_deepseek_by_default() -> None:
    provider = get_provider()
    assert provider.name == "deepseek"
