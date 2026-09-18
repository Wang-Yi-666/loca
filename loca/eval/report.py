"""Rendering for benchmark runs: ``loca bench report``.

Two output shapes, same as :mod:`loca.observability.reporter`:

* a Rich table for humans, with the summary first — a pass rate you have to
  scroll to find is a pass rate nobody reads;
* a JSON form for scripts, produced by a pure function so it can be piped
  without a terminal being involved.

Every piece of agent-authored text goes through :func:`rich.markup.escape`.
A task prompt or a pytest failure message containing ``[`` would otherwise be
eaten as a style tag and silently vanish from the report.
"""

from __future__ import annotations

import json
from typing import Any

from rich.markup import escape as _rich_escape

from loca.eval.benchmark import (
    BenchmarkReport,
    DifficultyStat,
    TaskResult,
)


def _esc(value: Any) -> str:
    return _rich_escape(str(value))


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _int(value: float) -> str:
    return f"{int(round(value)):,}"


def render(report: BenchmarkReport, console: Any, *, verbose: bool = False) -> None:
    """Print a run's summary, per-difficulty table and failure list."""
    console.print(_summary_panel(report))

    if report.results:
        console.print(_difficulty_table(report))
        console.print(_results_table(report, verbose=verbose))

    failures = [r for r in report.results if not r.passed]
    if failures:
        console.print(_failures_table(failures, verbose=verbose))

    faults = report.grader_faults()
    if faults:
        console.print(
            f"[bold red]⚠ {len(faults)} attempt(s) hit a broken grader[/bold red] "
            "[dim]— that is a task-set bug, not a model failure; "
            "see the failure table.[/dim]"
        )


def _summary_panel(report: BenchmarkReport) -> Any:
    from rich.panel import Panel

    cost = report.cost()
    lines = [
        f"provider [cyan]{_esc(report.provider or '?')}[/cyan] · "
        f"model [cyan]{_esc(report.model or '(default)')}[/cyan]",
        f"[bold]{_pct(report.pass_at_1)}[/bold] pass@1 "
        f"[dim]({report.passed_attempts}/{report.total_attempts} attempts)[/dim] · "
        f"[bold]{_pct(report.pass_at_k)}[/bold] pass@{report.attempts_per_task} "
        f"[dim]({report.solved_tasks}/{report.task_count} tasks solved)[/dim]",
        f"[dim]tokens {_int(cost['tokens_total'])} total · "
        f"{_int(cost['tokens_per_pass'])} per pass · "
        f"{cost['steps_per_pass']:.1f} steps per pass · "
        f"{report.workers} worker(s) · {report.duration_s / 60:.1f} min[/dim]",
    ]
    return Panel("\n".join(lines), title="benchmark", border_style="cyan")


def _difficulty_table(report: BenchmarkReport) -> Any:
    from rich.table import Table

    table = Table(title="by difficulty", title_justify="left", header_style="bold")
    table.add_column("tier")
    table.add_column("tasks", justify="right")
    table.add_column("attempts", justify="right")
    table.add_column("passed", justify="right")
    table.add_column("pass rate", justify="right")
    table.add_column("tokens/pass", justify="right")
    table.add_column("steps/pass", justify="right")
    for name, stat in report.by_difficulty().items():
        table.add_row(
            _esc(name),
            str(stat.tasks),
            str(stat.attempts),
            str(stat.passed),
            _pct(stat.pass_rate),
            _int(stat.tokens_per_pass) if stat.passed else "—",
            f"{stat.steps_per_pass:.1f}" if stat.passed else "—",
        )
    return table


def _results_table(report: BenchmarkReport, *, verbose: bool) -> Any:
    from rich.table import Table

    table = Table(title="attempts", title_justify="left", header_style="bold")
    table.add_column("task")
    table.add_column("tier")
    table.add_column("try", justify="right")
    table.add_column("outcome")
    table.add_column("steps", justify="right")
    table.add_column("tokens", justify="right")
    table.add_column("secs", justify="right")
    if verbose:
        table.add_column("detail")

    for result in report.results:
        row = [
            _esc(result.task_id),
            _esc(result.difficulty),
            str(result.attempt),
            _outcome_cell(result),
            str(result.steps),
            _int(result.tokens),
            f"{result.duration_s:.0f}",
        ]
        if verbose:
            row.append(_esc(_one_line(result.detail, 120)))
        table.add_row(*row)
    return table


def _failures_table(failures: list[TaskResult], *, verbose: bool) -> Any:
    from rich.table import Table

    table = Table(title="failures", title_justify="left", header_style="bold red")
    table.add_column("task")
    table.add_column("outcome")
    table.add_column("steps", justify="right")
    table.add_column("reason")
    for result in failures:
        table.add_row(
            _esc(result.task_id),
            _outcome_cell(result),
            str(result.steps),
            _esc(_one_line(result.detail, 200 if verbose else 90)),
        )
    return table


def _outcome_cell(result: TaskResult) -> str:
    colour = {
        "passed": "green",
        "wrong_answer": "yellow",
        "max_steps": "yellow",
        "provider_error": "red",
        "timeout": "red",
        "crash": "red",
        "grader_error": "bold red",
    }.get(result.outcome, "white")
    return f"[{colour}]{_esc(result.outcome)}[/{colour}]"


def render_json(report: BenchmarkReport) -> str:
    """Serialise a run. Pure — no console, so it is safe to pipe."""
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)


# ---- comparison -------------------------------------------------------------


def render_comparison(rows: list[dict[str, Any]], console: Any) -> None:
    """Print a side-by-side table for several providers."""
    from rich.table import Table

    table = Table(title="provider comparison", title_justify="left", header_style="bold")
    table.add_column("provider")
    table.add_column("model")
    table.add_column("tasks", justify="right")
    table.add_column("pass@1", justify="right")
    table.add_column("pass@k", justify="right")
    table.add_column("tokens/pass", justify="right")
    table.add_column("steps/pass", justify="right")
    table.add_column("failures")

    for row in rows:
        failures = row.get("failures") or {}
        breakdown = ", ".join(f"{k}×{v}" for k, v in failures.items()) or "—"
        table.add_row(
            _esc(row["provider"]),
            _esc(row["model"]),
            str(row["tasks"]),
            _pct(row["pass_at_1"]),
            _pct(row["pass_at_k"]),
            _int(row["tokens_per_pass"]) if row["tokens_per_pass"] else "—",
            f"{row['steps_per_pass']:.1f}" if row["steps_per_pass"] else "—",
            _esc(breakdown),
        )
    console.print(table)
    console.print(
        "[dim]pass@1 = attempts that passed · pass@k = tasks solved at least once · "
        "tokens/steps are per passing attempt[/dim]"
    )


def render_comparison_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, ensure_ascii=False, indent=2)


def _one_line(text: str, limit: int) -> str:
    """Collapse a multi-line failure into one readable cell."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1] + "…"


def difficulty_names(stats: dict[str, DifficultyStat]) -> list[str]:
    return list(stats)
