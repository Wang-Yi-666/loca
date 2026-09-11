"""Event types emitted by the agent execution loop.

The loop streams these events to its caller, which can forward them to a UI
or a test assertion. Each event is a frozen dataclass so consumers can do
``isinstance`` checks cheaply.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class EventType(str, Enum):
    """Discriminator for :class:`AgentEvent`."""

    TEXT_DELTA = "text_delta"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    STEP_START = "step_start"
    USAGE = "usage"
    CONTEXT_TRIMMED = "context_trimmed"
    RECOVERY = "recovery"
    ERROR = "error"
    DONE = "done"


@dataclass(slots=True)
class AgentEvent:
    """One tick of the agent loop.

    ``data`` shape depends on ``type``:

    - TEXT_DELTA: ``{"content": str}``
    - TOOL_CALL:  ``{"id": str, "name": str, "arguments": dict}``
    - TOOL_RESULT: ``{"name": str, "content": str, "is_error": bool}``
    - STEP_START: ``{"step": int}``
    - USAGE: ``{"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}``
    - CONTEXT_TRIMMED: ``{"dropped": int, "estimated_tokens": int, "budget": int}``
    - RECOVERY: ``{"reason": str, "step": int}``
    - ERROR: ``{"message": str, "step": int, "retryable": bool}``
    - DONE: ``{"reason": str, "steps": int, "total_tokens": int}``
    """

    type: EventType
    data: dict[str, Any]
