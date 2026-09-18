"""Turning a stored trace into something a human can read.

``loca report <session_id>`` is the read side of Week 5. Where the trace
records *facts* (this step, this many tokens, this tool, 12 ms), the reporter
turns them into a judgement: how much of the budget went where, which tool is
the slow one, what fraction of tool calls failed, and which files the agent
actually touched.

Two renderings from one source
------------------------------

* :func:`render` — a Rich console report, for a human at a terminal.
* :func:`to_dict` — the same numbers as JSON, for a script or a CI check.

Both read the same :class:`ReportData`, so they can never disagree.

Where the data comes from
-------------------------

The session database first; the append-only JSONL mirror under
``<db dir>/traces/<session_id>.jsonl`` as a fallback. That fallback is the
point of writing two sinks: delete the ``.db`` and the run is still explainable.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.markup import escape

from loca.observability.checkpoint import Checkpoint
from loca.observability.storage import SessionInfo, SessionStore
from loca.observability.trace import StepTrace, load_steps, read_jsonl, trace_jsonl_path

#: Longest error string shown inline before it is wrapped onto its own line.
ERROR_INLINE_CHARS = 72


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ToolStat:
    """Per-tool totals across a whole session."""

    name: str
    calls: int = 0
    errors: int = 0
    duration_ms: int = 0

    @property
    def error_rate(self) -> float:
        return self.errors / self.calls if self.calls else 0.0


@dataclass(slots=True)
class TraceSummary:
    """Everything ``loca report`` says about a session, in one object."""

    session_id: str
    steps: int = 0
    provider: str = ""
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model_ms: int = 0
    tool_ms: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    failures: int = 0
    retries: int = 0
    compactions: int = 0
    trims: int = 0
    tools: dict[str, ToolStat] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    first_at: str = ""
    last_at: str = ""

    @property
    def error_rate(self) -> float:
        """Share of tool calls that came back as errors."""
        return self.tool_errors / self.tool_calls if self.tool_calls else 0.0

    @property
    def tokens_per_step(self) -> int:
        return round(self.total_tokens / self.steps) if self.steps else 0


def summarize(steps: Sequence[StepTrace]) -> TraceSummary:
    """Reduce step traces to the numbers a report leads with."""
    summary = TraceSummary(session_id=steps[0].session_id if steps else "")
    for index, step in enumerate(steps):
        summary.steps += 1
        summary.provider = step.provider or summary.provider
        summary.model = step.model or summary.model
        summary.prompt_tokens += step.prompt_tokens
        summary.completion_tokens += step.completion_tokens
        summary.total_tokens += step.total_tokens
        # The step's wall time includes its tool calls, so model time is
        # "step time minus what the tools spent" — otherwise every tool would
        # be counted twice in the headline.
        summary.model_ms += max(step.duration_ms - step.tool_duration_ms, 0)
        summary.tool_ms += step.tool_duration_ms
        summary.failures += 1 if step.failed else 0
        summary.retries += step.retries
        summary.compactions += sum(1 for note in step.context if note.startswith("summarized"))
        summary.trims += sum(1 for note in step.context if note.startswith("trimmed"))
        for path in step.checkpoints:
            if path not in summary.files:
                summary.files.append(path)
        for call in step.tool_calls:
            stat = summary.tools.setdefault(call.name, ToolStat(name=call.name))
            stat.calls += 1
            summary.tool_calls += 1
        for result in step.tool_results:
            stat = summary.tools.setdefault(result.name, ToolStat(name=result.name))
            stat.duration_ms += result.duration_ms
            if result.is_error:
                stat.errors += 1
                summary.tool_errors += 1
        if index == 0:
            summary.first_at = step.created_at
        summary.last_at = step.created_at or summary.last_at
    return summary


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ReportData:
    """One session, its traces and its checkpoints — ready to render."""

    session_id: str
    session: SessionInfo | None = None
    steps: list[StepTrace] = field(default_factory=list)
    checkpoints: list[Checkpoint] = field(default_factory=list)
    #: ``"database"``, ``"jsonl"`` or ``"none"`` — where ``steps`` came from.
    source: str = "none"

    @property
    def summary(self) -> TraceSummary:
        return summarize(self.steps)


def gather(
    store: SessionStore,
    session_id: str,
    *,
    jsonl_dir: str | Path | None = None,
    jsonl_fallback: bool = True,
) -> ReportData:
    """Load everything a report needs for one session.

    Falls back to the JSONL mirror when the database holds no traces, so a run
    is still explainable after its session rows are gone.
    """
    session = store.get_session(session_id)
    steps = load_steps(store, session_id)
    source = "database"

    if not steps and jsonl_fallback:
        mirror = trace_jsonl_path(
            session_id,
            db_path=store.path,
            directory=jsonl_dir,
        )
        fallback = read_jsonl(mirror)
        if fallback:
            steps = fallback
            source = "jsonl"

    checkpoints: list[Checkpoint] = []
    checkpoints = [Checkpoint.from_dict(row.payload) for row in store.list_checkpoints(session_id)]

    return ReportData(
        session_id=session_id,
        session=session,
        steps=steps,
        checkpoints=checkpoints,
        source=source if steps else "none",
    )


def to_dict(data: ReportData) -> dict[str, Any]:
    """Machine-readable form of :func:`render`'s numbers."""
    summary = data.summary
    session = data.session
    return {
        "session": {
            "id": data.session_id,
            "title": session.display_title if session else None,
            "workspace": session.workspace if session else None,
            "provider": session.provider if session else summary.provider or None,
            "model": session.model if session else summary.model,
            "created_at": session.created_at if session else None,
            "updated_at": session.updated_at if session else None,
            "messages": session.message_count if session else 0,
        },
        "source": data.source,
        "summary": {
            "steps": summary.steps,
            "prompt_tokens": summary.prompt_tokens,
            "completion_tokens": summary.completion_tokens,
            "total_tokens": summary.total_tokens,
            "tokens_per_step": summary.tokens_per_step,
            "model_ms": summary.model_ms,
            "tool_ms": summary.tool_ms,
            "tool_calls": summary.tool_calls,
            "tool_errors": summary.tool_errors,
            "error_rate": round(summary.error_rate, 4),
            "failures": summary.failures,
            "retries": summary.retries,
            "compactions": summary.compactions,
            "trims": summary.trims,
            "files": list(summary.files),
            "first_at": summary.first_at,
            "last_at": summary.last_at,
        },
        "tools": [
            {
                "name": stat.name,
                "calls": stat.calls,
                "errors": stat.errors,
                "error_rate": round(stat.error_rate, 4),
                "duration_ms": stat.duration_ms,
            }
            for stat in sorted(summary.tools.values(), key=lambda s: (-s.calls, s.name))
        ],
        "steps": [step.to_dict() for step in data.steps],
        "checkpoints": [checkpoint.to_dict() for checkpoint in data.checkpoints],
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _tokens(count: int) -> str:
    return f"{count:,}"


def _duration(ms: int) -> str:
    if ms < 1000:
        return f"{ms}ms"
    if ms < 60_000:
        return f"{ms / 1000:.1f}s"
    minutes, seconds = divmod(ms / 1000, 60)
    return f"{int(minutes)}m{seconds:04.1f}s"


def _one_line(text: str, limit: int = ERROR_INLINE_CHARS) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _esc(text: Any) -> str:
    """Escape Rich markup in agent-supplied text.

    Tool names, file paths, prompts and model output are arbitrary strings, and
    they routinely contain square brackets — ``[user]``, ``arr[0]``,
    ``[dim]``. Without escaping, Rich reads them as style tags and silently
    swallows them, so a report could quietly lose the very text it exists to
    show.
    """
    return escape(str(text))


def render(
    data: ReportData,
    console: Any,
    *,
    limit: int | None = None,
    verbose: bool = False,
) -> None:
    """Print a report. ``limit`` truncates the step table; ``verbose`` shows previews."""
    from rich.table import Table

    session = data.session
    summary = data.summary

    # ---- header ----------------------------------------------------------
    title = session.display_title if session else "(session not in this database)"
    console.print(
        f"[bold cyan]loca report[/bold cyan] · [bold]{_esc(data.session_id)}[/bold]"
    )
    console.print(f"[italic]{_esc(_one_line(title, 96))}[/italic]")

    facts: list[tuple[str, str]] = []
    if session is not None:
        facts.append(("workspace", session.workspace or "(not recorded)"))
        facts.append(("provider", session.provider or summary.provider or "(unknown)"))
        if session.model or summary.model:
            facts.append(("model", session.model or summary.model or ""))
        facts.append(("created", session.created_at))
        facts.append(("updated", session.updated_at))
        facts.append(("messages", str(session.message_count)))
    facts.append(("trace source", data.source))
    width = max(len(key) for key, _ in facts)
    for key, value in facts:
        console.print(f"[dim]{key.ljust(width)}[/dim]  {_esc(value)}")

    if not data.steps:
        console.print()
        console.print(
            "[yellow]no trace recorded for this session.[/yellow]\n"
            "[dim]Traces are written as the agent runs; a session started with "
            "`--no-trace` (or before Week 5) has none.[/dim]"
        )
        return

    # ---- summary ---------------------------------------------------------
    console.print()
    console.print("[bold]summary[/bold]")
    console.print(
        f"  steps      {summary.steps} model call(s) · "
        f"{_tokens(summary.tokens_per_step)} tokens/step average"
    )
    console.print(
        f"  tokens     {_tokens(summary.total_tokens)} total "
        f"([dim]{_tokens(summary.prompt_tokens)} prompt · "
        f"{_tokens(summary.completion_tokens)} completion[/dim])"
    )
    console.print(
        f"  time       {_duration(summary.model_ms)} model · "
        f"{_duration(summary.tool_ms)} tools"
    )
    tool_line = f"  tools      {summary.tool_calls} call(s)"
    if summary.tool_calls:
        colour = "red" if summary.tool_errors else "green"
        tool_line += (
            f" · [{colour}]{summary.tool_errors} error(s) "
            f"({summary.error_rate:.0%})[/{colour}]"
        )
    console.print(tool_line)
    if summary.failures or summary.retries:
        console.print(
            f"  problems   [red]{summary.failures} failed step(s)[/red] · "
            f"{summary.retries} recovery/recoveries"
        )
    if summary.compactions or summary.trims:
        console.print(
            f"  context    {summary.compactions} compaction(s) · {summary.trims} trim(s)"
        )

    # ---- tools -----------------------------------------------------------
    if summary.tools:
        console.print()
        console.print("[bold]tools[/bold]")
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("tool")
        table.add_column("calls", justify="right")
        table.add_column("errors", justify="right")
        table.add_column("time", justify="right")
        table.add_column("avg", justify="right")
        for stat in sorted(summary.tools.values(), key=lambda s: (-s.calls, s.name)):
            avg = _duration(round(stat.duration_ms / stat.calls)) if stat.calls else "—"
            table.add_row(
                _esc(stat.name),
                str(stat.calls),
                f"[red]{stat.errors}[/red]" if stat.errors else "0",
                _duration(stat.duration_ms),
                avg,
            )
        console.print(table)

    # ---- steps -----------------------------------------------------------
    console.print()
    console.print("[bold]steps[/bold]")
    shown = data.steps if limit is None else data.steps[:limit]
    step_table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    step_table.add_column("step", justify="right")
    step_table.add_column("time", justify="right")
    step_table.add_column("tokens", justify="right")
    step_table.add_column("tools")
    step_table.add_column("finish")
    step_table.add_column("note")
    for step in shown:
        tools = ", ".join(_esc(name) for name in step.tool_names) or "—"
        note = ""
        if step.error:
            note = f"[red]{_esc(_one_line(step.error, 48))}[/red]"
        elif step.retries:
            note = f"[yellow]recovered ×{step.retries}[/yellow]"
        elif step.context:
            note = f"[yellow]{_esc(_one_line(step.context[0], 48))}[/yellow]"
        finish = step.finish_reason or "?"
        if finish == "error":
            finish = f"[red]{finish}[/red]"
        step_table.add_row(
            str(step.step),
            _duration(step.duration_ms),
            _tokens(step.total_tokens),
            tools,
            finish,
            note,
        )
    console.print(step_table)
    if limit is not None and len(data.steps) > limit:
        console.print(f"[dim]… {len(data.steps) - limit} more step(s); --limit 0 for all[/dim]")

    if verbose:
        _render_details(data.steps, console)

    # ---- files -----------------------------------------------------------
    if summary.files:
        console.print()
        console.print("[bold]files snapshotted[/bold] [dim](restorable with `loca rollback`)[/dim]")
        for path in summary.files:
            console.print(f"  {_esc(path)}")
    elif data.checkpoints:
        console.print()
        console.print("[dim]checkpoints exist but name no files[/dim]")


def _render_details(steps: Iterable[StepTrace], console: Any) -> None:
    """Per-step prompt tail, model text and tool previews."""
    for step in steps:
        console.print()
        console.print(f"[bold]step {step.step}[/bold] [dim]({_duration(step.duration_ms)})[/dim]")
        if step.prompt_tail:
            label = "" if step.prompt_sampled else " [yellow](shape only)[/yellow]"
            console.print(
                f"  [dim]prompt[/dim] {step.prompt_messages} message(s), "
                f"{_tokens(step.prompt_chars)} chars{label}"
            )
            console.print(f"  [dim]└─[/dim] {_esc(_one_line(step.prompt_tail, 200))}")
        if step.text:
            console.print(f"  [dim]reply[/dim]  {_esc(_one_line(step.text, 200))}")
        for call in step.tool_calls:
            args = ", ".join(f"{k}={v!r}" for k, v in call.arguments.items())
            console.print(f"  [dim]→[/dim] {_esc(call.name)}({_esc(_one_line(args, 160))})")
        for result in step.tool_results:
            colour = "red" if result.is_error else "green"
            marker = "✗" if result.is_error else "✓"
            console.print(
                f"  [{colour}]{marker}[/{colour}] {_esc(result.name)} "
                f"[dim]{result.chars} chars · {_duration(result.duration_ms)}[/dim]"
            )
            if result.preview:
                console.print(f"     [dim]{_esc(_one_line(result.preview, 200))}[/dim]")
        for note in step.context:
            console.print(f"  [yellow]{_esc(note)}[/yellow]")


def render_json(data: ReportData) -> str:
    """The report as a JSON document (``loca report <id> --json``).

    Returned rather than printed so the caller decides where it goes — plain
    ``print`` keeps the output pipeable into ``jq`` without Rich re-wrapping it.
    """
    return json.dumps(to_dict(data), ensure_ascii=False, indent=2)


__all__ = [
    "ReportData",
    "ToolStat",
    "TraceSummary",
    "gather",
    "render",
    "render_json",
    "summarize",
    "to_dict",
]
