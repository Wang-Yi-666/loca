"""Agent execution loop.

The loop drives a single ``run()`` invocation:

1. Start with a system prompt and a list of user/assistant messages.
2. Trim the context if it is about to overflow the model's window.
3. Call the provider with the current messages + available tool schemas.
4. Stream text deltas, then collect any tool calls.
5. For each tool call, validate arguments, execute, and append a tool
   message with the result.
6. If the model emitted no tool calls, we're done.
7. Otherwise, repeat up to ``max_steps`` times.

The loop is **stream-first**: callers consume events via a generator. The
caller is responsible for converting the event stream to whatever transport
they want (SSE, websocket, log file, etc.).

Failure handling (Week 3):

- Transient provider failures (timeouts, 429s, 5xx) are retried by
  :class:`~loca.core.recovery.RetryingProvider` before they reach the loop.
- Anything the retry policy gives up on is surfaced as an ``ERROR`` event
  rather than escaping the generator, so a UI/SSE consumer keeps its stream.
- Tool failures are recoverable by design: they come back as a
  ``ToolResult(is_error=True)`` and the model gets a chance to self-correct.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from loca.core.events import AgentEvent, EventType
from loca.core.recovery import RetryingProvider, is_transient, trim_messages
from loca.providers.base import LLMProvider
from loca.providers.types import (
    ChatRequest,
    FinishReason,
    Message,
    Role,
)
from loca.tools.base import Tool, ToolContext, ToolResult
from loca.tools.registry import all_tools
from loca.tools.validation import SchemaValidationError, validate_arguments

# 64k tokens is DeepSeek's window; keep headroom for the model's own reply.
DEFAULT_TOKEN_BUDGET = 48_000


class AgentLoop:
    """Drive a multi-step agent conversation."""

    DEFAULT_SYSTEM_PROMPT = (
        "You are loca, a coding assistant. You have access to filesystem and "
        "shell tools. Use them to answer the user's request. Be concise."
    )

    #: Sent as a user turn when the model's answer was truncated by the output
    #: length limit, so it resumes instead of returning half a reply.
    CONTINUE_AFTER_TRUNCATION = (
        "Your previous reply was cut off by the output length limit. Continue "
        "exactly where you stopped — do not repeat what you already wrote."
    )

    def __init__(
        self,
        provider: LLMProvider,
        tools: Sequence[Tool] | None = None,
        *,
        system_prompt: str | None = None,
        max_steps: int = 20,
        model: str | None = None,
        temperature: float | None = None,
        retries: int = 2,
        context_token_budget: int | None = DEFAULT_TOKEN_BUDGET,
        keep_recent_messages: int = 6,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """
        Parameters
        ----------
        retries:
            Extra attempts for *transient* provider failures (rate limits,
            timeouts, 5xx). ``0`` disables the wrapper entirely.
        context_token_budget:
            Estimated token ceiling for one request. The loop drops the oldest
            turns before calling the model. ``None`` disables trimming.
        keep_recent_messages:
            Messages that survive a trim regardless of the budget.
        sleep:
            Injected so tests can run the retry path without real delays.
        """
        self._raw_provider = provider
        self.provider: LLMProvider = (
            RetryingProvider(provider, max_attempts=retries + 1, sleep=sleep)
            if retries > 0
            else provider
        )
        self.tools: list[Tool] = list(tools) if tools is not None else list(all_tools())
        self.system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT
        self.max_steps = max_steps
        self.model = model
        self.temperature = temperature
        self.retries = retries
        self.context_token_budget = context_token_budget
        self.keep_recent_messages = keep_recent_messages
        #: Full message list of the most recent ``run()`` (system prompt, the
        #: user turn, every assistant/tool message). Feed it back as
        #: ``history`` for multi-turn chat. It is the same list object the loop
        #: mutated, so it stays current even after a context trim.
        self.last_transcript: list[Message] = []

    def run(
        self,
        ctx: ToolContext,
        user_message: str,
        history: Sequence[Message] | None = None,
    ) -> Iterator[AgentEvent]:
        """Run one user turn end-to-end. Yields events as they happen.

        ``history`` is the prior conversation (e.g. multi-turn chat). The new
        user message is appended to it. The loop owns the system prompt: any
        system message in ``history`` is dropped so replaying
        ``last_transcript`` back into ``run()`` never duplicates it.
        """
        messages: list[Message] = []
        if self.system_prompt:
            messages.append(Message(role=Role.SYSTEM, content=self.system_prompt))
        messages.extend(m for m in (history or []) if m.role is not Role.SYSTEM)
        if user_message:
            messages.append(Message(role=Role.USER, content=user_message))

        # Expose the live transcript. We keep the same list object for the
        # whole run (including trims, which mutate in place) so callers can
        # read it back after the generator is exhausted.
        self.last_transcript = messages

        # Build tool schemas once for the whole run.
        tool_schemas = [t.to_openai_tool() for t in self.tools] if self.tools else []

        total_tokens = 0
        last_finish: FinishReason | None = None
        for step in range(self.max_steps):
            yield AgentEvent(type=EventType.STEP_START, data={"step": step})

            # Keep the request inside the model's context window. The estimate
            # is cheap and deliberately conservative; a wrong estimate only
            # costs some old history, never a failed call.
            if self.context_token_budget is not None:
                outcome = trim_messages(
                    messages,
                    max_tokens=self.context_token_budget,
                    keep_recent=self.keep_recent_messages,
                )
                if outcome.trimmed:
                    # Mutate in place so ``last_transcript`` keeps pointing at
                    # the live conversation.
                    messages[:] = outcome.messages
                    yield AgentEvent(
                        type=EventType.CONTEXT_TRIMMED,
                        data={
                            "dropped": outcome.dropped,
                            "estimated_tokens": outcome.estimated_tokens,
                            "budget": self.context_token_budget,
                        },
                    )

            request = ChatRequest(
                # Snapshot the list: we keep appending tool results to
                # ``messages`` after the call, and an observer holding the
                # request (a trace recorder, a test) must see what was
                # actually sent, not the later mutation.
                messages=list(messages),
                tools=tool_schemas,
                model=self.model,
                temperature=self.temperature,
                stream=True,
            )

            # Accumulate streamed response. Providers (see ``DeepSeekProvider``)
            # deliver tool calls as fully assembled ``ToolCall`` objects, so
            # we just extend the list.
            text = ""
            reasoning = ""
            tool_calls: list[Any] = []
            finish: FinishReason | None = None
            step_usage: dict[str, int] = {}

            try:
                for chunk in self.provider.stream_chat(request):
                    if chunk.delta_content:
                        text += chunk.delta_content
                        yield AgentEvent(
                            type=EventType.TEXT_DELTA,
                            data={"content": chunk.delta_content},
                        )
                    if chunk.delta_reasoning:
                        reasoning += chunk.delta_reasoning
                    if chunk.delta_tool_calls:
                        tool_calls.extend(chunk.delta_tool_calls)
                    if chunk.usage is not None:
                        step_usage = {
                            "prompt_tokens": chunk.usage.prompt_tokens,
                            "completion_tokens": chunk.usage.completion_tokens,
                            "total_tokens": chunk.usage.total_tokens,
                        }
                        total_tokens += chunk.usage.total_tokens
                    if chunk.finish_reason is not None:
                        finish = chunk.finish_reason
            except Exception as exc:
                # The provider gave up — retries exhausted, bad credentials,
                # malformed request. Report it as an event instead of letting
                # the exception escape, so an SSE transport stays well-formed
                # and the caller learns *why* the turn stopped.
                yield AgentEvent(
                    type=EventType.ERROR,
                    data={
                        "message": f"{type(exc).__name__}: {exc}",
                        "step": step,
                        "retryable": is_transient(exc),
                    },
                )
                return
            last_finish = finish

            if step_usage:
                yield AgentEvent(type=EventType.USAGE, data=step_usage)

            # Append the assistant turn. Tool calls live alongside content
            # because the model may produce both. Convert empty string to
            # None so the wire serializer omits the field entirely.
            messages.append(
                Message(
                    role=Role.ASSISTANT,
                    content=text or None,
                    tool_calls=tool_calls,
                    reasoning_content=reasoning or None,
                )
            )

            if not tool_calls:
                if finish is FinishReason.LENGTH:
                    # The answer hit the output cap mid-sentence. Ask the model
                    # to carry on rather than returning a truncated reply; the
                    # step budget bounds how many times this can happen.
                    messages.append(
                        Message(
                            role=Role.USER,
                            content=self.CONTINUE_AFTER_TRUNCATION,
                        )
                    )
                    yield AgentEvent(
                        type=EventType.RECOVERY,
                        data={"reason": "length", "step": step},
                    )
                    continue
                yield AgentEvent(
                    type=EventType.DONE,
                    data={
                        "reason": finish.value if finish else "stop",
                        "steps": step + 1,
                        "total_tokens": total_tokens,
                    },
                )
                return

            # Execute each tool call and append the result message.
            for call in tool_calls:
                yield AgentEvent(
                    type=EventType.TOOL_CALL,
                    data={
                        "id": call.id,
                        "name": call.name,
                        "arguments": call.arguments,
                    },
                )
                result = self._execute_tool(call, ctx)
                yield AgentEvent(
                    type=EventType.TOOL_RESULT,
                    data={
                        "name": call.name,
                        "content": result.content,
                        "is_error": result.is_error,
                    },
                )
                messages.append(
                    Message(
                        role=Role.TOOL,
                        content=result.content,
                        tool_call_id=call.id,
                    )
                )

        # Exhausted max_steps.
        yield AgentEvent(
            type=EventType.DONE,
            data={
                "reason": "max_steps",
                "steps": self.max_steps,
                "total_tokens": total_tokens,
            },
        )
        if last_finish is not None:
            _ = last_finish  # silence linters

    # ---- tool dispatch ----------------------------------------------------

    def _execute_tool(self, call: Any, ctx: ToolContext) -> ToolResult:
        tool = next((t for t in self.tools if t.name == call.name), None)
        if tool is None:
            return ToolResult(
                content=f"Unknown tool {call.name!r}. Available: "
                f"{[t.name for t in self.tools]}",
                is_error=True,
            )
        try:
            validate_arguments(tool.input_schema, call.arguments)
        except SchemaValidationError as exc:
            return ToolResult(
                content=(
                    f"Invalid arguments for tool {call.name!r}: "
                    f"{'; '.join(exc.errors)}"
                ),
                is_error=True,
            )
        start = time.monotonic()
        try:
            result = tool.execute(call.arguments, ctx)
        except Exception as exc:  # pragma: no cover - defensive
            result = ToolResult(
                content=f"Tool {call.name!r} crashed: {type(exc).__name__}: {exc}",
                is_error=True,
            )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        # We attach timing to the event via a side channel; the loop already
        # emitted TOOL_RESULT with content so we just return.
        _ = elapsed_ms
        return result
