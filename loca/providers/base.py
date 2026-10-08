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

    @property
    def resolved_model(self) -> str | None:
        """The model this provider uses when the caller names none.

        Read when recording what a run actually measured. ``--model`` is
        normally left unset, so without this a benchmark report or a step trace
        can only record ``null`` — and an evidence file that cannot name its own
        model cannot support the reproducibility claim it is cited for.

        Every built-in provider stores its default in ``_default_model``, so the
        default implementation reads that; the ``getattr`` keeps the interface
        usable by test doubles that do not.
        """
        default = getattr(self, "_default_model", None)
        return str(default) if default else None

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
