"""Tests for loca.core.recovery — retries and context budgeting.

Everything here is offline: the retry policy is tested with a scripted fake
provider, and the sleep callable is injected so no test ever actually waits.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from loca.core.events import EventType
from loca.core.loop import AgentLoop
from loca.core.recovery import (
    ProviderCallError,
    RetryingProvider,
    count_tokens,
    estimate_tokens,
    is_transient,
    trim_messages,
)
from loca.providers.base import LLMProvider
from loca.providers.types import (
    ChatRequest,
    ChatResponse,
    FinishReason,
    Message,
    Role,
    StreamChunk,
    ToolCall,
)
from loca.tools.base import ToolContext

# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class APIConnectionError(Exception):
    """Name-matched by ``is_transient`` exactly like the openai SDK's class."""


class ScriptedProvider(LLMProvider):
    """Replays one script per call.

    A script is a list of items: exceptions are raised, everything else is
    yielded (or returned, for ``chat``).
    """

    name = "scripted"

    def __init__(self, scripts: list[list[Any]]) -> None:
        self._scripts = list(scripts)
        self.calls = 0
        self.requests: list[ChatRequest] = []

    def _script(self, request: ChatRequest) -> list[Any]:
        self.requests.append(request)
        script = self._scripts[min(self.calls, len(self._scripts) - 1)]
        self.calls += 1
        return script

    def chat(self, request: ChatRequest) -> ChatResponse:
        for item in self._script(request):
            if isinstance(item, BaseException):
                raise item
            return item  # type: ignore[return-value]
        raise AssertionError("script did not contain a response")

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamChunk]:
        for item in self._script(request):
            if isinstance(item, BaseException):
                raise item
            yield item  # type: ignore[misc]


def _response(text: str = "done") -> ChatResponse:
    return ChatResponse(
        message=Message(role=Role.ASSISTANT, content=text),
        finish_reason=FinishReason.STOP,
    )


def _final(text: str = "done") -> StreamChunk:
    return StreamChunk(delta_content=text, finish_reason=FinishReason.STOP)


def _recorder() -> tuple[list[float], Any]:
    slept: list[float] = []
    return slept, slept.append


def _wrapped(scripts: list[list[Any]]) -> tuple[RetryingProvider, ScriptedProvider, list[float]]:
    slept, sleep = _recorder()
    inner = ScriptedProvider(scripts)
    provider = RetryingProvider(
        inner, max_attempts=3, base_delay=1.0, jitter=False, sleep=sleep
    )
    return provider, inner, slept


def _request() -> ChatRequest:
    return ChatRequest(messages=[Message(role=Role.USER, content="hi")], stream=True)


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError("timed out"),
        ConnectionResetError("reset"),
        APIConnectionError("socket closed"),
    ],
)
def test_builtin_and_named_errors_are_transient(exc: BaseException) -> None:
    assert is_transient(exc)


def test_status_code_drives_classification() -> None:
    rate_limited = Exception("slow down")
    rate_limited.status_code = 429  # type: ignore[attr-defined]
    assert is_transient(rate_limited)

    bad_request = Exception("bad schema")
    bad_request.status_code = 400  # type: ignore[attr-defined]
    assert not is_transient(bad_request)


def test_plain_value_error_is_not_transient() -> None:
    assert not is_transient(ValueError("nope"))


def test_provider_call_error_reports_wrapped_classification() -> None:
    """A wrapped transient failure stays transient for the error reporter."""
    assert is_transient(ProviderCallError("gave up", attempts=3, transient=True))
    assert not is_transient(ProviderCallError("bad key", attempts=1, transient=False))


# ---------------------------------------------------------------------------
# retry policy
# ---------------------------------------------------------------------------


def test_chat_retries_then_succeeds() -> None:
    provider, inner, slept = _wrapped(
        [[ConnectionError("flaky")], [ConnectionError("flaky")], [_response("ok")]]
    )
    response = provider.chat(_request())
    assert response.message.content == "ok"
    assert inner.calls == 3
    assert provider.retry_count == 2
    assert slept == [1.0, 2.0], "exponential backoff"


def test_chat_does_not_retry_permanent_errors() -> None:
    provider, inner, slept = _wrapped([[ValueError("bad payload")]])
    with pytest.raises(ValueError, match="bad payload"):
        provider.chat(_request())
    assert inner.calls == 1
    assert slept == []


def test_chat_raises_provider_call_error_when_attempts_exhausted() -> None:
    provider, inner, _ = _wrapped([[ConnectionError("down")]] * 3)
    with pytest.raises(ProviderCallError) as info:
        provider.chat(_request())
    assert info.value.attempts == 3
    assert info.value.transient is True
    assert isinstance(info.value.cause, ConnectionError)
    assert inner.calls == 3


def test_stream_retries_before_first_chunk() -> None:
    provider, inner, _ = _wrapped([[TimeoutError("slow")], [_final("hello")]])
    chunks = list(provider.stream_chat(_request()))
    assert [c.delta_content for c in chunks] == ["hello"]
    assert inner.calls == 2


def test_stream_never_replays_after_output_started() -> None:
    """Re-running would duplicate text the user already saw."""
    provider, inner, _ = _wrapped(
        [[StreamChunk(delta_content="partial"), ConnectionError("dropped")]]
    )
    seen: list[str] = []
    with pytest.raises(ConnectionError):
        for chunk in provider.stream_chat(_request()):
            seen.append(chunk.delta_content)
    assert seen == ["partial"], "output must not be replayed"
    assert inner.calls == 1, "must not have retried"


def test_stream_exhausted_before_output_wraps_error() -> None:
    provider, _, _ = _wrapped([[TimeoutError("slow")]] * 3)
    with pytest.raises(ProviderCallError) as info:
        list(provider.stream_chat(_request()))
    assert info.value.attempts == 3
    assert info.value.transient is True


def test_wrapper_mirrors_inner_name() -> None:
    provider, _, _ = _wrapped([[]])
    assert provider.name == "scripted"
    assert provider.inner is provider.inner  # unwrap is stable


# ---------------------------------------------------------------------------
# token estimation & trimming
# ---------------------------------------------------------------------------


def test_estimate_tokens_ascii_and_cjk() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2
    assert estimate_tokens("你好世界") == 4, "CJK is ~1 token per character"


def test_trim_is_a_noop_when_everything_fits() -> None:
    messages = [
        Message(role=Role.SYSTEM, content="sys"),
        Message(role=Role.USER, content="hello"),
    ]
    outcome = trim_messages(messages, max_tokens=10_000)
    assert not outcome.trimmed
    assert outcome.dropped == 0
    assert outcome.messages == messages
    assert outcome.estimated_tokens == count_tokens(messages)


def test_trim_preserves_system_and_drops_oldest() -> None:
    messages = [
        Message(role=Role.SYSTEM, content="sys"),
        Message(role=Role.USER, content="old question " * 20),
        Message(role=Role.ASSISTANT, content="old answer " * 20),
        Message(role=Role.USER, content="new question"),
    ]
    outcome = trim_messages(messages, max_tokens=12, keep_recent=1)
    assert outcome.trimmed
    assert outcome.messages[0].role is Role.SYSTEM
    assert outcome.messages[-1].content == "new question"
    assert outcome.dropped == 2


def test_trim_drops_orphan_tool_messages() -> None:
    """A tool result whose parent assistant call was trimmed must go too."""
    messages = [
        Message(role=Role.SYSTEM, content="sys"),
        Message(role=Role.USER, content="q1"),
        Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "a"})],
        ),
        Message(role=Role.TOOL, content="file contents", tool_call_id="c1"),
        Message(role=Role.USER, content="q2"),
    ]
    outcome = trim_messages(messages, max_tokens=1, keep_recent=2)
    assert outcome.dropped_orphan_tool_messages == 1
    assert all(m.role is not Role.TOOL for m in outcome.messages)
    assert outcome.messages[-1].content == "q2"


def test_trim_keeps_recent_messages_even_when_over_budget() -> None:
    messages = [
        Message(role=Role.SYSTEM, content="sys"),
        Message(role=Role.USER, content="huge " * 500),
        Message(role=Role.ASSISTANT, content="huge " * 500),
    ]
    outcome = trim_messages(messages, max_tokens=1, keep_recent=2)
    assert [m.role for m in outcome.messages] == [Role.SYSTEM, Role.USER, Role.ASSISTANT]


def test_trim_never_empties_the_conversation() -> None:
    messages = [Message(role=Role.USER, content="only turn")]
    outcome = trim_messages(messages, max_tokens=1, keep_recent=1)
    assert outcome.messages == messages


def test_trim_rejects_non_positive_budget() -> None:
    with pytest.raises(ValueError):
        trim_messages([], max_tokens=0)


# ---------------------------------------------------------------------------
# loop integration
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx(tmp_path) -> ToolContext:  # type: ignore[no-untyped-def]
    return ToolContext(workspace=tmp_path, session_id="recovery", step_index=0)


def test_loop_retries_transient_failure_then_finishes(ctx: ToolContext) -> None:
    inner = ScriptedProvider(
        [[ConnectionError("gateway hiccup")], [_final("recovered")]]
    )
    loop = AgentLoop(
        provider=inner,
        tools=[],
        system_prompt="sys",
        retries=2,
        context_token_budget=None,
        sleep=lambda _: None,
    )
    events = list(loop.run(ctx, user_message="hi"))
    text = "".join(e.data["content"] for e in events if e.type is EventType.TEXT_DELTA)
    assert text == "recovered"
    assert EventType.ERROR not in [e.type for e in events]
    assert inner.calls == 2


def test_loop_surfaces_permanent_error_as_event(ctx: ToolContext) -> None:
    inner = ScriptedProvider([[ValueError("bad request body")]])
    loop = AgentLoop(
        provider=inner,
        tools=[],
        system_prompt="sys",
        retries=2,
        context_token_budget=None,
        sleep=lambda _: None,
    )
    events = list(loop.run(ctx, user_message="hi"))
    errors = [e for e in events if e.type is EventType.ERROR]
    assert len(errors) == 1
    assert "ValueError" in errors[0].data["message"]
    assert errors[0].data["retryable"] is False
    # The stream still ends cleanly — no exception escaped the generator.
    assert EventType.DONE not in [e.type for e in events]

    # A retry must not have been attempted for a 4xx-style failure.
    assert inner.calls == 1


def test_loop_reports_exhausted_transient_retries(ctx: ToolContext) -> None:
    inner = ScriptedProvider([[TimeoutError("timeout")]] * 5)
    loop = AgentLoop(
        provider=inner,
        tools=[],
        system_prompt="sys",
        retries=1,
        context_token_budget=None,
        sleep=lambda _: None,
    )
    events = list(loop.run(ctx, user_message="hi"))
    errors = [e for e in events if e.type is EventType.ERROR]
    assert len(errors) == 1
    assert errors[0].data["retryable"] is True
    assert inner.calls == 2, "original attempt + one retry"


def test_loop_continues_when_reply_is_truncated(ctx: ToolContext) -> None:
    """``finish_reason=length`` must resume, not return half an answer."""
    inner = ScriptedProvider(
        [
            [StreamChunk(delta_content="part 1 ", finish_reason=FinishReason.LENGTH)],
            [StreamChunk(delta_content="part 2", finish_reason=FinishReason.STOP)],
        ]
    )
    loop = AgentLoop(
        provider=inner,
        tools=[],
        system_prompt="sys",
        retries=0,
        context_token_budget=None,
    )
    events = list(loop.run(ctx, user_message="tell me a long story"))
    text = "".join(e.data["content"] for e in events if e.type is EventType.TEXT_DELTA)

    assert text == "part 1 part 2", "the truncated reply must be continued"
    assert [e.type for e in events].count(EventType.RECOVERY) == 1
    assert [e.type for e in events][-1] is EventType.DONE

    # The follow-up request asks the model to pick up where it stopped.
    follow_up = inner.requests[1].messages[-1]
    assert follow_up.role is Role.USER
    assert "cut off" in (follow_up.content or "")


def test_loop_emits_context_trimmed_event(ctx: ToolContext) -> None:
    history = [
        Message(role=Role.USER, content="question " * 30),
        Message(role=Role.ASSISTANT, content="answer " * 30),
        Message(role=Role.USER, content="follow up"),
        Message(role=Role.ASSISTANT, content="reply"),
    ]
    inner = ScriptedProvider([[_final("ok")]])
    loop = AgentLoop(
        provider=inner,
        tools=[],
        system_prompt="sys",
        context_token_budget=8,
        keep_recent_messages=1,
        retries=0,
    )
    events = list(loop.run(ctx, user_message="next", history=history))
    trims = [e for e in events if e.type is EventType.CONTEXT_TRIMMED]
    assert len(trims) == 1
    assert trims[0].data["dropped"] > 0
    assert trims[0].data["budget"] == 8
    # The provider actually received the trimmed conversation: system + the
    # newest turn only (the long history was dropped).
    sent = inner.requests[0].messages
    assert [m.role for m in sent] == [Role.SYSTEM, Role.USER]
    assert sent[-1].content == "next"
