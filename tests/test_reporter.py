"""Tests for the Week-5 reporter: aggregation, rendering and the CLI command."""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from loca.cli import main
from loca.observability.reporter import (
    ToolStat,
    gather,
    render,
    render_json,
    summarize,
    to_dict,
)
from loca.observability.storage import SessionStore
from loca.observability.trace import (
    StepTrace,
    ToolCallRecord,
    ToolResultRecord,
    load_steps,
)

# ---- helpers ----------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SessionStore]:
    with SessionStore(tmp_path / "sessions.db") as opened:
        yield opened


def _console() -> tuple[Console, io.StringIO]:
    buffer = io.StringIO()
    return Console(file=buffer, width=140, no_color=True, highlight=False), buffer


def _step(
    step: int,
    *,
    text: str = "",
    tools: list[tuple[str, dict[str, Any]]] | None = None,
    results: list[tuple[str, str, bool]] | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    duration_ms: int = 100,
    tool_ms: int = 0,
    finish_reason: str = "stop",
    error: str | None = None,
    context: list[str] | None = None,
    checkpoints: list[str] | None = None,
    retries: int = 0,
) -> StepTrace:
    calls = [
        ToolCallRecord(id=f"c{index}", name=name, arguments=arguments)
        for index, (name, arguments) in enumerate(tools or [])
    ]
    records = [
        ToolResultRecord(
            name=name,
            preview=content,
            chars=len(content),
            is_error=is_error,
            duration_ms=tool_ms,
        )
        for name, content, is_error in (results or [])
    ]
    return StepTrace(
        session_id="s1",
        step=step,
        created_at="2026-09-12T00:00:00+00:00",
        provider="deepseek",
        model="deepseek-chat",
        duration_ms=duration_ms,
        prompt_messages=3,
        prompt_chars=120,
        prompt_tail="[user] do the thing",
        text=text,
        tool_calls=calls,
        tool_results=records,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        finish_reason=finish_reason,
        error=error,
        retries=retries,
        context=context or [],
        checkpoints=checkpoints or [],
    )


def _save(store: SessionStore, steps: list[StepTrace], session_id: str = "s1") -> None:
    store.ensure_session(session_id)
    for step in steps:
        store.save_trace(
            session_id, step=step.step, payload=step.to_dict(), created_at=step.created_at
        )


# ---- aggregation ------------------------------------------------------------


def test_summarize_totals_and_rates() -> None:
    steps = [
        _step(
            0,
            prompt_tokens=100,
            completion_tokens=10,
            duration_ms=1000,
            tool_ms=200,
            tools=[("read_file", {"path": "a.py"})],
            results=[("read_file", "ok", False)],
            checkpoints=["a.py"],
            finish_reason="tool_use",
        ),
        _step(
            1,
            prompt_tokens=200,
            completion_tokens=20,
            duration_ms=500,
            tool_ms=100,
            tools=[("write_file", {"path": "a.py"})],
            results=[("write_file", "boom", True)],
            finish_reason="tool_use",
        ),
        _step(2, prompt_tokens=300, completion_tokens=30, duration_ms=100),
    ]
    summary = summarize(steps)

    assert summary.steps == 3
    assert (summary.prompt_tokens, summary.completion_tokens) == (600, 60)
    assert summary.total_tokens == 660
    assert summary.tokens_per_step == 220
    # Step wall time minus tool time; a tool must not be counted twice.
    assert summary.model_ms == 1000 - 200 + (500 - 100) + 100
    assert summary.tool_ms == 300
    assert summary.tool_calls == 2
    assert summary.tool_errors == 1
    assert summary.error_rate == 0.5
    assert summary.files == ["a.py"]
    assert summary.first_at == "2026-09-12T00:00:00+00:00"


def test_summarize_counts_tool_calls_even_without_results() -> None:
    summary = summarize([_step(0, tools=[("echo", {})], finish_reason="tool_use")])

    assert summary.tools["echo"].calls == 1
    assert summary.tools["echo"].errors == 0
    assert summary.tool_errors == 0


def test_summarize_tolerates_an_empty_trace() -> None:
    summary = summarize([])

    assert summary.steps == 0
    assert summary.error_rate == 0.0
    assert summary.tokens_per_step == 0


def test_tool_stat_error_rate() -> None:
    stat = ToolStat(name="echo", calls=4, errors=1, duration_ms=100)

    assert stat.error_rate == 0.25
    assert ToolStat(name="x").error_rate == 0.0


def test_summarize_counts_context_events_and_failures() -> None:
    steps = [
        _step(0, context=["trimmed 4 message(s), ~900/1000 tokens"]),
        _step(1, context=["summarized 6 message(s) (dropped 2), ~800/1000 tokens"]),
        _step(2, error="RuntimeError: boom", finish_reason="error", retries=1),
    ]
    summary = summarize(steps)

    assert summary.trims == 1
    assert summary.compactions == 1
    assert summary.failures == 1
    assert summary.retries == 1


# ---- gather -----------------------------------------------------------------


def test_gather_reads_steps_from_the_database(store: SessionStore, tmp_path: Path) -> None:
    store.create_session("s1", title="a task", workspace=str(tmp_path))
    _save(store, [_step(0, text="hi")])

    data = gather(store, "s1")

    assert data.source == "database"
    assert data.session is not None
    assert data.session.display_title == "a task"
    assert len(data.steps) == 1


def test_gather_falls_back_to_the_jsonl_mirror(store: SessionStore, tmp_path: Path) -> None:
    """The whole point of two sinks: lose the database rows, keep the story."""
    store.create_session("s1")
    mirror = tmp_path / "traces" / "s1.jsonl"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text(
        "\n".join(
            json.dumps(_step(index, text=f"step {index}").to_dict()) for index in range(2)
        )
        + "\n",
        encoding="utf-8",
    )

    data = gather(store, "s1", jsonl_dir=tmp_path / "traces")

    assert data.source == "jsonl"
    assert [s.text for s in data.steps] == ["step 0", "step 1"]


def test_gather_reports_none_when_nothing_was_recorded(store: SessionStore) -> None:
    store.create_session("s1")

    data = gather(store, "s1")

    assert data.source == "none"
    assert data.steps == []


def test_gather_can_disable_the_fallback(store: SessionStore, tmp_path: Path) -> None:
    store.create_session("s1")
    mirror = tmp_path / "s1.jsonl"
    mirror.write_text(json.dumps(_step(0).to_dict()) + "\n", encoding="utf-8")

    data = gather(store, "s1", jsonl_dir=tmp_path, jsonl_fallback=False)

    assert data.source == "none"


def test_gather_for_an_unknown_session(store: SessionStore) -> None:
    data = gather(store, "does-not-exist")

    assert data.session is None
    assert data.steps == []


def test_gather_loads_checkpoints(store: SessionStore, tmp_path: Path) -> None:
    store.create_session("s1", workspace=str(tmp_path))
    store.save_checkpoint(
        "s1",
        step=0,
        tool="write_file",
        payload={
            "session_id": "s1",
            "step": 0,
            "tool": "write_file",
            "workspace": str(tmp_path),
            "created_at": "now",
            "snapshots": [{"path": "a.py", "existed": False, "encoding": "absent"}],
        },
    )

    data = gather(store, "s1")

    assert len(data.checkpoints) == 1
    assert data.checkpoints[0].snapshots[0].path == "a.py"


def test_load_steps_is_ordered(store: SessionStore) -> None:
    _save(store, [_step(2, text="c"), _step(0, text="a"), _step(1, text="b")])

    assert [s.step for s in load_steps(store, "s1")] == [0, 1, 2]


# ---- rendering --------------------------------------------------------------


def test_report_renders_the_headline_numbers(store: SessionStore) -> None:
    store.create_session("s1", title="tidy the README", workspace=r"D:\repo")
    _save(
        store,
        [
            _step(
                0,
                prompt_tokens=1000,
                completion_tokens=50,
                duration_ms=2000,
                tool_ms=500,
                tools=[("read_file", {"path": "README.md"})],
                results=[("read_file", "ok", False)],
                checkpoints=["README.md"],
                finish_reason="tool_use",
            ),
            _step(1, text="done", prompt_tokens=1200, completion_tokens=30),
        ],
    )

    console, buffer = _console()
    render(gather(store, "s1"), console)
    out = buffer.getvalue()

    assert "loca report" in out
    assert "tidy the README" in out
    assert r"D:\repo" in out
    assert "2,280" in out  # total tokens
    assert "read_file" in out
    assert "README.md" in out
    assert "steps" in out


def test_report_says_so_when_there_is_no_trace(store: SessionStore, tmp_path: Path) -> None:
    store.create_session("s1")

    console, buffer = _console()
    render(gather(store, "s1"), console)

    out = buffer.getvalue()
    assert "no trace recorded" in out
    assert "--no-trace" in out


def test_report_limit_truncates_the_step_table(store: SessionStore) -> None:
    store.create_session("s1")
    _save(store, [_step(index, text=f"s{index}") for index in range(4)])

    console, buffer = _console()
    render(gather(store, "s1"), console, limit=2)
    out = buffer.getvalue()

    assert "2 more step(s)" in out


def test_report_verbose_shows_prompts_and_previews(store: SessionStore) -> None:
    store.create_session("s1")
    _save(
        store,
        [
            _step(
                0,
                text="let me look",
                tools=[("read_file", {"path": "a.py"})],
                results=[("read_file", "file contents here", False)],
            )
        ],
    )

    console, buffer = _console()
    render(gather(store, "s1"), console, verbose=True)
    out = buffer.getvalue()

    assert "[user] do the thing" in out
    assert "let me look" in out
    assert "read_file(path='a.py')" in out
    assert "file contents here" in out


def test_report_flags_errors_and_recoveries(store: SessionStore) -> None:
    store.create_session("s1")
    _save(
        store,
        [
            _step(0, error="RuntimeError: upstream exploded", finish_reason="error"),
            _step(1, retries=2, finish_reason="recovered"),
        ],
    )

    console, buffer = _console()
    render(gather(store, "s1"), console, verbose=True)
    out = buffer.getvalue()

    assert "upstream exploded" in out
    assert "1 failed step" in out
    assert "recovered" in out


def test_report_lists_tool_errors(store: SessionStore) -> None:
    store.create_session("s1")
    _save(
        store,
        [
            _step(
                0,
                tools=[("write_file", {"path": "a.py"})],
                results=[("write_file", "permission denied", True)],
                finish_reason="tool_use",
            )
        ],
    )

    console, buffer = _console()
    render(gather(store, "s1"), console)
    out = buffer.getvalue()

    assert "write_file" in out
    assert "1 error(s) (100%)" in out


def test_render_json_round_trips(store: SessionStore) -> None:
    store.create_session("s1", title="a task", workspace=r"D:\repo")
    _save(store, [_step(0, text="hi", prompt_tokens=10, completion_tokens=2)])

    payload = json.loads(render_json(gather(store, "s1")))

    assert payload["session"]["id"] == "s1"
    assert payload["session"]["title"] == "a task"
    assert payload["source"] == "database"
    assert payload["summary"]["steps"] == 1
    assert payload["summary"]["total_tokens"] == 12
    assert payload["steps"][0]["text"] == "hi"


def test_to_dict_lists_tools_sorted_by_calls(store: SessionStore) -> None:
    store.create_session("s1")
    calls = [("echo", {}), ("echo", {}), ("read_file", {})]
    _save(
        store,
        [_step(0, tools=calls, finish_reason="tool_use")],
    )

    payload = to_dict(gather(store, "s1"))

    assert [tool["name"] for tool in payload["tools"]] == ["echo", "read_file"]


# ---- CLI --------------------------------------------------------------------


def test_cli_report_renders_a_session(
    store: SessionStore, capsys: pytest.CaptureFixture[str]
) -> None:
    db = store.path
    store.create_session("s1", title="fix the bug")
    _save(store, [_step(0, text="hi", prompt_tokens=10, completion_tokens=2)])

    code = main(["report", "s1", "--db", str(db)])

    out = capsys.readouterr().out
    assert code == 0
    assert "fix the bug" in out or "loca report" in out


def test_cli_report_json_is_machine_readable(
    store: SessionStore, capsys: pytest.CaptureFixture[str]
) -> None:
    db = store.path
    store.create_session("s1")
    _save(store, [_step(0, text="hi")])

    code = main(["report", "s1", "--db", str(db), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["summary"]["steps"] == 1


def test_cli_report_defaults_to_the_most_recent_session(
    store: SessionStore, capsys: pytest.CaptureFixture[str]
) -> None:
    db = store.path
    store.create_session("older")
    store.create_session("newer")

    code = main(["report", "--db", str(db), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["session"]["id"] == "newer"


def test_cli_report_unknown_session_fails(
    store: SessionStore, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["report", "nope", "--db", str(store.path)])

    assert code == 1
    assert "no such session" in capsys.readouterr().out


def test_cli_report_with_no_sessions_at_all(
    store: SessionStore, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["report", "--db", str(store.path)])

    assert code == 1
    assert "no sessions recorded yet" in capsys.readouterr().out
