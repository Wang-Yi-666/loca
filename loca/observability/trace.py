"""Step-by-step traces: a durable record of what the agent actually did.

A *session* (``storage.py``) answers "what was said". A *trace* answers "what
happened": which model call ran, how many tokens it cost, which tools it
triggered, how long each one took, and what broke. That is the difference
between replaying a conversation and being able to explain a run.

How it is built
---------------

:class:`TraceRecorder` is a **sink for loop events**. Feed it the
:class:`~loca.core.events.AgentEvent` stream the loop already produces and it
accumulates one :class:`StepTrace` per model step::

    recorder = TraceRecorder(
        session_id,
        store=store,
        prompt_source=lambda: loop.last_transcript,
    )
    for event in loop.run(ctx, user_message="..."):
        recorder.observe(event)
        ...

A step is finalised when the *next* step starts (or when ``DONE`` arrives),
because that is the earliest moment its data is complete. Nothing about the
loop changes; tracing is a pure observer.

Two sinks, deliberately
-----------------------

* **SQLite** — one row per step, so ``loca report`` works long after the
  process that produced it exited, and survives with the session it describes.
* **JSONL** — one JSON object per line next to the session database
  (``<db dir>/traces/<session_id>.jsonl``). Append-only, greppable with any
  tool, and readable even when the database is not. If the database is deleted
  but the file survives, ``loca report`` still has something to show.

What is *not* stored here
-------------------------

The full prompt and the full tool result would double the size of every run:
the transcript already keeps both. A step records the prompt's shape
(message count, character count, and the tail the model was reacting to) and a
bounded preview of each tool result, plus its true length — enough to read a
run end to end without duplicating it.

``finish_reason`` is likewise *derived* from the event stream rather than
copied from the wire: the loop only announces a session-level reason in
``DONE``. Treat it as a classification of how the step ended, not as a
verbatim provider field.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loca.core.events import AgentEvent, EventType
from loca.observability.storage import SessionStore, default_db_path, utcnow

#: How much of the prompt's last message is kept. Enough to recognise the step
#: when reading a report; not enough to be a second copy of the transcript.
PROMPT_TAIL_CHARS = 240

#: How much of each tool result is kept, for the same reason.
TOOL_RESULT_PREVIEW_CHARS = 800

#: Directory holding the JSONL mirror. ``$LOCA_TRACE_DIR`` overrides it.
TRACE_DIR_ENV = "LOCA_TRACE_DIR"

#: Sub-directory created next to the session database when no override is set.
TRACE_DIR_NAME = "traces"


# ---------------------------------------------------------------------------
# path helpers
# ---------------------------------------------------------------------------


def default_trace_dir(db_path: str | Path | None = None) -> Path:
    """Where the JSONL mirrors live.

    Preference order: ``$LOCA_TRACE_DIR`` → ``<db dir>/traces`` → the default
    database's directory. Keeping it next to the database means ``--db`` moves
    the traces with the sessions they describe.
    """
    override = os.environ.get(TRACE_DIR_ENV)
    if override:
        return Path(override).expanduser()
    if db_path is not None and str(db_path) != ":memory:":
        return Path(db_path).expanduser().parent / TRACE_DIR_NAME
    return default_db_path().parent / TRACE_DIR_NAME


def trace_jsonl_path(
    session_id: str,
    *,
    db_path: str | Path | None = None,
    directory: str | Path | None = None,
) -> Path:
    """Path of the JSONL mirror for one session."""
    base = Path(directory).expanduser() if directory is not None else default_trace_dir(db_path)
    return base / f"{session_id}.jsonl"


def _store_db_path(store: SessionStore | None) -> str | Path | None:
    return store.path if store is not None else None


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


@dataclass(slots=True)
class ToolCallRecord:
    """One tool the model asked for, as the model asked for it."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolCallRecord:
        return cls(
            id=data.get("id") or "",
            name=data.get("name") or "",
            arguments=data.get("arguments") or {},
        )


@dataclass(slots=True)
class ToolResultRecord:
    """What came back. ``preview`` is bounded; ``chars`` is the real length."""

    name: str
    preview: str = ""
    chars: int = 0
    is_error: bool = False
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "preview": self.preview,
            "chars": self.chars,
            "is_error": self.is_error,
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolResultRecord:
        return cls(
            name=data.get("name") or "",
            preview=data.get("preview") or "",
            chars=int(data.get("chars") or 0),
            is_error=bool(data.get("is_error")),
            duration_ms=int(data.get("duration_ms") or 0),
        )


@dataclass(slots=True)
class StepTrace:
    """One model step, start to finish.

    ``step`` is the **session-global** step number — the same one
    ``loca rollback <session> <step>`` takes — so a trace entry and a
    checkpoint always refer to the same thing.
    """

    session_id: str
    step: int
    created_at: str = ""
    provider: str = ""
    model: str | None = None
    duration_ms: int = 0

    # --- what the model saw -------------------------------------------------
    prompt_messages: int = 0
    prompt_chars: int = 0
    prompt_tail: str = ""
    #: True when the prompt was sampled from the live transcript (exact), False
    #: when the recorder had no prompt source and only knows the shape.
    prompt_sampled: bool = True

    # --- what came back -----------------------------------------------------
    text: str = ""
    reasoning: str = ""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    tool_results: list[ToolResultRecord] = field(default_factory=list)

    # --- accounting ---------------------------------------------------------
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = ""
    error: str | None = None
    retries: int = 0

    #: Human-readable notes about context pressure during this step.
    context: list[str] = field(default_factory=list)
    #: Workspace-relative paths snapshotted before this step's tool calls.
    checkpoints: list[str] = field(default_factory=list)

    # --- derived ------------------------------------------------------------

    @property
    def failed(self) -> bool:
        """Did the step end in a provider/model failure?"""
        return self.error is not None

    @property
    def tool_errors(self) -> int:
        return sum(1 for r in self.tool_results if r.is_error)

    @property
    def tool_duration_ms(self) -> int:
        return sum(r.duration_ms for r in self.tool_results)

    @property
    def tool_names(self) -> list[str]:
        return [c.name for c in self.tool_calls]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "step": self.step,
            "created_at": self.created_at,
            "provider": self.provider,
            "model": self.model,
            "duration_ms": self.duration_ms,
            "prompt_messages": self.prompt_messages,
            "prompt_chars": self.prompt_chars,
            "prompt_tail": self.prompt_tail,
            "prompt_sampled": self.prompt_sampled,
            "text": self.text,
            "reasoning": self.reasoning,
            "tool_calls": [c.to_dict() for c in self.tool_calls],
            "tool_results": [r.to_dict() for r in self.tool_results],
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "finish_reason": self.finish_reason,
            "error": self.error,
            "retries": self.retries,
            "context": list(self.context),
            "checkpoints": list(self.checkpoints),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StepTrace:
        return cls(
            session_id=data.get("session_id") or "",
            step=int(data.get("step") or 0),
            created_at=data.get("created_at") or "",
            provider=data.get("provider") or "",
            model=data.get("model"),
            duration_ms=int(data.get("duration_ms") or 0),
            prompt_messages=int(data.get("prompt_messages") or 0),
            prompt_chars=int(data.get("prompt_chars") or 0),
            prompt_tail=data.get("prompt_tail") or "",
            prompt_sampled=bool(data.get("prompt_sampled", True)),
            text=data.get("text") or "",
            reasoning=data.get("reasoning") or "",
            tool_calls=[ToolCallRecord.from_dict(c) for c in data.get("tool_calls") or []],
            tool_results=[ToolResultRecord.from_dict(r) for r in data.get("tool_results") or []],
            prompt_tokens=int(data.get("prompt_tokens") or 0),
            completion_tokens=int(data.get("completion_tokens") or 0),
            total_tokens=int(data.get("total_tokens") or 0),
            finish_reason=data.get("finish_reason") or "",
            error=data.get("error"),
            retries=int(data.get("retries") or 0),
            context=list(data.get("context") or []),
            checkpoints=list(data.get("checkpoints") or []),
        )


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------


class TraceRecorder:
    """Turn a loop's event stream into :class:`StepTrace` rows.

    Parameters
    ----------
    session_id:
        Session the traces belong to.
    store:
        Where step records are persisted. ``None`` keeps them in memory only
        (still readable via :attr:`steps`), which is what tests and
        ``--no-save`` runs want.
    jsonl:
        Also mirror every step to ``<trace dir>/<session_id>.jsonl``.
    jsonl_path:
        Explicit JSONL destination; overrides ``jsonl`` and the derived path.
    prompt_source:
        Callable returning the live message list the loop is about to send —
        normally ``lambda: loop.last_transcript``. The recorder samples it on
        the first event of each step, which is *after* any context compaction
        and *before* the assistant message is appended, so the sample is
        exactly the prompt that went out.
    clock:
        Monotonic clock, injected so tests can assert on timings.
    """

    def __init__(
        self,
        session_id: str,
        *,
        store: SessionStore | None = None,
        provider: str = "",
        model: str | None = None,
        jsonl: bool = True,
        jsonl_path: str | Path | None = None,
        prompt_source: Callable[[], Sequence[Any]] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        import time

        self.session_id = session_id
        self.store = store
        self.provider = provider
        self.model = model
        self.prompt_source = prompt_source
        self._clock = clock or time.monotonic

        if jsonl_path is not None:
            self.jsonl_path: Path | None = Path(jsonl_path).expanduser()
        elif jsonl:
            self.jsonl_path = trace_jsonl_path(session_id, db_path=_store_db_path(store))
        else:
            self.jsonl_path = None

        self._completed: list[StepTrace] = []
        self._pending: StepTrace | None = None
        self._started_at: float = 0.0
        self._sampled = False
        #: ``(tool_name, started_at)`` in the order the calls were announced.
        self._call_started: list[tuple[str, float]] = []

    # ---- public API -------------------------------------------------------

    @property
    def steps(self) -> list[StepTrace]:
        """Steps recorded so far (finalised only)."""
        return list(self._completed)

    @property
    def pending(self) -> StepTrace | None:
        """The step currently being accumulated, if any."""
        return self._pending

    def observe(self, event: AgentEvent) -> StepTrace | None:
        """Feed one loop event.

        Returns the step that this event *closed*, if any — so a caller can
        stream traces out while a run is still going.
        """
        kind = event.type
        data = event.data

        if kind is EventType.STEP_START:
            closed = self._finalize()
            self._begin(step=int(data.get("global_step", data.get("step", 0))))
            return closed

        if self._pending is None:
            # Events before the first STEP_START (defensive; the loop always
            # announces the step first).
            return None

        # Sampling the prompt must happen before the loop appends the assistant
        # message, and after compaction. Every other event of a step arrives
        # later than that, so the first one we see is the right moment.
        self._sample_prompt()

        if kind is EventType.TEXT_DELTA:
            self._pending.text += data.get("content", "")
        elif kind is EventType.TOOL_CALL:
            self._note_call(data)
        elif kind is EventType.TOOL_RESULT:
            self._note_result(data)
        elif kind is EventType.USAGE:
            self._pending.prompt_tokens = int(data.get("prompt_tokens") or 0)
            self._pending.completion_tokens = int(data.get("completion_tokens") or 0)
            self._pending.total_tokens = int(data.get("total_tokens") or 0)
        elif kind is EventType.CHECKPOINT:
            for path in data.get("files") or []:
                if path not in self._pending.checkpoints:
                    self._pending.checkpoints.append(path)
        elif kind is EventType.CONTEXT_TRIMMED:
            self._pending.context.append(
                f"trimmed {data.get('dropped', 0)} message(s), "
                f"~{data.get('estimated_tokens', 0)}/{data.get('budget', 0)} tokens"
            )
        elif kind is EventType.CONTEXT_SUMMARIZED:
            self._pending.context.append(
                f"summarized {data.get('summarized', 0)} message(s) "
                f"(dropped {data.get('dropped', 0)}), "
                f"~{data.get('estimated_tokens', 0)}/{data.get('budget', 0)} tokens"
            )
        elif kind is EventType.RECOVERY:
            self._pending.retries += 1
            self._pending.context.append(f"recovered from {data.get('reason', 'unknown')}")
        elif kind is EventType.ERROR:
            self._pending.error = str(data.get("message") or "unknown error")
            # The loop treats a provider error as terminal (it yields ERROR and
            # returns), so the step is complete here — no need to wait for the
            # next turn's STEP_START to flush it.
            return self._finalize()
        elif kind is EventType.DONE:
            self._pending.finish_reason = str(data.get("reason") or "")
            return self._finalize()

        return None

    def close(self) -> None:
        """Finalize an in-flight step (e.g. when a caller stops reading)."""
        self._finalize()

    def __enter__(self) -> TraceRecorder:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- internals --------------------------------------------------------

    def _begin(self, *, step: int) -> None:
        self._pending = StepTrace(
            session_id=self.session_id,
            step=step,
            created_at=utcnow(),
            provider=self.provider,
            model=self.model,
            # Assume sampled; cleared when there is no prompt source.
            prompt_sampled=self.prompt_source is not None,
        )
        self._started_at = self._clock()
        self._sampled = False
        self._call_started.clear()

    def _sample_prompt(self) -> None:
        if self._sampled or self._pending is None:
            return
        self._sampled = True
        if self.prompt_source is None:
            return
        try:
            messages = list(self.prompt_source() or [])
        except Exception:  # pragma: no cover - defensive: never break a run
            return
        pending = self._pending
        pending.prompt_messages = len(messages)
        pending.prompt_chars = sum(len(m.content or "") for m in messages)
        pending.prompt_tail = _clip(_render_tail(messages), PROMPT_TAIL_CHARS)

    def _note_call(self, data: dict[str, Any]) -> None:
        assert self._pending is not None
        call = ToolCallRecord(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            arguments=data.get("arguments") or {},
        )
        self._pending.tool_calls.append(call)
        # Keep the timing in call order. ``TOOL_RESULT`` carries the tool name
        # but not the call id, so results are matched by name (falling back to
        # the oldest unmatched call), which is exact for the normal case of one
        # call per tool per step.
        self._call_started.append((call.name, self._clock()))

    def _note_result(self, data: dict[str, Any]) -> None:
        assert self._pending is not None
        content = str(data.get("content") or "")
        name = str(data.get("name") or "")
        self._pending.tool_results.append(
            ToolResultRecord(
                name=name,
                preview=_clip(content, TOOL_RESULT_PREVIEW_CHARS),
                chars=len(content),
                is_error=bool(data.get("is_error")),
                duration_ms=self._pop_duration(name),
            )
        )

    def _pop_duration(self, name: str) -> int:
        """Elapsed time of the call this result belongs to."""
        if not self._call_started:
            return 0
        index = next(
            (i for i, (call_name, _) in enumerate(self._call_started) if call_name == name),
            0,
        )
        _, started = self._call_started.pop(index)
        return int((self._clock() - started) * 1000)

    def _finalize(self) -> StepTrace | None:
        trace = self._pending
        if trace is None:
            return None
        trace.duration_ms = int((self._clock() - self._started_at) * 1000)
        trace.finish_reason = trace.finish_reason or _derive_finish(trace)
        self._pending = None
        self._completed.append(trace)
        self._persist(trace)
        return trace

    def _persist(self, trace: StepTrace) -> None:
        payload = trace.to_dict()
        if self.store is not None:
            try:
                self.store.save_trace(
                    trace.session_id,
                    step=trace.step,
                    payload=payload,
                    created_at=trace.created_at,
                )
            except Exception:  # pragma: no cover - a broken db must not kill a run
                pass
        if self.jsonl_path is not None:
            try:
                self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
                with self.jsonl_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False))
                    handle.write("\n")
            except OSError:  # pragma: no cover - disk full / permissions
                pass


def _render_tail(messages: Sequence[Any]) -> str:
    """Last non-empty thing the model saw, prefixed with its role."""
    for message in reversed(messages):
        role = getattr(getattr(message, "role", None), "value", "?")
        text = getattr(message, "content", None) or ""
        if not text.strip() and getattr(message, "tool_calls", None):
            names = ", ".join(c.name for c in message.tool_calls)
            text = f"<tool calls: {names}>"
        if text.strip():
            return f"[{role}] {text.strip()}"
    return ""


def _derive_finish(trace: StepTrace) -> str:
    """Classify how the step ended, from what the event stream told us.

    The loop only announces a session-level reason in ``DONE`` (which
    :meth:`TraceRecorder.observe` stores verbatim, so this is only reached for
    steps that ended *before* the run did). Order matters: a failure beats a
    recovery, a recovery beats "the model used tools".
    """
    if trace.error:
        return "error"
    if trace.retries:
        return "recovered"
    if trace.tool_calls:
        return "tool_use"
    return "stop"


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def load_steps(store: SessionStore, session_id: str) -> list[StepTrace]:
    """Step traces for a session from the database, oldest first."""
    return [StepTrace.from_dict(row.payload) for row in store.list_traces(session_id)]


def read_jsonl(path: str | Path) -> list[StepTrace]:
    """Read a JSONL mirror. Malformed lines are skipped, not fatal."""
    steps: list[StepTrace] = []
    try:
        handle = Path(path).expanduser().open("r", encoding="utf-8")
    except OSError:
        return steps
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                steps.append(StepTrace.from_dict(json.loads(line)))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
    return steps


def iter_steps(steps: Sequence[StepTrace]) -> Iterator[StepTrace]:
    """Yield the steps in order — sugar for callers that stream into a renderer."""
    yield from steps


__all__ = [
    "PROMPT_TAIL_CHARS",
    "TOOL_RESULT_PREVIEW_CHARS",
    "TRACE_DIR_ENV",
    "TRACE_DIR_NAME",
    "StepTrace",
    "ToolCallRecord",
    "ToolResultRecord",
    "TraceRecorder",
    "default_trace_dir",
    "iter_steps",
    "load_steps",
    "read_jsonl",
    "trace_jsonl_path",
]
