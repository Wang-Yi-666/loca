"""Offline regression tests for DeepSeekProvider.stream_chat tool-call assembly.

The real OpenAI-compatible stream delivers a tool call as fragments: the
first delta carries ``id`` + ``function.name``, later deltas carry the
arguments as JSON string pieces. These tests pin the contract that the
provider only ever emits **fully assembled** calls — never an empty-argument
call emitted before the argument fragments arrive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loca.providers.deepseek import DeepSeekProvider
from loca.providers.types import ChatRequest, Message, Role

# ---- minimal fakes for the openai SDK's stream objects -----------------------


@dataclass
class FakeFunction:
    name: str | None = None
    arguments: str | None = None


@dataclass
class FakeDeltaToolCall:
    index: int | None = None
    id: str | None = None
    function: FakeFunction | None = None


@dataclass
class FakeDelta:
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[Any] = field(default_factory=list)


@dataclass
class FakeChoice:
    delta: FakeDelta
    finish_reason: str | None = None


@dataclass
class FakeRawChunk:
    choices: list[Any]
    usage: Any = None


class FakeCompletions:
    def __init__(self, chunks: list[FakeRawChunk]) -> None:
        self._chunks = chunks
        self.captured_payloads: list[dict[str, Any]] = []

    def create(self, **payload: Any) -> Any:
        self.captured_payloads.append(payload)
        return iter(self._chunks)


class FakeChat:
    def __init__(self, completions: FakeCompletions) -> None:
        self.completions = completions


class FakeClient:
    def __init__(self, chunks: list[FakeRawChunk]) -> None:
        self.chat = FakeChat(FakeCompletions(chunks))


def _provider_with_stream(chunks: list[FakeRawChunk]) -> DeepSeekProvider:
    provider = DeepSeekProvider(api_key="sk-test")
    provider._client = FakeClient(chunks)  # type: ignore[assignment]
    return provider


def _request() -> ChatRequest:
    return ChatRequest(
        messages=[Message(role=Role.USER, content="run it")],
        tools=[],
        stream=True,
    )


def _fragmented_call_chunks() -> list[FakeRawChunk]:
    """id/name first, arguments split over two later deltas, finish last."""
    return [
        # Text first — the model talks before calling the tool.
        FakeRawChunk(choices=[FakeChoice(delta=FakeDelta(content="Running it."))]),
        # Metadata delta: id + name, no arguments yet.
        FakeRawChunk(
            choices=[
                FakeChoice(
                    delta=FakeDelta(
                        tool_calls=[
                            FakeDeltaToolCall(
                                index=0,
                                id="call_abc",
                                function=FakeFunction(name="bash"),
                            )
                        ]
                    )
                )
            ]
        ),
        # Argument fragments.
        FakeRawChunk(
            choices=[
                FakeChoice(
                    delta=FakeDelta(
                        tool_calls=[
                            FakeDeltaToolCall(
                                index=0, function=FakeFunction(arguments='{"command"')
                            )
                        ]
                    )
                )
            ]
        ),
        FakeRawChunk(
            choices=[
                FakeChoice(
                    delta=FakeDelta(
                        tool_calls=[
                            FakeDeltaToolCall(
                                index=0,
                                function=FakeFunction(arguments=': "echo hi"}'),
                            )
                        ]
                    )
                )
            ]
        ),
        # Finish chunk: empty delta, finish_reason set.
        FakeRawChunk(
            choices=[FakeChoice(delta=FakeDelta(), finish_reason="tool_calls")]
        ),
    ]


def test_tool_call_flushed_once_with_full_arguments() -> None:
    provider = _provider_with_stream(_fragmented_call_chunks())
    out = list(provider.stream_chat(_request()))

    # Nothing before the flush may carry tool calls.
    for chunk in out:
        if chunk.finish_reason is None or chunk.delta_content:
            assert chunk.delta_tool_calls == []

    flushed = [c for c in out if c.delta_tool_calls]
    assert len(flushed) == 1, "call must be emitted exactly once, fully assembled"
    (tc,) = flushed[0].delta_tool_calls
    assert tc.id == "call_abc"
    assert tc.name == "bash"
    assert tc.arguments == {"command": "echo hi"}


def test_parallel_tool_calls_all_flushed() -> None:
    chunks = [
        FakeRawChunk(
            choices=[
                FakeChoice(
                    delta=FakeDelta(
                        tool_calls=[
                            FakeDeltaToolCall(
                                index=0, id="c0", function=FakeFunction(name="bash")
                            ),
                            FakeDeltaToolCall(
                                index=1, id="c1", function=FakeFunction(name="echo")
                            ),
                        ]
                    )
                )
            ]
        ),
        FakeRawChunk(
            choices=[
                FakeChoice(
                    delta=FakeDelta(
                        tool_calls=[
                            FakeDeltaToolCall(
                                index=0, function=FakeFunction(arguments='{"command": "ls"}')
                            )
                        ]
                    )
                )
            ]
        ),
        FakeRawChunk(
            choices=[
                FakeChoice(
                    delta=FakeDelta(
                        tool_calls=[
                            FakeDeltaToolCall(
                                index=1, function=FakeFunction(arguments='{"text": "hi"}')
                            )
                        ]
                    )
                )
            ]
        ),
        FakeRawChunk(
            choices=[FakeChoice(delta=FakeDelta(), finish_reason="tool_calls")]
        ),
    ]
    provider = _provider_with_stream(chunks)
    flushed = [c for c in provider.stream_chat(_request()) if c.delta_tool_calls]
    assert len(flushed) == 1
    calls = {tc.name: tc for tc in flushed[0].delta_tool_calls}
    assert set(calls) == {"bash", "echo"}
    assert calls["bash"].arguments == {"command": "ls"}
    assert calls["echo"].arguments == {"text": "hi"}


def test_empty_arguments_flush_as_empty_dict() -> None:
    """A no-argument call streams zero argument fragments; {} is correct."""
    chunks = [
        FakeRawChunk(
            choices=[
                FakeChoice(
                    delta=FakeDelta(
                        tool_calls=[
                            FakeDeltaToolCall(
                                index=0,
                                id="c9",
                                function=FakeFunction(name="noargs"),
                            )
                        ]
                    )
                )
            ]
        ),
        FakeRawChunk(
            choices=[FakeChoice(delta=FakeDelta(), finish_reason="tool_calls")]
        ),
    ]
    provider = _provider_with_stream(chunks)
    flushed = [c for c in provider.stream_chat(_request()) if c.delta_tool_calls]
    (tc,) = flushed[0].delta_tool_calls
    assert tc.arguments == {}


def test_text_only_stream_has_no_flush_chunk() -> None:
    chunks = [
        FakeRawChunk(choices=[FakeChoice(delta=FakeDelta(content="hello"))]),
        FakeRawChunk(choices=[FakeChoice(delta=FakeDelta(), finish_reason="stop")]),
    ]
    provider = _provider_with_stream(chunks)
    out = list(provider.stream_chat(_request()))
    assert all(c.delta_tool_calls == [] for c in out)
    assert out[-1].finish_reason is not None
