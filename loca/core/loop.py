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

Durability (Week 4):

- A :class:`~loca.observability.checkpoint.CheckpointManager` can be attached to
  snapshot every file a tool is about to touch, so a bad edit is undoable.
- A :class:`~loca.core.context.ContextManager` can be attached to summarize old
  turns instead of dropping them when the context window fills up.
- Both are optional injections: the loop keeps working with neither, and the
  caller decides what a turn costs.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Sequence
from typing import TYPE_CHECKING, Any

from loca.core.context import ContextManager
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

if TYPE_CHECKING:  # pragma: no cover - typing only
    # The loop needs "something that can capture a snapshot", not the concrete
    # manager: it calls exactly one method on it (``capture``). Importing the
    # class at runtime made core depend on observability while observability
    # already depends on core's event model — a cycle held together by an
    # annotation. Same reason the provider layer talks to an ABC.
    from loca.observability.checkpoint import CheckpointManager

# 64k tokens is DeepSeek's window; keep headroom for the model's own reply.
DEFAULT_TOKEN_BUDGET = 48_000


class AgentLoop:
    """Drive a multi-step agent conversation."""

    #: Last-resort prompt for a loop built without one. Deliberately says
    #: nothing about coding, Windows, or a particular toolset: that is
    #: *policy*, and policy belongs to an agent definition — see
    #: :data:`loca.agents.CODING_AGENT`, which every entry point in this
    #: project uses instead of relying on this.
    DEFAULT_SYSTEM_PROMPT = (
        "You are a helpful assistant. Use the tools available to you when they "
        "help answer the user's request. Be concise."
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
        checkpoint_manager: CheckpointManager | None = None,
        context_manager: ContextManager | None = None,
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
            Ignored when ``context_manager`` is given — that object owns the
            budget (and can summarize instead of dropping).
        keep_recent_messages:
            Messages that survive a trim regardless of the budget.
        checkpoint_manager:
            When attached, every file-mutating tool call is preceded by a
            snapshot of its targets. ``None`` means no undo history.
        context_manager:
            When attached, takes over context budgeting entirely.
        sleep:
            Injected so tests can run the retry path without real delays.
        """
        self._raw_provider = provider
        #: Transient failures the retry wrapper has absorbed. The wrapper has
        #: always offered this hook; nothing consumed it, so every "retries"
        #: column in a report was really counting continuations.
        self._retry_notes: list[str] = []
        self.provider: LLMProvider = (
            RetryingProvider(
                provider,
                max_attempts=retries + 1,
                sleep=sleep,
                on_retry=self._note_retry,
            )
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
        self.checkpoint_manager = checkpoint_manager
        self.context_manager = context_manager
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
            # Session-global step counter, advanced by the loop (not the caller
            # and not the tool) so checkpoints and traces share one monotonic
            # numbering across every turn of a session. It is announced with
            # the step so a trace can be lined up with `loca rollback <step>`.
            global_step = ctx.step_index
            ctx.step_index += 1
            yield AgentEvent(
                type=EventType.STEP_START,
                data={"step": step, "global_step": global_step},
            )

            # Keep the request inside the model's context window. The estimate
            # is cheap and deliberately conservative; a wrong estimate only
            # costs some old history, never a failed call.
            yield from self._compact_events(messages)

            request = ChatRequest(
                # Snapshot the list: we keep appending tool results to
                # ``messages`` after the call, and an observer holding the
                # request (a trace recorder, a test) must see what was
                # actually sent, not the later mutation.
                messages=list(messages),
                tools=tool_schemas,
                model=self.model,
                temperature=self.temperature,
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
                    if self._retry_notes:
                        # A retry only ever happens before the first chunk, so
                        # surface it ahead of anything the model produced.
                        yield from self._retry_events(step)
                    if chunk.delta_content:
                        text += chunk.delta_content
                        yield AgentEvent(
                            type=EventType.TEXT_DELTA,
                            data={"content": chunk.delta_content},
                        )
                    if chunk.delta_reasoning:
                        reasoning += chunk.delta_reasoning
                        # Same channel as the visible reply — it is a streamed
                        # delta either way — but a separate key, so the trace
                        # can record what the model was thinking without mixing
                        # it into the answer. Emitted only when there is
                        # something to say: a consumer that renders `content`
                        # never gets an empty bubble.
                        yield AgentEvent(
                            type=EventType.TEXT_DELTA,
                            data={"content": "", "reasoning": chunk.delta_reasoning},
                        )
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
                # Flush first: the retries that were absorbed before the final
                # failure belong to this step, and a trace should say so.
                yield from self._retry_events(step)
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
                checkpoint = self._capture_checkpoint(call, ctx, step=global_step)
                if checkpoint is not None:
                    yield checkpoint
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

    # ---- context & checkpoints --------------------------------------------

    def _compact_events(self, messages: list[Message]) -> Iterator[AgentEvent]:
        """Shrink ``messages`` in place if it overflows the window.

        Two strategies, in order of preference (see
        :class:`~loca.core.context.ContextManager`): fold old turns into a
        summary, or — when no summarizer is attached — drop them. Either way the
        list is mutated in place so ``last_transcript`` stays live.
        """
        if self.context_manager is not None:
            outcome = self.context_manager.fit(messages)
            if not outcome.trimmed:
                return
            messages[:] = outcome.messages
            if outcome.summarized:
                yield AgentEvent(
                    type=EventType.CONTEXT_SUMMARIZED,
                    data={
                        "summarized": outcome.summarized_messages,
                        "dropped": outcome.dropped,
                        "summary_tokens": outcome.summary_tokens,
                        "estimated_tokens": outcome.estimated_tokens,
                        "budget": outcome.budget,
                    },
                )
            else:
                yield AgentEvent(
                    type=EventType.CONTEXT_TRIMMED,
                    data={
                        "dropped": outcome.dropped,
                        "estimated_tokens": outcome.estimated_tokens,
                        "budget": outcome.budget,
                    },
                )
            return

        if self.context_token_budget is None:
            return
        outcome = trim_messages(
            messages,
            max_tokens=self.context_token_budget,
            keep_recent=self.keep_recent_messages,
        )
        if outcome.trimmed:
            messages[:] = outcome.messages
            yield AgentEvent(
                type=EventType.CONTEXT_TRIMMED,
                data={
                    "dropped": outcome.dropped,
                    "estimated_tokens": outcome.estimated_tokens,
                    "budget": self.context_token_budget,
                },
            )

    def compact(self) -> bool:
        """Summarize the current transcript on demand (backs ``/compact``).

        Returns ``True`` when the transcript actually changed. Unlike
        :meth:`_compact_events` this runs even when the conversation still fits,
        because the user explicitly asked for it.
        """
        if self.context_manager is None or not self.last_transcript:
            return False
        messages, outcome = self.context_manager.compact(self.last_transcript)
        if outcome is None:
            return False
        self.last_transcript[:] = messages
        return True

    # ---- transient-failure reporting --------------------------------------

    def _note_retry(self, attempt: int, delay: float, exc: BaseException) -> None:
        """Record one absorbed transient failure (the wrapper's ``on_retry``)."""
        self._retry_notes.append(
            f"attempt {attempt}, backoff {delay:.2f}s: {type(exc).__name__}: {exc}"
        )

    def _retry_events(self, step: int) -> Iterator[AgentEvent]:
        """Surface the retries absorbed since the last flush, then forget them."""
        notes, self._retry_notes = self._retry_notes, []
        for note in notes:
            yield AgentEvent(
                type=EventType.RECOVERY,
                data={"reason": "provider_retry", "detail": note, "step": step},
            )

    def _capture_checkpoint(
        self, call: Any, ctx: ToolContext, *, step: int
    ) -> AgentEvent | None:
        """Snapshot the files this call is about to touch, if anything does."""
        if self.checkpoint_manager is None:
            return None
        checkpoint = self.checkpoint_manager.capture(
            session_id=ctx.session_id,
            step=step,
            tool=call.name,
            arguments=call.arguments if isinstance(call.arguments, dict) else {},
            workspace=ctx.workspace,
        )
        if checkpoint is None:
            return None
        return AgentEvent(
            type=EventType.CHECKPOINT,
            data={
                "step": step,
                "tool": call.name,
                "files": [s.path for s in checkpoint.snapshots],
                "restorable": all(s.restorable for s in checkpoint.snapshots),
            },
        )

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
