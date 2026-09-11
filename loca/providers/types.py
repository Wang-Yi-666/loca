"""Shared types for the provider layer.

These dataclasses form the contract between loca's core loop and any concrete
provider. The shape is intentionally vendor-neutral so DeepSeek, OpenAI and
Anthropic implementations can map their native responses into this shape.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    """Roles that can appear in a chat message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class FinishReason(str, Enum):
    """Why the model stopped generating."""

    STOP = "stop"
    TOOL_USE = "tool_use"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"


@dataclass(slots=True)
class ToolCall:
    """A single tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class Usage:
    """Token accounting for a single chat call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    # DeepSeek-style reasoning tokens (when the provider exposes them).
    reasoning_tokens: int = 0


@dataclass(slots=True)
class Message:
    """One entry in the conversation history."""

    role: Role
    content: str | None = None
    # Set when the model is responding with one or more tool calls.
    tool_calls: list[ToolCall] = field(default_factory=list)
    # Set when this message is the result of executing a tool call.
    tool_call_id: str | None = None
    # Optional vendor-specific thinking text (e.g. DeepSeek reasoning_content).
    reasoning_content: str | None = None

    def to_openai(self) -> dict[str, Any]:
        """Render this message in OpenAI Chat Completions format."""
        payload: dict[str, Any] = {"role": self.role.value}
        if self.tool_calls:
            # OpenAI's pydantic SDK fills missing ``content`` with ``null``
            # when serializing, and DeepSeek rejects null on assistant
            # tool-call messages. Use a single space as a benign placeholder.
            if self.content and self.content.strip():
                payload["content"] = self.content
            else:
                payload["content"] = " "
            payload["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(
                            tc.arguments,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    },
                }
                for tc in self.tool_calls
            ]
        else:
            payload["content"] = self.content
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        return payload


@dataclass(slots=True)
class ChatRequest:
    """Input to a provider call."""

    messages: list[Message]
    tools: list[dict[str, Any]] = field(default_factory=list)
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False


@dataclass(slots=True)
class ChatResponse:
    """Non-streaming response from a provider."""

    message: Message
    finish_reason: FinishReason
    usage: Usage = field(default_factory=Usage)


@dataclass(slots=True)
class StreamChunk:
    """One piece of a streamed response.

    Providers yield these in order. The harness accumulates text deltas into
    ``message.content``, tool_call deltas into ``tool_calls``, and watches
    ``finish_reason`` to know when the stream is done.
    """

    delta_content: str = ""
    delta_reasoning: str = ""
    delta_tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: FinishReason | None = None
    usage: Usage | None = None
