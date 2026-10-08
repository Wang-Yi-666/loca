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

import pytest

from loca.providers.deepseek import DeepSeekProvider
from loca.providers.types import ChatRequest, FinishReason, Message, Role

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


@dataclass
class FakeUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


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
                                function=FakeFunction(name="shell"),
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

    # Nothing before the flush may carry tool calls. This loop only bites on
    # frames that report a finish_reason — which, before the mid-stream fix,
    # was every frame (they all said ERROR), so it asserted almost nothing.
    for chunk in out:
        if chunk.finish_reason is None or chunk.delta_content:
            assert chunk.delta_tool_calls == []

    flushed = [c for c in out if c.delta_tool_calls]
    assert len(flushed) == 1, "call must be emitted exactly once, fully assembled"
    (tc,) = flushed[0].delta_tool_calls
    assert tc.id == "call_abc"
    assert tc.name == "shell"
    assert tc.arguments == {"command": "echo hi"}


def test_mid_stream_frames_do_not_claim_a_finish_reason() -> None:
    """A frame that says nothing about why generation stopped must stay None.

    :mod:`loca.providers.types` documents ``finish_reason`` as the
    end-of-stream signal, so mapping a mid-stream ``None`` through the
    "unrecognised reason" default made any consumer following that contract
    stop — and treat the turn as failed — on the first frame.
    """
    provider = _provider_with_stream(_fragmented_call_chunks())
    out = list(provider.stream_chat(_request()))

    assert out[0].finish_reason is None, "the text frame carries no reason"
    assert out[-1].finish_reason is FinishReason.TOOL_USE
    assert all(c.finish_reason is not FinishReason.ERROR for c in out)


def test_streaming_asks_the_endpoint_for_usage() -> None:
    """Without stream_options OpenAI sends no usage, so reports showed 0 tokens."""
    client = FakeClient([])
    provider = DeepSeekProvider(api_key="sk-test")
    provider._client = client  # type: ignore[assignment]

    list(provider.stream_chat(_request()))

    payload = client.chat.completions.captured_payloads[0]
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}


def test_stream_usage_request_can_be_switched_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Older self-hosted gateways reject the unknown field outright."""
    monkeypatch.setenv("LOCA_DEEPSEEK_STREAM_USAGE", "0")
    client = FakeClient([])
    provider = DeepSeekProvider(api_key="sk-test")
    provider._client = client  # type: ignore[assignment]

    list(provider.stream_chat(_request()))

    assert "stream_options" not in client.chat.completions.captured_payloads[0]


def test_non_streaming_requests_never_carry_stream_options() -> None:
    provider = DeepSeekProvider(api_key="sk-test")
    payload = provider._build_payload(_request(), stream=False)
    assert "stream_options" not in payload


def test_the_usage_frame_reaches_the_consumer() -> None:
    """OpenAI sends usage in a trailing ``choices=[]`` frame; it must survive."""
    chunks = [
        FakeRawChunk(choices=[FakeChoice(delta=FakeDelta(content="hi"))]),
        FakeRawChunk(choices=[FakeChoice(delta=FakeDelta(), finish_reason="stop")]),
        FakeRawChunk(
            choices=[],
            usage=FakeUsage(prompt_tokens=11, completion_tokens=4, total_tokens=15),
        ),
    ]
    provider = _provider_with_stream(chunks)
    out = list(provider.stream_chat(_request()))

    usages = [c.usage for c in out if c.usage is not None]
    assert usages, "the usage frame was dropped"
    assert usages[-1].total_tokens == 15
    assert usages[-1].prompt_tokens == 11


def test_parallel_tool_calls_all_flushed() -> None:
    chunks = [
        FakeRawChunk(
            choices=[
                FakeChoice(
                    delta=FakeDelta(
                        tool_calls=[
                            FakeDeltaToolCall(
                                index=0, id="c0", function=FakeFunction(name="shell")
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
                                index=0, function=FakeFunction(arguments='{"command": "dir"}')
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
    assert set(calls) == {"shell", "echo"}
    assert calls["shell"].arguments == {"command": "dir"}
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
