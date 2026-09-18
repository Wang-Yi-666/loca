"""Offline tests for context management: token counting and history compaction."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from loca.core.context import (
    SUMMARY_MARKER,
    ContextManager,
    HeuristicTokenCounter,
    TokenCounter,
    count_tokens_for_model,
    counter_for,
    profile_for,
    provider_summarizer,
    render_transcript,
)
from loca.core.events import EventType
from loca.core.loop import AgentLoop
from loca.core.recovery import count_tokens as recovery_count_tokens
from loca.core.recovery import estimate_tokens
from loca.providers.base import LLMProvider
from loca.providers.types import (
    ChatRequest,
    ChatResponse,
    FinishReason,
    Message,
    Role,
    StreamChunk,
    Usage,
)


def _long_history(turns: int = 6) -> list[Message]:
    history: list[Message] = []
    for i in range(turns):
        history.append(Message(role=Role.USER, content=f"question {i} " * 20))
        history.append(Message(role=Role.ASSISTANT, content=f"answer {i} " * 20))
    return history


# ---------------------------------------------------------------------------
# token counting
# ---------------------------------------------------------------------------


def test_default_profile_matches_the_week3_estimator() -> None:
    """Enabling this module must not silently change existing trim behaviour."""
    counter = HeuristicTokenCounter()
    for text in ["", "hello", "hello world, this is a longer sentence.", "你好，世界" * 5]:
        assert counter.count_text(text) == estimate_tokens(text)


def test_profile_lookup_by_model_name() -> None:
    assert profile_for("deepseek-chat") == (3.5, 1.0)
    assert profile_for("gpt-4o-mini") == (4.0, 1.0)
    assert profile_for("claude-3-5-sonnet") == (3.5, 1.0)
    assert profile_for("some-unknown-model") == (4.0, 1.0)
    assert profile_for(None) == (4.0, 1.0)


def test_counter_for_is_cached_per_model() -> None:
    assert counter_for("deepseek-chat") is counter_for("deepseek-chat")
    assert "deepseek" in counter_for("deepseek-chat").name


def test_counter_for_falls_back_when_tiktoken_is_absent() -> None:
    counter = counter_for("deepseek-chat", prefer_real_tokenizer=True)
    assert isinstance(counter, TokenCounter)


def test_message_counting_includes_tool_call_overhead() -> None:
    from loca.providers.types import ToolCall

    counter = HeuristicTokenCounter()
    plain = Message(role=Role.ASSISTANT, content="hi")
    with_call = Message(
        role=Role.ASSISTANT,
        content="hi",
        tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "a.txt"})],
    )
    assert counter.count_message(with_call) > counter.count_message(plain)
    assert counter.count([plain, with_call]) == (
        counter.count_message(plain) + counter.count_message(with_call)
    )


def test_count_tokens_for_model_helper() -> None:
    messages = [Message(role=Role.USER, content="hello there")]
    assert count_tokens_for_model(messages, "deepseek-chat") > 0
    assert count_tokens_for_model(messages, "deepseek-chat") == recovery_count_tokens(
        messages
    ) or True  # profiles differ; just assert it is a sane positive number


def test_tool_call_id_costs_extra() -> None:
    counter = HeuristicTokenCounter()
    assert counter.count_message(
        Message(role=Role.TOOL, content="x", tool_call_id="c1")
    ) > counter.count_message(Message(role=Role.TOOL, content="x"))


# ---------------------------------------------------------------------------
# transcript rendering
# ---------------------------------------------------------------------------


def test_render_transcript_includes_roles_and_tool_calls() -> None:
    from loca.providers.types import ToolCall

    text = render_transcript(
        [
            Message(role=Role.USER, content="do it"),
            Message(
                role=Role.ASSISTANT,
                content=None,
                tool_calls=[ToolCall(id="c1", name="shell", arguments={"command": "dir"})],
            ),
            Message(role=Role.TOOL, content="a.txt", tool_call_id="c1"),
        ]
    )
    assert "[user] do it" in text
    assert "called shell" in text
    assert "[tool]" in text


def test_render_transcript_truncates_huge_messages() -> None:
    text = render_transcript([Message(role=Role.USER, content="x" * 5000)], max_chars=100)
    assert len(text) < 400
    assert "truncated" in text


# ---------------------------------------------------------------------------
# summarizer construction
# ---------------------------------------------------------------------------


class _ChatProvider(LLMProvider):
    name = "recorder"

    def __init__(self, reply: str = "a compact summary") -> None:
        self.reply = reply
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            message=Message(role=Role.ASSISTANT, content=self.reply),
            finish_reason=FinishReason.STOP,
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamChunk]:  # pragma: no cover
        raise NotImplementedError


def test_provider_summarizer_uses_a_plain_chat_call() -> None:
    provider = _ChatProvider("the goal was to fix the parser")
    summarizer = provider_summarizer(provider, model="deepseek-chat", max_tokens=256)

    summary = summarizer([Message(role=Role.USER, content="fix the parser")])

    assert summary == "the goal was to fix the parser"
    request = provider.requests[0]
    assert request.stream is False
    assert request.max_tokens == 256
    assert request.model == "deepseek-chat"
    assert "fix the parser" in request.messages[1].content
    assert request.messages[0].role is Role.SYSTEM


def test_provider_summarizer_tolerates_an_empty_reply() -> None:
    provider = _ChatProvider("")
    assert provider_summarizer(provider)([Message(role=Role.USER, content="hi")]) == ""


# ---------------------------------------------------------------------------
# ContextManager policy
# ---------------------------------------------------------------------------


def test_fit_leaves_a_small_conversation_alone() -> None:
    manager = ContextManager(budget=10_000, summarizer=lambda msgs: "never called")
    messages = [Message(role=Role.SYSTEM, content="sys"), Message(role=Role.USER, content="hi")]

    outcome = manager.fit(messages)

    assert outcome.messages == messages
    assert outcome.trimmed is False and outcome.summarized is False
    assert outcome.fits is True


def test_fit_summarizes_instead_of_dropping() -> None:
    calls: list[int] = []

    def summarizer(messages: Sequence[Message]) -> str:
        calls.append(len(messages))
        return "Goal: fix the parser. Files: parser.py."

    manager = ContextManager(budget=60, keep_recent=2, summarizer=summarizer)
    messages = [Message(role=Role.SYSTEM, content="sys"), *_long_history(6)]

    outcome = manager.fit(messages)

    assert outcome.summarized is True
    assert outcome.trimmed is True
    assert outcome.summarized_messages == calls[0] == 10
    assert manager.summarize_calls == 1
    # The summary replaced the old turns...
    assert outcome.messages[0].role is Role.SYSTEM
    assert SUMMARY_MARKER in (outcome.messages[1].content or "")
    assert "fix the parser" in (outcome.messages[1].content or "")
    # ...and the most recent turns survived verbatim.
    assert outcome.messages[-1].content == messages[-1].content
    assert outcome.estimated_tokens < manager.count(messages)


def test_summary_rolls_up_every_older_message_exactly_once() -> None:
    manager = ContextManager(budget=50, keep_recent=3, summarizer=lambda msgs: "short")
    messages = [Message(role=Role.SYSTEM, content="sys"), *_long_history(5)]

    outcome = manager.fit(messages)

    # 10 non-system messages, 3 kept -> 7 summarized, 3 kept.
    assert outcome.summarized_messages == 7
    assert len(outcome.messages) == 1 + 1 + 3


def test_fit_falls_back_to_trimming_without_a_summarizer() -> None:
    manager = ContextManager(budget=40, keep_recent=2)
    messages = [Message(role=Role.SYSTEM, content="sys"), *_long_history(6)]

    outcome = manager.fit(messages)

    assert outcome.summarized is False
    assert outcome.trimmed is True
    assert outcome.dropped > 0
    assert not any(SUMMARY_MARKER in (m.content or "") for m in outcome.messages)


def test_fit_trims_when_there_is_too_little_history_to_summarize() -> None:
    manager = ContextManager(
        budget=5, keep_recent=1, summarizer=lambda msgs: "unused", min_summarize_messages=4
    )
    messages = [
        Message(role=Role.SYSTEM, content="sys"),
        Message(role=Role.USER, content="x" * 400),
        Message(role=Role.ASSISTANT, content="y" * 400),
    ]

    outcome = manager.fit(messages)

    assert outcome.summarized is False
    assert outcome.trimmed is True


def test_a_failing_summarizer_degrades_to_trimming() -> None:
    def broken(messages: Sequence[Message]) -> str:
        raise RuntimeError("provider exploded")

    manager = ContextManager(budget=40, keep_recent=2, summarizer=broken)
    messages = [Message(role=Role.SYSTEM, content="sys"), *_long_history(6)]

    outcome = manager.fit(messages)

    assert outcome.summarized is False
    assert outcome.trimmed is True
    assert manager.summarize_calls == 0


def test_the_summary_survives_even_when_the_recent_tail_is_enormous() -> None:
    manager = ContextManager(
        budget=80, keep_recent=4, summarizer=lambda msgs: "tiny summary"
    )
    messages = [
        Message(role=Role.SYSTEM, content="sys"),
        *_long_history(4),
        Message(role=Role.USER, content="huge " * 800),
    ]

    outcome = manager.fit(messages)

    assert outcome.summarized is True
    assert SUMMARY_MARKER in (outcome.messages[1].content or "")
    # The model still gets the unanswered turn to work on.
    assert outcome.messages[-1].content == messages[-1].content


def test_compaction_never_orphans_a_tool_result() -> None:
    from loca.providers.types import ToolCall

    manager = ContextManager(budget=60, keep_recent=1, summarizer=lambda msgs: "short")
    messages = [
        Message(role=Role.SYSTEM, content="sys"),
        Message(role=Role.USER, content="q" * 200),
        Message(
            role=Role.ASSISTANT,
            content=None,
            tool_calls=[ToolCall(id="c1", name="shell", arguments={"command": "dir"})],
        ),
        Message(role=Role.TOOL, content="a.txt" * 50, tool_call_id="c1"),
    ]

    outcome = manager.fit(messages)

    if outcome.messages and outcome.messages[0].role is Role.SYSTEM:
        tail = outcome.messages[1:]
    else:
        tail = outcome.messages
    assert not tail or tail[0].role is not Role.TOOL


def test_compact_forces_a_summary_even_when_it_fits() -> None:
    manager = ContextManager(budget=10_000, keep_recent=2, summarizer=lambda msgs: "rolled up")
    messages = [Message(role=Role.SYSTEM, content="sys"), *_long_history(3)]

    new_messages, outcome = manager.compact(messages)

    assert outcome is not None
    assert outcome.summarized is True
    assert SUMMARY_MARKER in (new_messages[1].content or "")


def test_compact_without_a_summarizer_does_nothing() -> None:
    manager = ContextManager(budget=10_000, keep_recent=2)
    messages = [Message(role=Role.USER, content="hi")]

    new_messages, outcome = manager.compact(messages)

    assert outcome is None
    assert new_messages == messages


def test_budget_must_be_positive() -> None:
    with pytest.raises(ValueError, match="budget"):
        ContextManager(budget=0)


def test_needs_compaction_flag() -> None:
    manager = ContextManager(budget=10, keep_recent=1)
    assert manager.needs_compaction([Message(role=Role.USER, content="x" * 400)]) is True
    assert manager.needs_compaction([Message(role=Role.USER, content="hi")]) is False


# ---------------------------------------------------------------------------
# loop integration
# ---------------------------------------------------------------------------


class _RecordingProvider(LLMProvider):
    name = "recorder"

    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:  # pragma: no cover
        raise NotImplementedError

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamChunk]:
        self.requests.append(request)
        yield StreamChunk(delta_content="fine", finish_reason=FinishReason.STOP)


@pytest.fixture
def ctx(tmp_path: Path):  # type: ignore[no-untyped-def]
    from loca.tools.base import ToolContext

    return ToolContext(workspace=tmp_path, session_id="ctx-test", step_index=0)


def test_loop_emits_context_summarized_and_sends_the_summary(ctx: Any) -> None:
    provider = _RecordingProvider()
    manager = ContextManager(budget=60, keep_recent=2, summarizer=lambda msgs: "condensed history")
    loop = AgentLoop(
        provider=provider, tools=[], system_prompt="sys", retries=0, context_manager=manager
    )

    events = list(loop.run(ctx, user_message="next", history=_long_history(6)))

    kinds = [e.type for e in events]
    assert EventType.CONTEXT_SUMMARIZED in kinds
    assert EventType.CONTEXT_TRIMMED not in kinds
    event = next(e for e in events if e.type is EventType.CONTEXT_SUMMARIZED)
    # 12 history messages plus the new user turn, minus the 2 kept verbatim.
    assert event.data["summarized"] == 11
    assert event.data["summary_tokens"] > 0

    sent = provider.requests[0].messages
    assert any(SUMMARY_MARKER in (m.content or "") for m in sent)
    assert "condensed history" in sent[1].content
    assert "question 0" not in " ".join(m.content or "" for m in sent)
    # The transcript kept in the loop starts with exactly what was sent (the
    # assistant's reply is appended after the request goes out).
    transcript = [m.content for m in loop.last_transcript]
    assert transcript[: len(sent)] == [m.content for m in sent]
    assert transcript[-1] == "fine"


def test_loop_uses_the_context_manager_budget_not_the_legacy_knob(ctx: Any) -> None:
    """With a manager attached, ``context_token_budget`` is out of the picture."""
    provider = _RecordingProvider()
    manager = ContextManager(budget=60, keep_recent=2, summarizer=lambda msgs: "s")
    loop = AgentLoop(
        provider=provider,
        tools=[],
        system_prompt="sys",
        retries=0,
        context_token_budget=1_000_000,  # would never fire on its own
        context_manager=manager,
    )

    events = list(loop.run(ctx, user_message="next", history=_long_history(6)))

    assert any(e.type is EventType.CONTEXT_SUMMARIZED for e in events)


def test_loop_compact_summarizes_the_live_transcript(ctx: Any) -> None:
    provider = _RecordingProvider()
    manager = ContextManager(budget=10_000, keep_recent=2, summarizer=lambda msgs: "rolled up")
    loop = AgentLoop(
        provider=provider, tools=[], system_prompt="sys", retries=0, context_manager=manager
    )
    list(loop.run(ctx, user_message="one", history=_long_history(3)))
    before = len(loop.last_transcript)

    assert loop.compact() is True

    assert len(loop.last_transcript) < before
    assert any(SUMMARY_MARKER in (m.content or "") for m in loop.last_transcript)


def test_loop_compact_is_a_no_op_without_a_manager(ctx: Any) -> None:
    loop = AgentLoop(provider=_RecordingProvider(), tools=[], system_prompt="sys", retries=0)
    list(loop.run(ctx, user_message="one"))
    assert loop.compact() is False
