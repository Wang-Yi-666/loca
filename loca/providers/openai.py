"""OpenAI provider stub.

The architecture is fully wired up — calling code does not need to change when
this is implemented. Only the credential is missing for now.
"""

from __future__ import annotations

from collections.abc import Iterator

from loca.providers.base import LLMProvider
from loca.providers.types import ChatRequest, ChatResponse, StreamChunk


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError(
                "OpenAIProvider requires OPENAI_API_KEY. Set LOCA_OPENAI_API_KEY."
            )
        self._api_key = api_key  # unused until implemented

    def chat(self, request: ChatRequest) -> ChatResponse:
        raise NotImplementedError(
            "OpenAI provider is scaffolded but not yet implemented. "
            "Drop LOCA_OPENAI_API_KEY into .env and finish chat() in Week 5."
        )

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamChunk]:
        raise NotImplementedError("OpenAI streaming is not implemented yet.")
        if False:  # pragma: no cover
            yield
