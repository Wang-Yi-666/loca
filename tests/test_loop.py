"""Tests for the agent execution loop using a fake provider.

We never hit the network here. The fake provider yields scripted events so
we can assert on the loop's behavior deterministically.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from loca.core.events import EventType
from loca.core.loop import AgentLoop
from loca.providers.base import LLMProvider
from loca.providers.types import (
    ChatRequest,
    ChatResponse,
    FinishReason,
    Message,
    StreamChunk,
    ToolCall,
    Usage,
)
from loca.tools.base import Tool, ToolContext, ToolResult


class FakeProvider(LLMProvider):
    """Provider that returns a scripted sequence of streamed responses."""

    def __init__(self, scripts: list[list[StreamChunk]]) -> None:
        self.name = "fake"
        self._scripts = list(scripts)
        self._call_index = 0
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:  # pragma: no cover
        raise NotImplementedError

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamChunk]:
        self.requests.append(request)
        idx = min(self._call_index, len(self._scripts) - 1)
        self._call_index += 1
        yield from self._scripts[idx]


def _scripted_text(text: str, *, usage: Usage | None = None) -> list[StreamChunk]:
    return [
        StreamChunk(delta_content=text, finish_reason=FinishReason.STOP, usage=usage),
    ]


def _scripted_tool_call(
    name: str, args: dict[str, Any], tool_id: str = "call_1"
) -> list[StreamChunk]:
    return [
        StreamChunk(
            delta_tool_calls=[ToolCall(id=tool_id, name=name, arguments=args)],
            finish_reason=FinishReason.TOOL_USE,
        ),
    ]


class _EchoTool(Tool):
    name = "echo"
    description = "Echo arguments back."
    input_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    }

    def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult(content=f"echo: {arguments['text']}")


@pytest.fixture
def echo_tool() -> Tool:
    return _EchoTool()


def test_simple_text_response_terminates(
    ctx: ToolContext, echo_tool: Tool
) -> None:
    provider = FakeProvider([_scripted_text("hello there")])
    loop = AgentLoop(provider=provider, tools=[echo_tool], system_prompt="x")
    events = list(loop.run(ctx, user_message="hi"))
    types = [e.type for e in events]
    assert EventType.STEP_START in types
    assert EventType.TEXT_DELTA in types
    assert EventType.DONE in types
    # No tool call events.
    assert EventType.TOOL_CALL not in types


def test_tool_call_runs_and_loop_continues(
    ctx: ToolContext, echo_tool: Tool
) -> None:
    provider = FakeProvider(
        [
            _scripted_tool_call("echo", {"text": "first"}, tool_id="c1"),
            _scripted_text("all done"),
        ]
    )
    loop = AgentLoop(provider=provider, tools=[echo_tool], system_prompt="x")
    events = list(loop.run(ctx, user_message="please echo"))
    tool_results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(tool_results) == 1
    assert tool_results[0].data["content"] == "echo: first"
    # The second provider call should see the tool message appended.
    assert len(provider.requests) == 2
    last_request = provider.requests[1]
    # The conversation fed to the second call: [system, user, assistant+tool_call,
    # tool_result, assistant+content]. We just want to confirm the tool result
    # made it in.
    roles = [m.role.value for m in last_request.messages]
    assert "tool" in roles
    tool_message = next(m for m in last_request.messages if m.role.value == "tool")
    assert tool_message.content == "echo: first"
    assert tool_message.tool_call_id == "c1"


def test_unknown_tool_returns_error(ctx: ToolContext) -> None:
    provider = FakeProvider(
        [
            _scripted_tool_call("nope", {}),
            _scripted_text("ok"),
        ]
    )
    loop = AgentLoop(provider=provider, tools=[_EchoTool()], system_prompt="x")
    events = list(loop.run(ctx, user_message="x"))
    result_events = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert result_events[0].data["is_error"] is True
    assert "Unknown tool" in result_events[0].data["content"]


def test_max_steps_terminates_loop(ctx: ToolContext) -> None:
    # Always returns a tool call, never a final answer. Loop should bail at
    # max_steps.
    provider = FakeProvider(
        [_scripted_tool_call("echo", {"text": str(i)}, tool_id=f"c{i}") for i in range(5)]
    )
    loop = AgentLoop(
        provider=provider,
        tools=[_EchoTool()],
        system_prompt="x",
        max_steps=3,
    )
    events = list(loop.run(ctx, user_message="x"))
    done = [e for e in events if e.type == EventType.DONE]
    assert done
    assert done[-1].data["reason"] == "max_steps"
    assert done[-1].data["steps"] == 3


def test_invalid_tool_arguments_surface_as_error(
    ctx: ToolContext, echo_tool: Tool
) -> None:
    # echo requires "text" but we pass nothing.
    provider = FakeProvider(
        [
            _scripted_tool_call("echo", {}),
            _scripted_text("recovered"),
        ]
    )
    loop = AgentLoop(provider=provider, tools=[echo_tool], system_prompt="x")
    events = list(loop.run(ctx, user_message="x"))
    result_events = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert result_events[0].data["is_error"] is True
    assert "Invalid arguments" in result_events[0].data["content"]


def test_history_is_extended_not_replaced(
    ctx: ToolContext, echo_tool: Tool
) -> None:
    provider = FakeProvider([_scripted_text("ok")])
    loop = AgentLoop(provider=provider, tools=[echo_tool], system_prompt="sys")
    prior = [Message(role="user", content="old question")]
    list(loop.run(ctx, user_message="new question", history=prior))
    # Verify the provider got the system prompt + prior + new user message.
    sent = provider.requests[0].messages
    assert sent[0].role.value == "system"
    assert sent[1].content == "old question"
    assert sent[2].content == "new question"
