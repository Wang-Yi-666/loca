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
    CHECKPOINT = "checkpoint"
    CONTEXT_TRIMMED = "context_trimmed"
    CONTEXT_SUMMARIZED = "context_summarized"
    RECOVERY = "recovery"
    ERROR = "error"
    DONE = "done"


@dataclass(slots=True)
class AgentEvent:
    """One tick of the agent loop.

    ``data`` shape depends on ``type``:

    - TEXT_DELTA: ``{"content": str}``, plus ``"reasoning": str`` on the deltas
      that carry the model's private thinking (DeepSeek ``reasoning_content``,
      Anthropic ``thinking``). Those arrive with an empty ``content``, so a
      renderer can treat them as a separate channel.
    - TOOL_CALL:  ``{"id": str, "name": str, "arguments": dict}``
    - TOOL_RESULT: ``{"name": str, "content": str, "is_error": bool}``
    - STEP_START: ``{"step": int, "global_step": int}`` — ``step`` is the index
      inside this ``run()`` call; ``global_step`` is the session-wide counter
      (the number ``loca rollback`` and traces use).
    - USAGE: ``{"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}``
    - CHECKPOINT: ``{"step": int, "tool": str, "files": [str], "restorable": bool}``
    - CONTEXT_TRIMMED: ``{"dropped": int, "estimated_tokens": int, "budget": int}``
    - CONTEXT_SUMMARIZED: ``{"dropped": int, "summarized": int, "summary_tokens": int,
      "estimated_tokens": int, "budget": int}``
    - RECOVERY: ``{"reason": str, "step": int}`` — the loop carried on instead
      of ending the turn. ``reason`` says how: ``"length"`` (the reply hit the
      output cap, so the model was asked to continue) or ``"provider_retry"``
      (a transient provider failure the retry wrapper absorbed, with ``detail``
      naming the exception). The two are counted separately downstream — they
      are different events that happened to need the same vocabulary.
    - ERROR: ``{"message": str, "step": int, "retryable": bool}``
    - DONE: ``{"reason": str, "steps": int, "total_tokens": int}``
    """

    type: EventType
    data: dict[str, Any]
