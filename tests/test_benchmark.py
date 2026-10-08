"""Tests for the Week-6 benchmark runner and report.

Everything here runs against scripted providers, so the suite stays offline and
deterministic. The provider is stubbed at the same seam the real one plugs into
(``LLMProvider.stream_chat``), which means these tests exercise the real agent
loop, the real tools and the real graders.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from loca.eval.benchmark import (
    BenchmarkError,
    BenchmarkReport,
    TaskResult,
    compare,
    run_attempt,
    run_benchmark,
)
from loca.eval.report import (
    render,
    render_comparison,
    render_comparison_json,
    render_json,
)
from loca.eval.tasks import TaskSet, load_tasks
from loca.providers.base import LLMProvider
from loca.providers.types import (
    ChatRequest,
    ChatResponse,
    FinishReason,
    StreamChunk,
    ToolCall,
)
from loca.tools import register_default_tools
from loca.tools.registry import all_tools

register_default_tools()


# ---- a scripted provider ----------------------------------------------------


class ScriptedProvider(LLMProvider):
    """Replays a fixed list of stream chunks, one entry per model call."""

    name = "scripted"

    def __init__(self, scripts: list[list[StreamChunk]]) -> None:
        self._scripts = list(scripts)
        self._call = 0

    def chat(self, request: ChatRequest) -> ChatResponse:  # pragma: no cover
        raise NotImplementedError

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamChunk]:
        script = self._scripts[min(self._call, len(self._scripts) - 1)]
        self._call += 1
        yield from script


class ExplodingProvider(LLMProvider):
    name = "exploding"

    def chat(self, request: ChatRequest) -> ChatResponse:  # pragma: no cover
        raise NotImplementedError

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamChunk]:
        raise RuntimeError("provider is down")
        yield  # pragma: no cover - makes this a generator


def _text(text: str) -> list[StreamChunk]:
    return [StreamChunk(delta_content=text, finish_reason=FinishReason.STOP)]


def _call(name: str, args: dict[str, Any], call_id: str = "c1") -> list[StreamChunk]:
    return [
        StreamChunk(
            delta_tool_calls=[ToolCall(id=call_id, name=name, arguments=args)],
            finish_reason=FinishReason.TOOL_USE,
        )
    ]


def _solution_scripts() -> list[list[StreamChunk]]:
    """Write the answer, then stop."""
    return [
        _call("write_file", {"path": "answer.py", "content": "VALUE = 7\n"}),
        _text("done"),
    ]


# ---- a throwaway task -------------------------------------------------------


def _make_task(root: Path, task_id: str = "t1", *, difficulty: str = "simple") -> Path:
    path = root / task_id
    (path / "workspace").mkdir(parents=True)
    (path / "hidden").mkdir()
    # The grader is hidden: the agent gets no hint of the expected value.
    (path / "hidden" / "test_it.py").write_text(
        "from answer import VALUE\n\n\ndef test_value():\n    assert VALUE == 7\n",
        encoding="utf-8",
    )
    (path / "task.json").write_text(
        json.dumps(
            {
                "id": task_id,
                "title": "write the answer",
                "difficulty": difficulty,
                "prompt": "create answer.py defining VALUE",
                "checks": {"kind": "pytest", "paths": ["test_it.py"]},
            }
        ),
        encoding="utf-8",
    )
    return path


def _task_set(root: Path, *task_ids: str) -> TaskSet:
    """Create throwaway tasks under ``root`` and load them as a set.

    ``load_tasks`` takes the *directory holding* the tasks, which is an easy
    thing to get wrong — hence this helper rather than a bare ``load_tasks``.
    """
    for task_id in task_ids:
        _make_task(root, task_id)
    return load_tasks(root)


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """The *root* holding the tasks — that is what ``load_tasks`` takes."""
    return _make_task(tmp_path / "tasks", "t1").parent


# ---- one attempt ------------------------------------------------------------


def test_a_successful_attempt_is_graded_as_passed(task_dir: Path, tmp_path: Path) -> None:
    task = load_tasks(task_dir).get("t1")
    result = run_attempt(
        task,
        provider_factory=lambda: ScriptedProvider(_solution_scripts()),
        sandbox=tmp_path / "sandbox",
        tools=list(all_tools()),
        trace=False,
    )
    assert result.outcome == "passed"
    assert result.passed
    assert result.steps == 2
    assert result.tool_calls == 1
    assert result.tool_errors == 0
    assert (tmp_path / "sandbox" / "answer.py").exists()


def test_an_attempt_that_changes_nothing_is_a_wrong_answer(task_dir: Path, tmp_path: Path) -> None:
    task = load_tasks(task_dir).get("t1")
    result = run_attempt(
        task,
        provider_factory=lambda: ScriptedProvider([_text("I would rather not")]),
        sandbox=tmp_path / "sandbox",
        tools=list(all_tools()),
        trace=False,
    )
    assert result.outcome == "wrong_answer"
    assert result.failed
    assert result.steps == 1
    # A grader's failure text is kept, so a report can explain the failure.
    assert result.detail


def test_a_provider_error_is_classified_separately(task_dir: Path, tmp_path: Path) -> None:
    task = load_tasks(task_dir).get("t1")
    result = run_attempt(
        task,
        provider_factory=lambda: ExplodingProvider(),
        sandbox=tmp_path / "sandbox",
        tools=list(all_tools()),
        trace=False,
    )
    assert result.outcome == "provider_error"
    assert "provider is down" in result.detail


def test_running_out_of_steps_is_classified_separately(task_dir: Path, tmp_path: Path) -> None:
    task = load_tasks(task_dir).get("t1")

    def looping() -> ScriptedProvider:
        # Never stops asking for a tool: the loop has to cut it off.
        return ScriptedProvider([_call("read_file", {"path": "answer.py"}, "c1")])

    result = run_attempt(
        task,
        provider_factory=looping,
        sandbox=tmp_path / "sandbox",
        max_steps=3,
        tools=list(all_tools()),
        trace=False,
    )
    assert result.outcome == "max_steps"
    assert result.steps == 3


def test_a_wall_clock_timeout_is_classified_separately(task_dir: Path, tmp_path: Path) -> None:
    task = load_tasks(task_dir).get("t1")
    result = run_attempt(
        task,
        provider_factory=lambda: ScriptedProvider([_text("thinking")]),
        sandbox=tmp_path / "sandbox",
        timeout_s=0,
        tools=list(all_tools()),
        trace=False,
    )
    assert result.outcome == "timeout"


def test_a_broken_grader_is_not_counted_against_the_model(
    task_dir: Path, tmp_path: Path
) -> None:
    task = load_tasks(task_dir).get("t1")
    task.checks = {"kind": "vibes"}
    result = run_attempt(
        task,
        provider_factory=lambda: ScriptedProvider([_text("done")]),
        sandbox=tmp_path / "sandbox",
        tools=list(all_tools()),
        trace=False,
    )
    assert result.outcome == "grader_error"
    assert result.grader_fault


def test_a_crashing_provider_factory_does_not_escape(task_dir: Path, tmp_path: Path) -> None:
    task = load_tasks(task_dir).get("t1")

    def broken_factory() -> LLMProvider:
        raise RuntimeError("no credentials")

    result = run_attempt(
        task,
        provider_factory=broken_factory,
        sandbox=tmp_path / "sandbox",
        tools=list(all_tools()),
        trace=False,
    )
    assert result.outcome == "crash"
    assert "no credentials" in result.detail


def test_an_attempt_can_record_a_trace_and_a_session(task_dir: Path, tmp_path: Path) -> None:
    task = load_tasks(task_dir).get("t1")
    db = tmp_path / "sessions.db"
    result = run_attempt(
        task,
        provider_factory=lambda: ScriptedProvider(_solution_scripts()),
        sandbox=tmp_path / "sandbox",
        tools=list(all_tools()),
        store_path=db,
        provider_name="scripted",
    )
    assert result.outcome == "passed"
    assert result.session_id == "bench-t1-a1"
    assert db.exists()


def test_the_sandbox_is_wiped_of_hidden_files_before_grading(
    task_dir: Path, tmp_path: Path
) -> None:
    """An attempt that hand-writes a passing grader still gets the real one."""
    task = load_tasks(task_dir).get("t1")

    def cheating() -> ScriptedProvider:
        return ScriptedProvider(
            [
                _call(
                    "write_file",
                    {"path": "test_it.py", "content": "def test_anything():\n    pass\n"},
                    "c1",
                ),
                _text("all tests pass now"),
            ]
        )

    result = run_attempt(
        task,
        provider_factory=cheating,
        sandbox=tmp_path / "sandbox",
        tools=list(all_tools()),
        trace=False,
    )
    assert result.outcome == "wrong_answer", "the swapped-in grader must not survive"


# ---- the run ----------------------------------------------------------------


def test_run_benchmark_aggregates_one_attempt_per_task(tmp_path: Path) -> None:
    tasks = _task_set(tmp_path / "tasks", "t1")
    report = run_benchmark(
        tasks,
        provider_factory=lambda: ScriptedProvider(_solution_scripts()),
        provider_name="scripted",
        workdir=tmp_path / "work",
    )
    assert report.task_count == 1
    assert report.total_attempts == 1
    assert report.pass_at_1 == 1.0
    assert report.pass_at_k == 1.0
    assert report.results[0].task_id == "t1"


def test_run_benchmark_computes_pass_at_1_and_pass_at_k_separately(tmp_path: Path) -> None:
    """One flaky task: half the attempts pass, but the task is solvable."""
    tasks = _task_set(tmp_path / "tasks", "t1")
    counter = {"n": 0}

    def alternating() -> ScriptedProvider:
        counter["n"] += 1
        if counter["n"] % 2 == 1:
            return ScriptedProvider([_text("not today")])
        return ScriptedProvider(_solution_scripts())

    report = run_benchmark(
        tasks,
        provider_factory=alternating,
        attempts=2,
        workers=1,
        workdir=tmp_path / "work",
    )
    assert report.total_attempts == 2
    assert report.pass_at_1 == 0.5
    assert report.pass_at_k == 1.0
    assert report.solved_tasks == 1
    assert report.attempts_per_task == 2


def test_run_benchmark_groups_by_difficulty(tmp_path: Path) -> None:
    task_root = tmp_path / "tasks"
    _make_task(task_root, "t1", difficulty="simple")
    _make_task(task_root, "t2", difficulty="hard")
    tasks = load_tasks(task_root)
    report = run_benchmark(
        tasks,
        provider_factory=lambda: ScriptedProvider(_solution_scripts()),
        workdir=tmp_path / "work",
    )
    table = {name: stat for name, stat in report.by_difficulty().items()}
    assert set(table) == {"simple", "hard"}
    assert table["simple"].pass_rate == 1.0
    assert table["hard"].tasks == 1
    assert table["hard"].tokens_per_pass >= 0


def test_run_benchmark_counts_failures_by_outcome(tmp_path: Path) -> None:
    task_root = tmp_path / "tasks"
    _make_task(task_root, "t1")
    _make_task(task_root, "t2")
    tasks = load_tasks(task_root)

    def factory() -> ScriptedProvider:
        return ScriptedProvider([_text("nope")])

    report = run_benchmark(
        tasks,
        provider_factory=factory,
        workdir=tmp_path / "work",
    )
    assert report.outcomes()["wrong_answer"] == 2
    assert report.failure_breakdown() == {"wrong_answer": 2}
    assert report.pass_at_1 == 0.0


def test_run_benchmark_reports_grader_faults_separately(tmp_path: Path) -> None:
    task_root = tmp_path / "tasks"
    _make_task(task_root, "t1")
    tasks = load_tasks(task_root)
    tasks.tasks[0].checks = {"kind": "vibes"}
    report = run_benchmark(
        tasks,
        provider_factory=lambda: ScriptedProvider([_text("done")]),
        workdir=tmp_path / "work",
    )
    assert [r.task_id for r in report.grader_faults()] == ["t1"]


def test_run_benchmark_rejects_an_empty_selection(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkError, match="no tasks"):
        run_benchmark([], provider_factory=lambda: ScriptedProvider([_text("x")]),
                      workdir=tmp_path / "work")


def test_run_benchmark_rejects_a_zero_attempt_count(tmp_path: Path) -> None:
    tasks = _task_set(tmp_path / "tasks", "t1")
    with pytest.raises(BenchmarkError, match="attempts"):
        run_benchmark(
            tasks,
            provider_factory=lambda: ScriptedProvider(_text("x")),
            attempts=0,
            workdir=tmp_path / "work",
        )


def test_run_benchmark_reports_progress(tmp_path: Path) -> None:
    tasks = _task_set(tmp_path / "tasks", "t1")
    seen: list[tuple[int, int, str]] = []
    run_benchmark(
        tasks,
        provider_factory=lambda: ScriptedProvider(_solution_scripts()),
        workdir=tmp_path / "work",
        progress=lambda done, total, result: seen.append((done, total, result.task_id)),
    )
    assert seen == [(1, 1, "t1")]


def test_run_benchmark_removes_the_sandboxes_by_default(tmp_path: Path) -> None:
    tasks = _task_set(tmp_path / "tasks", "t1")
    workdir = tmp_path / "work"
    run_benchmark(
        tasks,
        provider_factory=lambda: ScriptedProvider(_solution_scripts()),
        workdir=workdir,
    )
    assert not workdir.exists()


def test_run_benchmark_can_keep_the_sandboxes(tmp_path: Path) -> None:
    tasks = _task_set(tmp_path / "tasks", "t1")
    workdir = tmp_path / "work"
    run_benchmark(
        tasks,
        provider_factory=lambda: ScriptedProvider(_solution_scripts()),
        workdir=workdir,
        keep=True,
    )
    assert (workdir / "t1-a1" / "answer.py").exists()


def test_run_benchmark_records_traces_when_asked(tmp_path: Path) -> None:
    tasks = _task_set(tmp_path / "tasks", "t1")
    db = tmp_path / "sessions.db"
    report = run_benchmark(
        tasks,
        provider_factory=lambda: ScriptedProvider(_solution_scripts()),
        workdir=tmp_path / "work",
        store_path=db,
        provider_name="scripted",
    )
    assert report.results[0].passed
    assert db.exists()


# ---- the report -------------------------------------------------------------


def _report_with(results: list[TaskResult]) -> BenchmarkReport:
    report = BenchmarkReport(provider="p", model="m", attempts_per_task=1, workers=1)
    report.results = results
    return report


def _result(
    task_id: str,
    outcome: str,
    *,
    difficulty: str = "simple",
    steps: int = 1,
    tokens: int = 100,
) -> TaskResult:
    return TaskResult(
        task_id=task_id,
        title="t",
        difficulty=difficulty,
        attempt=1,
        outcome=outcome,
        steps=steps,
        tokens=tokens,
        detail="detail text",
        duration_s=1.5,
    )


def test_cost_is_reported_per_pass_not_per_attempt() -> None:
    report = _report_with(
        [
            _result("a", "passed", tokens=1000, steps=4),
            _result("b", "wrong_answer", tokens=50, steps=1),
        ]
    )
    cost = report.cost()
    assert cost["tokens_total"] == 1050
    assert cost["tokens_per_pass"] == 1000
    assert cost["tokens_per_failure"] == 50
    assert cost["steps_per_pass"] == 4
    assert report.pass_at_1 == 0.5


def test_cost_of_a_run_with_no_passes_is_zero_not_a_crash() -> None:
    report = _report_with([_result("a", "wrong_answer")])
    cost = report.cost()
    assert cost["tokens_per_pass"] == 0.0
    assert cost["steps_per_pass"] == 0.0
    assert cost["tokens_per_failure"] == 100


def test_an_empty_report_has_zero_rates() -> None:
    report = BenchmarkReport()
    assert report.pass_at_1 == 0.0
    assert report.pass_at_k == 0.0
    assert report.task_count == 0


def test_render_json_is_valid_json_with_the_expected_shape() -> None:
    report = _report_with([_result("a", "passed"), _result("b", "max_steps")])
    payload = json.loads(render_json(report))
    assert payload["provider"] == "p"
    assert payload["pass_at_1"] == 0.5
    assert payload["failures"] == {"max_steps": 1}
    assert len(payload["results"]) == 2
    assert payload["results"][0]["task_id"] == "a"
    assert payload["by_difficulty"]["simple"]["passed"] == 1


def test_render_escapes_rich_markup_in_agent_output() -> None:
    """A prompt or a pytest message full of brackets must not be swallowed."""
    report = _report_with([_result("a", "wrong_answer")])
    report.results[0].detail = "[bold]not a style[/bold] and [dim]this isn't either[/dim]"
    buffer = StringIO()
    from rich.console import Console

    render(report, Console(file=buffer, width=200))
    output = buffer.getvalue()
    assert "not a style" in output
    assert "this isn't either" in output


def test_render_shows_the_pass_rate_and_the_failure_list() -> None:
    from rich.console import Console

    report = _report_with([_result("a", "passed"), _result("b", "provider_error")])
    buffer = StringIO()
    render(report, Console(file=buffer, width=200))
    output = buffer.getvalue()
    assert "50.0%" in output
    assert "provider_error" in output


def test_render_warns_about_a_broken_grader() -> None:
    from rich.console import Console

    report = _report_with([_result("a", "grader_error")])
    buffer = StringIO()
    render(report, Console(file=buffer, width=200))
    assert "broken grader" in buffer.getvalue()


# ---- the report names what it measured ---------------------------------------


class _NamedProvider(ScriptedProvider):
    """A scripted provider that also knows which model it speaks for."""

    def __init__(self, scripts: list[list[StreamChunk]], model: str = "scripted-v1") -> None:
        super().__init__(scripts)
        self._default_model = model


def test_run_benchmark_records_the_providers_default_model(tmp_path: Path) -> None:
    """``--model`` is usually unset, so the report has to ask the provider.

    ``docs/benchmarks/deepseek-36.json`` shipped with ``"model": null``: an
    evidence file cited for reproducibility that could not say what produced it.
    """
    tasks = _task_set(tmp_path / "tasks", "t1")
    report = run_benchmark(
        tasks,
        provider_factory=lambda: _NamedProvider(_solution_scripts()),
        workdir=tmp_path / "work",
    )
    assert report.model == "scripted-v1"
    assert report.to_dict()["model"] == "scripted-v1"


def test_an_explicit_model_still_wins(tmp_path: Path) -> None:
    tasks = _task_set(tmp_path / "tasks", "t1")
    report = run_benchmark(
        tasks,
        provider_factory=lambda: _NamedProvider(_solution_scripts()),
        model="pinned",
        workdir=tmp_path / "work",
    )
    assert report.model == "pinned"


def test_a_failing_model_probe_does_not_abort_the_run(tmp_path: Path) -> None:
    """The label is worth having; it is not worth throwing a benchmark away."""
    tasks = _task_set(tmp_path / "tasks", "t1")
    calls = {"n": 0}

    def factory() -> LLMProvider:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("no api key")
        return ScriptedProvider(_solution_scripts())

    report = run_benchmark(tasks, provider_factory=factory, workdir=tmp_path / "work")

    assert report.model is None
    assert report.passed_attempts == 1, "the attempts still ran"


def test_attempt_counters_are_persisted() -> None:
    """``recoveries`` was counted and then dropped on the way into the archive."""
    result = TaskResult(
        task_id="t", title="t", difficulty="simple", attempt=1, outcome="passed"
    )
    result.retries = 2
    result.continuations = 3

    payload = result.to_dict()

    assert payload["retries"] == 2
    assert payload["continuations"] == 3


# ---- the deadline is a cutoff, not a classification ---------------------------


class _SlowEmptyTurn(LLMProvider):
    """One model call that takes longer to start than the deadline allows.

    It emits no deltas at all, which makes DONE the first event to arrive after
    the deadline — the ordering that exposed the bug.
    """

    name = "slow-empty"

    def __init__(self, delay: float) -> None:
        self._delay = delay

    def chat(self, request: ChatRequest) -> ChatResponse:  # pragma: no cover
        raise NotImplementedError

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamChunk]:
        time.sleep(self._delay)
        yield StreamChunk(finish_reason=FinishReason.STOP)


def test_a_turn_that_finishes_past_the_deadline_is_graded_not_timed_out(
    tmp_path: Path,
) -> None:
    """The deadline check ran before the DONE branch and threw its result away.

    A run that overran by a hair but *finished* was recorded as ``timeout`` with
    ``steps=0 / tokens=0`` — the cost was under-reported and the grader never ran.
    """
    tasks = _task_set(tmp_path / "tasks", "t1")

    result = run_attempt(
        tasks.get("t1"),
        provider_factory=lambda: _SlowEmptyTurn(delay=1.2),
        sandbox=tmp_path / "sandbox",
        timeout_s=1,
    )

    assert result.outcome == "wrong_answer", "the turn completed; it just failed"
    assert result.steps == 1, "and its step count survived"


def test_render_verbose_includes_the_detail_column() -> None:
    from rich.console import Console

    report = _report_with([_result("a", "passed")])
    buffer = StringIO()
    render(report, Console(file=buffer, width=300), verbose=True)
    assert "detail text" in buffer.getvalue()


def test_render_comparison_puts_providers_side_by_side() -> None:
    from rich.console import Console

    deepseek = _report_with([_result("a", "passed"), _result("b", "wrong_answer")])
    deepseek.provider = "deepseek"
    anthropic = _report_with([_result("a", "wrong_answer"), _result("b", "wrong_answer")])
    anthropic.provider = "anthropic"

    rows = compare([deepseek, anthropic])
    buffer = StringIO()
    render_comparison(rows, Console(file=buffer, width=200))
    output = buffer.getvalue()

    assert "provider comparison" in output
    assert "deepseek" in output
    assert "anthropic" in output
    # One of deepseek's two attempts passed; neither of anthropic's did.
    assert "50.0%" in output
    assert "0.0%" in output


def test_render_comparison_json_is_serialisable() -> None:
    rows = compare([_report_with([_result("a", "passed")])])
    payload = json.loads(render_comparison_json(rows))
    assert payload[0]["tasks"] == 1
    assert payload[0]["pass_at_1"] == 1.0


def test_compare_handles_a_run_with_no_attempts() -> None:
    rows = compare([BenchmarkReport(provider="empty")])
    assert rows[0]["tasks"] == 0
    assert rows[0]["failures"] == {}
