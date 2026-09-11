"""Abstract base class that every provider must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from loca.providers.types import ChatRequest, ChatResponse, StreamChunk


class LLMProvider(ABC):
    """Vendor-neutral interface for chat completions.

    Concrete providers translate their wire protocol into ``ChatRequest`` /
    ``ChatResponse`` / ``StreamChunk``. The execution loop in
    ``loca.core.loop`` only talks to this interface.
    """

    name: str  # set by subclasses, e.g. "deepseek", "openai", "anthropic"

    @abstractmethod
    def chat(self, request: ChatRequest) -> ChatResponse:
        """Run a non-streaming chat completion."""

    @abstractmethod
    def stream_chat(self, request: ChatRequest) -> Iterator[StreamChunk]:
        """Run a streaming chat completion.

        The final chunk should have ``finish_reason`` set.
        """
        if False:  # pragma: no cover - structural hint for type checkers
            yield
