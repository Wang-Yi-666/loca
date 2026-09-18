"""Tests for the Anthropic provider.

Everything here runs offline. The translation layer is written over duck-typed
objects, so the Messages API can be exercised with plain dicts — no SDK, no key,
no network. That is not a testing convenience bolted on afterwards; it is why
the translation lives in pure functions instead of inside the client calls.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from loca.providers.anthropic import (
    DEFAULT_MAX_TOKENS,
    AnthropicProvider,
    extract_content,
    from_anthropic_message,
    iter_stream_events,
    map_stop_reason,
    parse_usage,
    prompt_tokens,
    to_anthropic_messages,
    to_anthropic_tools,
)
from loca.providers.types import (
    ChatRequest,
    FinishReason,
    Message,
    Role,
    StreamChunk,
    ToolCall,
)

#: A reusable JSON-Schema stub, so the tool-schema assertions stay readable.
OBJECT: dict[str, Any] = {"type": "object", "properties": {}}

# ---- request translation ----------------------------------------------------


def test_system_messages_are_lifted_out() -> None:
    system, messages = to_anthropic_messages(
        [
            Message(role=Role.SYSTEM, content="you are loca"),
            Message(role=Role.SYSTEM, content="be brief"),
            Message(role=Role.USER, content="hi"),
        ]
    )

    assert system == "you are loca\n\nbe brief"
    assert messages == [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]


def test_tool_results_become_blocks_in_a_user_turn() -> None:
    _, messages = to_anthropic_messages(
        [
            Message(role=Role.USER, content="read a.py"),
            Message(
                role=Role.ASSISTANT,
                content=None,
                tool_calls=[ToolCall(id="toolu_1", name="read_file", arguments={"path": "a.py"})],
            ),
            Message(role=Role.TOOL, content="print(1)", tool_call_id="toolu_1"),
        ]
    )

    assert messages[1] == {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "a.py"}}
        ],
    }
    assert messages[2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "print(1)"}],
    }


def test_assistant_text_and_tool_calls_share_one_turn() -> None:
    _, messages = to_anthropic_messages(
        [
            Message(
                role=Role.ASSISTANT,
                content="let me look",
                tool_calls=[ToolCall(id="t1", name="read_file", arguments={"path": "a.py"})],
            )
        ]
    )

    assert messages[0]["content"] == [
        {"type": "text", "text": "let me look"},
        {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a.py"}},
    ]


def test_consecutive_same_role_turns_are_merged() -> None:
    """Two tool results in a row must not become two user messages."""
    _, messages = to_anthropic_messages(
        [
            Message(role=Role.TOOL, content="a", tool_call_id="t1"),
            Message(role=Role.TOOL, content="b", tool_call_id="t2"),
        ]
    )

    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert [block["tool_use_id"] for block in messages[0]["content"]] == ["t1", "t2"]


def test_tool_only_assistant_turn_gets_a_placeholder() -> None:
    """The API rejects an empty content array; a tool-only turn is normal for us."""
    _, messages = to_anthropic_messages([Message(role=Role.ASSISTANT, content=None)])

    assert messages[0]["content"] == [{"type": "text", "text": " "}]


def test_empty_user_content_gets_a_placeholder() -> None:
    _, messages = to_anthropic_messages([Message(role=Role.USER, content=None)])

    assert messages[0]["content"] == [{"type": "text", "text": " "}]


def test_to_anthropic_tools_accepts_the_openai_wrapper() -> None:
    converted = to_anthropic_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file.",
                    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
                },
            }
        ]
    )

    assert converted == [
        {
            "name": "read_file",
            "description": "Read a file.",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
        }
    ]


def test_to_anthropic_tools_accepts_the_bare_shape() -> None:
    converted = to_anthropic_tools(
        [{"name": "echo", "description": "d", "input_schema": {"type": "object"}}]
    )

    assert converted[0]["name"] == "echo"
    assert converted[0]["input_schema"] == {"type": "object"}


def test_to_anthropic_tools_defaults_a_missing_schema_and_skips_nameless() -> None:
    converted = to_anthropic_tools([{"name": "echo"}, {"description": "no name"}])

    assert len(converted) == 1
    assert converted[0]["input_schema"] == {"type": "object", "properties": {}}


# ---- response parsing -------------------------------------------------------


def test_extract_content_reads_text_thinking_and_tools() -> None:
    text, thinking, calls = extract_content(
        [
            {"type": "thinking", "thinking": "hmm"},
            {"type": "text", "text": "look:"},
            {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a.py"}},
            {"type": "redacted_thinking", "data": "..."},
        ]
    )

    assert text == "look:"
    assert thinking == "hmm"
    assert calls == [ToolCall(id="t1", name="read_file", arguments={"path": "a.py"})]


def test_extract_content_tolerates_a_missing_input() -> None:
    _, _, calls = extract_content([{"type": "tool_use", "id": "t1", "name": "echo"}])

    assert calls[0].arguments == {}


def test_from_anthropic_message_maps_the_whole_response() -> None:
    response = from_anthropic_message(
        {
            "content": [
                {"type": "text", "text": "on it"},
                {"type": "tool_use", "id": "t1", "name": "echo", "input": {"text": "x"}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 10, "output_tokens": 4},
        }
    )

    assert response.message.role is Role.ASSISTANT
    assert response.message.content == "on it"
    assert response.message.tool_calls == [ToolCall(id="t1", name="echo", arguments={"text": "x"})]
    assert response.finish_reason is FinishReason.TOOL_USE
    assert response.usage.total_tokens == 14


def test_stop_reason_mapping() -> None:
    assert map_stop_reason("end_turn") is FinishReason.STOP
    assert map_stop_reason("stop_sequence") is FinishReason.STOP
    assert map_stop_reason("tool_use") is FinishReason.TOOL_USE
    assert map_stop_reason("max_tokens") is FinishReason.LENGTH
    assert map_stop_reason("refusal") is FinishReason.CONTENT_FILTER
    assert map_stop_reason("who knows") is FinishReason.ERROR
    assert map_stop_reason(None) is FinishReason.ERROR


def test_usage_sums_cached_input_tokens() -> None:
    """Reporting only ``input_tokens`` would understate a cached conversation."""
    usage = parse_usage(
        {
            "input_tokens": 100,
            "cache_creation_input_tokens": 20,
            "cache_read_input_tokens": 300,
            "output_tokens": 40,
        }
    )

    assert usage is not None
    assert usage.prompt_tokens == 420
    assert usage.completion_tokens == 40
    assert usage.total_tokens == 460


def test_prompt_tokens_and_missing_usage() -> None:
    assert prompt_tokens({"input_tokens": 7}) == 7
    assert parse_usage(None) is None


# ---- streaming translation --------------------------------------------------


def _ev(kind: str, **fields: Any) -> dict[str, Any]:
    """One raw stream event, in the shape the SDK hands over."""
    return {"type": kind, **fields}


def _block_start(index: int, block: dict[str, Any]) -> dict[str, Any]:
    return _ev("content_block_start", index=index, content_block=block)


def _block_delta(index: int, delta: dict[str, Any]) -> dict[str, Any]:
    return _ev("content_block_delta", index=index, delta=delta)


def _json_delta(index: int, partial: str) -> dict[str, Any]:
    return _block_delta(index, {"type": "input_json_delta", "partial_json": partial})


def _text_delta(index: int, text: str) -> dict[str, Any]:
    return _block_delta(index, {"type": "text_delta", "text": text})


STREAM: list[dict[str, Any]] = [
    _ev("message_start", message={"usage": {"input_tokens": 30, "cache_read_input_tokens": 5}}),
    _block_start(0, {"type": "text", "text": ""}),
    _text_delta(0, "Let me "),
    _text_delta(0, "look."),
    _ev("content_block_stop", index=0),
    _block_start(1, {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {}}),
    _json_delta(1, '{"pa'),
    _json_delta(1, 'th": "a.py"}'),
    _ev("content_block_stop", index=1),
    _ev("message_delta", delta={"stop_reason": "tool_use"}, usage={"output_tokens": 12}),
    _ev("message_stop"),
]


def test_stream_events_produce_text_tools_and_usage() -> None:
    chunks = list(iter_stream_events(STREAM))

    text = "".join(chunk.delta_content for chunk in chunks)
    tool_calls = [call for chunk in chunks for call in chunk.delta_tool_calls]
    final = chunks[-1]

    assert text == "Let me look."
    assert tool_calls == [ToolCall(id="toolu_1", name="read_file", arguments={"path": "a.py"})]
    assert final.finish_reason is FinishReason.TOOL_USE
    assert final.usage is not None
    assert final.usage.prompt_tokens == 35
    assert final.usage.completion_tokens == 12
    assert final.usage.total_tokens == 47


def test_tool_call_is_only_emitted_once_complete() -> None:
    """Never hand the harness a half-written JSON argument string."""
    def is_tool_stop(event: dict[str, Any]) -> bool:
        return event.get("index") == 1 and event["type"] == "content_block_stop"

    chunks = list(iter_stream_events([event for event in STREAM if not is_tool_stop(event)]))

    # No content_block_stop for index 1, so the call is never flushed.
    assert all(not chunk.delta_tool_calls for chunk in chunks)


def test_truncated_tool_json_becomes_empty_arguments() -> None:
    events = [
        _block_start(0, {"type": "tool_use", "id": "t1", "name": "echo", "input": {}}),
        _json_delta(0, '{"text": "x'),
        _ev("content_block_stop", index=0),
    ]

    calls = [call for chunk in iter_stream_events(events) for call in chunk.delta_tool_calls]

    assert calls[0].arguments == {}


def test_tool_use_block_with_a_prefilled_input_is_kept() -> None:
    block = {"type": "tool_use", "id": "t1", "name": "echo", "input": {"text": "ready"}}
    events = [_block_start(0, block), _ev("content_block_stop", index=0)]

    calls = [call for chunk in iter_stream_events(events) for call in chunk.delta_tool_calls]

    assert calls[0].arguments == {"text": "ready"}


def test_thinking_deltas_are_forwarded_as_reasoning() -> None:
    events = [
        _block_start(0, {"type": "thinking", "thinking": ""}),
        _block_delta(0, {"type": "thinking_delta", "thinking": "step 1"}),
        _text_delta(0, "answer"),
    ]

    chunks = list(iter_stream_events(events))

    assert "".join(c.delta_reasoning for c in chunks) == "step 1"
    assert "".join(c.delta_content for c in chunks) == "answer"


def test_stream_without_a_stop_reason_defaults_to_stop() -> None:
    chunks = list(iter_stream_events([_ev("message_start", message={"usage": {}})]))

    assert chunks[-1].finish_reason is FinishReason.STOP


def test_error_events_raise() -> None:
    with pytest.raises(RuntimeError, match="overloaded"):
        list(iter_stream_events([_ev("error", error={"message": "overloaded"})]))


def test_unknown_event_types_are_ignored() -> None:
    chunks = list(iter_stream_events([_ev("ping"), _ev("message_stop")]))

    assert len(chunks) == 1


# ---- provider plumbing ------------------------------------------------------


class FakeMessages:
    def __init__(self, *, response: Any = None, events: list[Any] | None = None) -> None:
        self._response = response
        self._events = events or []
        self.payloads: list[dict[str, Any]] = []

    def create(self, **payload: Any) -> Any:
        self.payloads.append(payload)
        if payload.get("stream"):
            return iter(self._events)
        return self._response


class FakeAnthropicClient:
    def __init__(self, *, response: Any = None, events: list[Any] | None = None) -> None:
        self.messages = FakeMessages(response=response, events=events)


def _provider(**kwargs: Any) -> AnthropicProvider:
    return AnthropicProvider(api_key="sk-test", **kwargs)


def test_constructor_rejects_an_empty_key() -> None:
    with pytest.raises(ValueError, match="LOCA_ANTHROPIC_API_KEY"):
        AnthropicProvider(api_key="")


def test_build_payload_always_sends_max_tokens() -> None:
    provider = _provider(client=FakeAnthropicClient())
    request = ChatRequest(messages=[Message(role=Role.USER, content="hi")])

    payload = provider.build_payload(request, stream=True)

    assert payload["max_tokens"] == DEFAULT_MAX_TOKENS
    assert payload["stream"] is True
    assert payload["model"] == "claude-sonnet-4-5"
    assert "system" not in payload


def test_build_payload_includes_system_tools_and_respects_max_tokens() -> None:
    provider = _provider(client=FakeAnthropicClient())
    request = ChatRequest(
        messages=[
            Message(role=Role.SYSTEM, content="be brief"),
            Message(role=Role.USER, content="hi"),
        ],
        tools=[{"type": "function", "function": {"name": "echo", "parameters": OBJECT}}],
        model="claude-opus-4-1",
        max_tokens=99,
        temperature=0.2,
    )

    payload = provider.build_payload(request, stream=False)

    assert payload["system"] == "be brief"
    assert payload["max_tokens"] == 99
    assert payload["model"] == "claude-opus-4-1"
    assert payload["temperature"] == 0.2
    assert payload["tools"][0]["input_schema"] == OBJECT
    assert "stream" not in payload


def test_chat_goes_through_the_client() -> None:
    client = FakeAnthropicClient(
        response={
            "content": [{"type": "text", "text": "hello"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 3, "output_tokens": 2},
        }
    )
    provider = _provider(client=client)

    response = provider.chat(ChatRequest(messages=[Message(role=Role.USER, content="hi")]))

    assert response.message.content == "hello"
    assert response.finish_reason is FinishReason.STOP
    assert client.messages.payloads[0]["messages"][0]["role"] == "user"


def test_stream_chat_goes_through_the_client() -> None:
    client = FakeAnthropicClient(events=STREAM)
    provider = _provider(client=client)
    request = ChatRequest(messages=[Message(role=Role.USER, content="hi")])

    chunks = list(provider.stream_chat(request))

    assert "".join(c.delta_content for c in chunks) == "Let me look."
    assert client.messages.payloads[0]["stream"] is True


def test_default_model_can_be_overridden_by_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCA_ANTHROPIC_MODEL", "claude-haiku-4-5")
    provider = _provider(client=FakeAnthropicClient())

    assert provider._default_model == "claude-haiku-4-5"


def test_missing_sdk_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a key nobody needs the SDK; with one, say exactly what to install."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "anthropic":
            raise ImportError("no module named anthropic")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match=r"loca\[anthropic\]"):
        AnthropicProvider(api_key="sk-test")


def test_provider_is_named_anthropic() -> None:
    assert AnthropicProvider.name == "anthropic"


def test_serialized_messages_are_json_safe() -> None:
    """Payloads must survive a round trip — the SDK validates them as JSON."""
    _, messages = to_anthropic_messages(
        [
            Message(role=Role.USER, content="hi"),
            Message(
                role=Role.ASSISTANT,
                tool_calls=[ToolCall(id="t1", name="echo", arguments={"text": "héllo"})],
            ),
            Message(role=Role.TOOL, content="ok", tool_call_id="t1"),
        ]
    )

    assert json.loads(json.dumps(messages, ensure_ascii=False)) == messages


def test_stream_chunks_are_loca_stream_chunks() -> None:
    chunks: list[StreamChunk] = list(iter_stream_events(STREAM))

    assert all(isinstance(chunk, StreamChunk) for chunk in chunks)
