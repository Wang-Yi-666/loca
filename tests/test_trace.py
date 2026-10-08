"""Tests for the Week-5 trace recorder.

Traces are built by *observing* the loop's event stream, so most of these tests
drive a real :class:`~loca.core.loop.AgentLoop` with a scripted provider and
then assert on what landed in the database and in the JSONL mirror. Nothing
hits the network.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from loca.core.events import AgentEvent, EventType
from loca.core.loop import AgentLoop
from loca.observability.storage import SessionStore
from loca.observability.trace import (
    StepTrace,
    ToolCallRecord,
    ToolResultRecord,
    TraceRecorder,
    default_trace_dir,
    load_steps,
    read_jsonl,
    trace_jsonl_path,
)
from loca.providers.base import LLMProvider
from loca.providers.types import (
    ChatRequest,
    ChatResponse,
    FinishReason,
    StreamChunk,
    ToolCall,
    Usage,
)
from loca.tools.base import Tool, ToolContext, ToolResult

# ---- fixtures and helpers ---------------------------------------------------


class ScriptedProvider(LLMProvider):
    """Yields a scripted response per model call."""

    name = "scripted"

    def __init__(self, scripts: list[list[StreamChunk]]) -> None:
        self._scripts = list(scripts)
        self._call = 0
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:  # pragma: no cover
        raise NotImplementedError

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamChunk]:
        self.requests.append(request)
        script = self._scripts[min(self._call, len(self._scripts) - 1)]
        self._call += 1
        yield from script


class EchoTool(Tool):
    name = "echo"
    description = "Echo text back."
    input_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    }

    def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult(content=f"echo: {arguments['text']}")


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SessionStore]:
    with SessionStore(tmp_path / "sessions.db") as opened:
        opened.create_session("s1", workspace=tmp_path)
        yield opened


def _tracer(
    store: SessionStore | None,
    *,
    loop: AgentLoop | None = None,
    **kwargs: Any,
) -> TraceRecorder:
    """A recorder with the noisy defaults filled in."""
    kwargs.setdefault("jsonl", False)
    if loop is not None:
        kwargs.setdefault("prompt_source", lambda: loop.last_transcript)
    return TraceRecorder("s1", store=store, **kwargs)


def _event(kind: EventType, **data: Any) -> AgentEvent:
    return AgentEvent(type=kind, data=data)


def _text(text: str, *, usage: Usage | None = None) -> list[StreamChunk]:
    return [StreamChunk(delta_content=text, finish_reason=FinishReason.STOP, usage=usage)]


def _call(name: str, args: dict[str, Any], call_id: str = "c1") -> list[StreamChunk]:
    return [
        StreamChunk(
            delta_tool_calls=[ToolCall(id=call_id, name=name, arguments=args)],
            finish_reason=FinishReason.TOOL_USE,
        )
    ]


def _loop(scripts: list[list[StreamChunk]], tools: list[Tool] | None = None) -> AgentLoop:
    return AgentLoop(
        provider=ScriptedProvider(scripts),
        tools=tools or [],
        context_token_budget=None,
    )


def _run(loop: AgentLoop, ctx: ToolContext, recorder: TraceRecorder, message: str = "hi") -> None:
    for event in loop.run(ctx, user_message=message):
        recorder.observe(event)


# ---- recording from a real loop ---------------------------------------------


def test_records_one_step_per_model_call(workspace: Path, store: SessionStore) -> None:
    """A tool-calling turn makes two model calls; a plain reply makes one."""
    loop = _loop([_call("echo", {"text": "hi"}), _text("bye")], tools=[EchoTool()])
    ctx = ToolContext(workspace=workspace, session_id="s1", step_index=0)
    recorder = _tracer(store, loop=loop)

    _run(loop, ctx, recorder)

    assert len(recorder.steps) == 2
    assert [s.step for s in recorder.steps] == [0, 1]
    assert recorder.steps[0].text == ""
    assert recorder.steps[1].text == "bye"
    # The trailing step is the one the loop announced DONE for.
    assert recorder.steps[-1].finish_reason == "stop"
    assert recorder.steps[0].finish_reason == "tool_use"


def test_a_final_reply_is_a_single_step(workspace: Path, store: SessionStore) -> None:
    loop = _loop([_text("no tools needed")])
    ctx = ToolContext(workspace=workspace, session_id="s1", step_index=0)
    recorder = _tracer(store)

    _run(loop, ctx, recorder)

    assert len(recorder.steps) == 1
    assert recorder.steps[0].finish_reason == "stop"


def test_session_global_step_number_is_used(workspace: Path, store: SessionStore) -> None:
    """Trace steps must line up with `loca rollback <session> <step>`."""
    loop = _loop([_text("a")])
    ctx = ToolContext(workspace=workspace, session_id="s1", step_index=7)
    recorder = _tracer(store)

    _run(loop, ctx, recorder)

    assert [s.step for s in recorder.steps] == [7]


def test_prompt_is_sampled_from_the_live_transcript(workspace: Path, store: SessionStore) -> None:
    loop = _loop([_text("ok")])
    ctx = ToolContext(workspace=workspace, session_id="s1", step_index=0)
    recorder = _tracer(store, loop=loop)

    _run(loop, ctx, recorder, message="count the files")

    step = recorder.steps[0]
    assert step.prompt_sampled is True
    # system prompt + the user turn
    assert step.prompt_messages == 2
    assert "count the files" in step.prompt_tail
    assert step.prompt_tail.startswith("[user]")
    assert step.prompt_chars > 0


def test_prompt_is_marked_unsampled_without_a_source(workspace: Path, store: SessionStore) -> None:
    loop = _loop([_text("ok")])
    ctx = ToolContext(workspace=workspace, session_id="s1", step_index=0)
    recorder = _tracer(store)

    _run(loop, ctx, recorder)

    step = recorder.steps[0]
    assert step.prompt_sampled is False
    assert step.prompt_messages == 0


def test_tool_calls_and_results_are_paired(workspace: Path, store: SessionStore) -> None:
    loop = _loop([_call("echo", {"text": "hi"}), _text("done")], tools=[EchoTool()])
    ctx = ToolContext(workspace=workspace, session_id="s1", step_index=0)
    recorder = _tracer(store)

    _run(loop, ctx, recorder)

    first = recorder.steps[0]
    assert first.tool_names == ["echo"]
    assert first.tool_calls[0].arguments == {"text": "hi"}
    assert first.tool_results[0].preview == "echo: hi"
    assert first.tool_results[0].chars == len("echo: hi")
    assert first.tool_results[0].is_error is False
    assert first.finish_reason == "tool_use"
    assert len(recorder.steps) == 2


def test_tool_errors_are_counted(workspace: Path, store: SessionStore) -> None:
    loop = _loop([_call("nope", {}), _text("recovered")], tools=[EchoTool()])
    ctx = ToolContext(workspace=workspace, session_id="s1", step_index=0)
    recorder = _tracer(store)

    _run(loop, ctx, recorder)

    assert recorder.steps[0].tool_errors == 1
    assert recorder.steps[0].tool_results[0].is_error is True


def test_usage_is_recorded_per_step(workspace: Path, store: SessionStore) -> None:
    usage = Usage(prompt_tokens=100, completion_tokens=20, total_tokens=120)
    loop = _loop([_text("hi", usage=usage)])
    ctx = ToolContext(workspace=workspace, session_id="s1", step_index=0)
    recorder = _tracer(store)

    _run(loop, ctx, recorder)

    step = recorder.steps[0]
    assert (step.prompt_tokens, step.completion_tokens, step.total_tokens) == (100, 20, 120)


def test_provider_error_closes_the_step_as_failed(workspace: Path, store: SessionStore) -> None:
    class Boom(LLMProvider):
        name = "boom"

        def chat(self, request: ChatRequest) -> ChatResponse:  # pragma: no cover
            raise NotImplementedError

        def stream_chat(self, request: ChatRequest) -> Iterator[StreamChunk]:
            raise RuntimeError("upstream exploded")
            yield  # pragma: no cover

    loop = AgentLoop(provider=Boom(), tools=[], retries=0, context_token_budget=None)
    ctx = ToolContext(workspace=workspace, session_id="s1", step_index=0)
    recorder = _tracer(store)

    _run(loop, ctx, recorder)

    step = recorder.steps[0]
    assert step.failed is True
    assert "upstream exploded" in (step.error or "")
    assert step.finish_reason == "error"


def test_checkpoint_paths_and_context_notes_are_kept(store: SessionStore) -> None:
    """The recorder is a pure event sink — feed it events directly."""
    recorder = _tracer(store)
    recorder.observe(_event(EventType.STEP_START, step=0, global_step=3))
    recorder.observe(
        _event(
            EventType.CONTEXT_SUMMARIZED,
            summarized=6,
            dropped=2,
            summary_tokens=40,
            estimated_tokens=900,
            budget=1000,
        )
    )
    recorder.observe(
        _event(
            EventType.CHECKPOINT,
            step=3,
            tool="write_file",
            files=["a.py", "b.py"],
            restorable=True,
        )
    )
    recorder.observe(_event(EventType.RECOVERY, reason="length", step=0))
    recorder.observe(
        _event(
            EventType.RECOVERY,
            reason="provider_retry",
            detail="attempt 1, backoff 0.50s: ConnectionError: hiccup",
            step=0,
        )
    )
    recorder.observe(_event(EventType.DONE, reason="stop", steps=1, total_tokens=5))

    step = recorder.steps[0]
    assert step.step == 3
    assert step.checkpoints == ["a.py", "b.py"]
    # Two things share the RECOVERY event; they must not share a counter.
    assert step.continuations == 1, "an output-cap nudge is not a retry"
    assert step.retries == 1
    assert any(note.startswith("summarized") for note in step.context)
    assert any("output cap" in note for note in step.context)
    assert any("ConnectionError" in note for note in step.context)


def test_reasoning_deltas_land_in_their_own_field(store: SessionStore) -> None:
    """``StepTrace.reasoning`` was declared, exported, round-tripped — and never written.

    The providers have always produced ``delta_reasoning`` and the loop has
    always accumulated it; only the trip into the trace was missing, so the
    field read ``""`` for every real run while the README claimed the trace
    records what the model was thinking.
    """
    recorder = _tracer(store)
    recorder.observe(_event(EventType.STEP_START, step=0, global_step=0))
    recorder.observe(_event(EventType.TEXT_DELTA, content="", reasoning="let me think"))
    recorder.observe(_event(EventType.TEXT_DELTA, content="the answer"))
    recorder.observe(_event(EventType.DONE, reason="stop", steps=1, total_tokens=1))

    step = recorder.steps[0]
    assert step.reasoning == "let me think"
    assert step.text == "the answer", "thinking must not leak into the reply"


def test_close_finalizes_an_in_flight_step(store: SessionStore) -> None:
    recorder = _tracer(store)
    recorder.observe(_event(EventType.STEP_START, step=0, global_step=0))
    recorder.observe(_event(EventType.TEXT_DELTA, content="half a rep"))
    assert recorder.pending is not None

    recorder.close()

    assert recorder.pending is None
    assert recorder.steps[0].text == "half a rep"


def test_observe_returns_the_step_it_closed(store: SessionStore) -> None:
    recorder = _tracer(store)
    recorder.observe(_event(EventType.STEP_START, step=0, global_step=0))
    recorder.observe(_event(EventType.TEXT_DELTA, content="one"))

    closed = recorder.observe(_event(EventType.STEP_START, step=1, global_step=1))

    assert closed is not None
    assert closed.text == "one"


def test_events_before_the_first_step_are_ignored(store: SessionStore) -> None:
    recorder = _tracer(store)

    assert recorder.observe(_event(EventType.TEXT_DELTA, content="stray")) is None
    assert recorder.steps == []


def test_tool_duration_is_measured(store: SessionStore) -> None:
    class Clock:
        """A monotonic clock the test steps by hand."""

        def __init__(self) -> None:
            self.now = 0.0

        def __call__(self) -> float:
            return self.now

    clock = Clock()
    recorder = _tracer(store, clock=clock)
    recorder.observe(_event(EventType.STEP_START, step=0, global_step=0))
    clock.now = 1.0
    recorder.observe(_event(EventType.TOOL_CALL, id="c1", name="echo", arguments={}))
    clock.now = 3.5
    recorder.observe(_event(EventType.TOOL_RESULT, name="echo", content="x", is_error=False))
    clock.now = 4.0
    recorder.observe(_event(EventType.DONE, reason="stop", steps=1, total_tokens=0))

    step = recorder.steps[0]
    assert step.tool_results[0].duration_ms == 2500
    assert step.tool_duration_ms == 2500
    assert step.duration_ms == 4000


# ---- persistence ------------------------------------------------------------


def test_steps_land_in_the_database(workspace: Path, store: SessionStore) -> None:
    loop = _loop([_call("echo", {"text": "a"}), _text("done")], tools=[EchoTool()])
    ctx = ToolContext(workspace=workspace, session_id="s1", step_index=0)
    recorder = _tracer(store)
    _run(loop, ctx, recorder)

    rows = store.list_traces("s1")
    assert [row.step for row in rows] == [0, 1]
    assert store.count_traces("s1") == 2

    reloaded = load_steps(store, "s1")
    assert [s.text for s in reloaded] == ["", "done"]
    assert reloaded[0].tool_names == ["echo"]


def test_jsonl_mirror_is_written_and_readable(
    workspace: Path, store: SessionStore, tmp_path: Path
) -> None:
    mirror = tmp_path / "mirror" / "s1.jsonl"
    loop = _loop([_text("hi")])
    ctx = ToolContext(workspace=workspace, session_id="s1", step_index=0)
    recorder = _tracer(store, jsonl_path=mirror)
    _run(loop, ctx, recorder)

    assert recorder.jsonl_path == mirror
    assert mirror.exists()
    lines = [json.loads(line) for line in mirror.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1
    assert lines[0]["text"] == "hi"

    steps = read_jsonl(mirror)
    assert [s.text for s in steps] == ["hi"]


def test_jsonl_can_be_disabled(workspace: Path, store: SessionStore) -> None:
    loop = _loop([_text("hi")])
    ctx = ToolContext(workspace=workspace, session_id="s1", step_index=0)
    recorder = _tracer(store)
    _run(loop, ctx, recorder)

    assert recorder.jsonl_path is None


def test_recorder_works_without_a_store(workspace: Path, tmp_path: Path) -> None:
    """--no-save runs still trace, they just keep it in memory."""
    loop = _loop([_text("hi")])
    ctx = ToolContext(workspace=workspace, session_id="s1", step_index=0)
    recorder = _tracer(None, jsonl_path=tmp_path / "t.jsonl")
    _run(loop, ctx, recorder)

    assert len(recorder.steps) == 1


def test_read_jsonl_skips_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / "broken.jsonl"
    good = StepTrace(session_id="s1", step=0, text="fine").to_dict()
    path.write_text(
        f"{json.dumps(good)}\nnot json at all\n\n{{\"half\": \n",
        encoding="utf-8",
    )

    steps = read_jsonl(path)

    assert len(steps) == 1
    assert steps[0].text == "fine"


def test_read_jsonl_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_jsonl(tmp_path / "nope.jsonl") == []


def test_deleting_a_session_cascades_to_traces(store: SessionStore) -> None:
    store.save_trace("s1", step=0, payload={"step": 0})
    assert store.count_traces("s1") == 1

    store.delete_session("s1")

    assert store.count_traces("s1") == 0


def test_delete_traces_removes_them(store: SessionStore) -> None:
    store.save_trace("s1", step=0, payload={"step": 0})
    store.save_trace("s1", step=1, payload={"step": 1})

    assert store.delete_traces("s1") == 2
    assert store.count_traces("s1") == 0


# ---- paths ------------------------------------------------------------------


def test_trace_dir_defaults_next_to_the_database(tmp_path: Path) -> None:
    assert trace_jsonl_path("s1", db_path=tmp_path / "sessions.db") == (
        tmp_path / "traces" / "s1.jsonl"
    )


def test_trace_dir_honours_the_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LOCA_TRACE_DIR", str(tmp_path / "elsewhere"))

    assert default_trace_dir() == tmp_path / "elsewhere"
    assert trace_jsonl_path("s2", db_path=tmp_path / "sessions.db") == (
        tmp_path / "elsewhere" / "s2.jsonl"
    )


def test_trace_jsonl_path_accepts_an_explicit_directory(tmp_path: Path) -> None:
    assert trace_jsonl_path("s3", directory=tmp_path / "d") == tmp_path / "d" / "s3.jsonl"


# ---- serialization ----------------------------------------------------------


def test_step_trace_round_trips_through_a_dict() -> None:
    original = StepTrace(
        session_id="s1",
        step=4,
        created_at="2026-09-12T00:00:00+00:00",
        provider="deepseek",
        model="deepseek-chat",
        duration_ms=1234,
        prompt_messages=9,
        prompt_chars=4000,
        prompt_tail="[user] do the thing",
        prompt_sampled=True,
        text="on it",
        reasoning="hmm",
        tool_calls=[ToolCallRecord(id="c1", name="echo", arguments={"text": "x"})],
        tool_results=[ToolResultRecord(name="echo", preview="x", chars=1, duration_ms=5)],
        prompt_tokens=10,
        completion_tokens=2,
        total_tokens=12,
        finish_reason="stop",
        retries=1,
        context=["trimmed 3 message(s)"],
        checkpoints=["a.py"],
    )

    assert StepTrace.from_dict(original.to_dict()) == original


def test_from_dict_tolerates_missing_keys() -> None:
    step = StepTrace.from_dict({"session_id": "s1", "step": "3"})

    assert step.step == 3
    assert step.tool_calls == []
    assert step.error is None
