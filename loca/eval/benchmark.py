"""Benchmark runner.

Runs a set of :class:`~loca.eval.tasks.EvalTask` against a provider, grades
each attempt, and aggregates the results.

The runner is deliberately thin: it reuses the real :class:`AgentLoop`, the real
tools, and (optionally) the real trace recorder. A benchmark that drives a
special test-only code path measures the test path, not the harness — so the
only thing that differs from `loca chat` is where the prompt comes from and who
grades the result.

Concurrency
-----------
Attempts are independent (each gets its own sandbox, provider instance and
session), so they run in a thread pool. ``provider_factory`` must therefore
return a *fresh* provider per call: HTTP clients are not safe to share across
threads in the way a long-lived agent conversation would need.

Timeouts
--------
The per-attempt deadline is *cooperative*: it is checked between streamed
events, so a provider call that blocks inside the HTTP client is bounded by
that client's own timeout, not by this one. This is documented rather than
hidden, because "the benchmark says it timed out at 300s but really it hung for
320s" is the kind of detail that quietly invalidates a report.
"""

from __future__ import annotations

import logging
import shutil
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loca.agents import CODING_AGENT, build_agent
from loca.core.events import EventType
from loca.core.loop import DEFAULT_TOKEN_BUDGET, AgentLoop
from loca.eval.tasks import (
    DIFFICULTIES,
    EvalTask,
    TaskError,
    TaskSet,
    load_tasks,
)
from loca.observability.storage import SessionStore
from loca.providers.base import LLMProvider
from loca.tools.registry import all_tools

_log = logging.getLogger("loca.benchmark")

#: How an attempt ended. ``passed`` and ``wrong_answer`` both mean the loop ran
#: to completion; the rest are failures with a distinct cause, and keeping them
#: apart is what turns "60% pass rate" into something actionable.
OUTCOMES: tuple[str, ...] = (
    "passed",
    "wrong_answer",
    "max_steps",
    "provider_error",
    "timeout",
    "crash",
    "grader_error",
)

#: Outcomes that blame the task author, not the agent. Reported separately so a
#: broken grader can never be mistaken for a weak model.
GRADER_FAULTS = frozenset({"grader_error"})

DEFAULT_MAX_STEPS = 20
DEFAULT_TASK_TIMEOUT = 300

#: Messages kept verbatim when the context is compacted. Matches the default of
#: ``loca chat --keep-recent`` so a benchmark run behaves like a real session.
DEFAULT_KEEP_RECENT = 6


@dataclass(slots=True)
class TaskResult:
    """One graded attempt at one task."""

    task_id: str
    title: str
    difficulty: str
    attempt: int
    outcome: str
    detail: str = ""
    steps: int = 0
    tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    #: Transient provider failures the retry wrapper absorbed.
    retries: int = 0
    #: Times the model was asked to continue after hitting the output cap.
    continuations: int = 0
    duration_s: float = 0.0
    session_id: str = ""
    sandbox: str = ""

    @property
    def passed(self) -> bool:
        return self.outcome == "passed"

    @property
    def failed(self) -> bool:
        return not self.passed

    @property
    def grader_fault(self) -> bool:
        return self.outcome in GRADER_FAULTS

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "difficulty": self.difficulty,
            "attempt": self.attempt,
            "outcome": self.outcome,
            "passed": self.passed,
            "steps": self.steps,
            "tokens": self.tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "tool_calls": self.tool_calls,
            "tool_errors": self.tool_errors,
            "retries": self.retries,
            "continuations": self.continuations,
            "duration_s": round(self.duration_s, 2),
            "session_id": self.session_id,
            "detail": self.detail,
        }


@dataclass(slots=True)
class DifficultyStat:
    """Aggregated numbers for one difficulty tier."""

    name: str
    tasks: int = 0
    attempts: int = 0
    passed: int = 0
    tokens: int = 0
    steps: int = 0

    @property
    def pass_rate(self) -> float:
        return self.passed / self.attempts if self.attempts else 0.0

    @property
    def tokens_per_pass(self) -> float:
        return self.tokens / self.passed if self.passed else 0.0

    @property
    def steps_per_pass(self) -> float:
        return self.steps / self.passed if self.passed else 0.0


@dataclass(slots=True)
class BenchmarkReport:
    """Everything one benchmark run produced."""

    provider: str = ""
    model: str | None = None
    attempts_per_task: int = 1
    workers: int = 1
    started_at: float = 0.0
    duration_s: float = 0.0
    workdir: str = ""
    results: list[TaskResult] = field(default_factory=list)

    # ---- per-attempt rate -------------------------------------------------

    @property
    def total_attempts(self) -> int:
        return len(self.results)

    @property
    def passed_attempts(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def pass_at_1(self) -> float:
        """Fraction of *attempts* that passed.

        With one attempt per task this is the usual pass rate. With several it
        answers "how often does a single run succeed", which is the number that
        matters when you actually use the agent.
        """
        return self.passed_attempts / self.total_attempts if self.results else 0.0

    # ---- per-task rate ----------------------------------------------------

    def by_task(self) -> dict[str, list[TaskResult]]:
        out: dict[str, list[TaskResult]] = {}
        for result in self.results:
            out.setdefault(result.task_id, []).append(result)
        return out

    @property
    def solved_tasks(self) -> int:
        return sum(1 for rs in self.by_task().values() if any(r.passed for r in rs))

    @property
    def task_count(self) -> int:
        return len(self.by_task())

    @property
    def pass_at_k(self) -> float:
        """Fraction of *tasks* solved by at least one of the k attempts.

        ``k == 1`` makes this equal to :attr:`pass_at_1`; as ``k`` grows it
        answers "is the task solvable at all", which separates a model that
        cannot do something from one that is merely unreliable.
        """
        return self.solved_tasks / self.task_count if self.task_count else 0.0

    # ---- breakdowns -------------------------------------------------------

    def outcomes(self) -> Counter[str]:
        return Counter(r.outcome for r in self.results)

    def failure_breakdown(self) -> dict[str, int]:
        """Non-passing outcomes, most common first."""
        counts = self.outcomes()
        items = [(k, v) for k, v in counts.items() if k != "passed"]
        items.sort(key=lambda kv: (-kv[1], kv[0]))
        return dict(items)

    def by_difficulty(self) -> dict[str, DifficultyStat]:
        stats: dict[str, DifficultyStat] = {}
        seen_tasks: dict[str, set[str]] = {}
        for result in self.results:
            stat = stats.setdefault(result.difficulty, DifficultyStat(name=result.difficulty))
            stat.attempts += 1
            stat.tokens += result.tokens
            stat.steps += result.steps
            if result.passed:
                stat.passed += 1
            seen_tasks.setdefault(result.difficulty, set()).add(result.task_id)
        for name, ids in seen_tasks.items():
            stats[name].tasks = len(ids)
        ordered = {d: stats[d] for d in DIFFICULTIES if d in stats}
        # Anything with a non-standard difficulty still shows up, at the end.
        ordered.update({k: v for k, v in stats.items() if k not in ordered})
        return ordered

    def cost(self) -> dict[str, float]:
        """Token and step cost, split by outcome.

        Reporting cost per *pass* rather than per attempt is intentional: a
        model that fails cheaply is not efficient, it is just failing.
        """
        passed = [r for r in self.results if r.passed]
        failed = [r for r in self.results if not r.passed]
        return {
            "tokens_total": float(sum(r.tokens for r in self.results)),
            "tokens_per_pass": (
                sum(r.tokens for r in passed) / len(passed) if passed else 0.0
            ),
            "tokens_per_failure": (
                sum(r.tokens for r in failed) / len(failed) if failed else 0.0
            ),
            "steps_per_pass": sum(r.steps for r in passed) / len(passed) if passed else 0.0,
            "duration_total_s": sum(r.duration_s for r in self.results),
        }

    def grader_faults(self) -> list[TaskResult]:
        return [r for r in self.results if r.grader_fault]

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "attempts_per_task": self.attempts_per_task,
            "workers": self.workers,
            "duration_s": round(self.duration_s, 2),
            "task_count": self.task_count,
            "total_attempts": self.total_attempts,
            "passed_attempts": self.passed_attempts,
            "pass_at_1": round(self.pass_at_1, 4),
            "solved_tasks": self.solved_tasks,
            "pass_at_k": round(self.pass_at_k, 4),
            "outcomes": dict(self.outcomes()),
            "failures": self.failure_breakdown(),
            "by_difficulty": {
                name: {
                    "tasks": stat.tasks,
                    "attempts": stat.attempts,
                    "passed": stat.passed,
                    "pass_rate": round(stat.pass_rate, 4),
                    "tokens_per_pass": round(stat.tokens_per_pass, 1),
                    "steps_per_pass": round(stat.steps_per_pass, 2),
                }
                for name, stat in self.by_difficulty().items()
            },
            "cost": {k: round(v, 2) for k, v in self.cost().items()},
            "results": [r.to_dict() for r in self.results],
        }


class BenchmarkError(Exception):
    """The run could not start (bad provider, bad task selection, …)."""


def _resolve_model(provider_factory: Callable[[], LLMProvider]) -> str | None:
    """Ask a throwaway provider what model it would use by default.

    Best effort, and deliberately not fatal: the probe exists only so the report
    can name what it measured. If it fails, the attempts themselves will report
    the real error as their outcome, which is a far more useful signal than
    aborting the whole run over a missing label.
    """
    try:
        return provider_factory().resolved_model
    except Exception as exc:  # noqa: BLE001 - see the docstring
        _log.warning("could not resolve the provider's default model: %s", exc)
        return None


# ---- one attempt ------------------------------------------------------------


def run_attempt(
    task: EvalTask,
    *,
    provider_factory: Callable[[], LLMProvider],
    sandbox: Path,
    attempt: int = 1,
    provider_name: str = "",
    model: str | None = None,
    max_steps: int | None = None,
    timeout_s: int | None = None,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    keep_recent: int = DEFAULT_KEEP_RECENT,
    tools: Sequence[Any] | None = None,
    store_path: Path | str | None = None,
    trace: bool = True,
    system_prompt: str | None = None,
) -> TaskResult:
    """Seed, run and grade a single attempt.

    Never raises for agent-side failures — everything ends up in the returned
    result's ``outcome``. A :class:`~loca.eval.tasks.TaskError` from the grader
    is also captured, as ``grader_error``, so one broken task cannot abort a
    whole benchmark run.

    The agent is assembled by :func:`loca.agents.build_agent` — the same call
    ``loca chat`` and the web UI make — so the score describes the agent that
    ships. Context budgeting is part of that assembly: a
    :class:`~loca.core.context.ContextManager` is attached whenever
    ``token_budget`` is positive, with or without a session store. Persistence
    and budgeting are separate concerns, and a benchmark that silently disabled
    compaction when ``store_path`` was omitted would measure a configuration
    nobody actually runs.
    """
    started = time.monotonic()
    session_id = f"bench-{task.id}-a{attempt}"
    result = TaskResult(
        task_id=task.id,
        title=task.title,
        difficulty=task.difficulty,
        attempt=attempt,
        outcome="crash",
        session_id=session_id,
        sandbox=str(sandbox),
    )

    task.seed(sandbox)

    limit = max_steps if max_steps is not None else (task.max_steps or DEFAULT_MAX_STEPS)
    deadline_s = timeout_s if timeout_s is not None else DEFAULT_TASK_TIMEOUT

    tool_list = list(tools) if tools is not None else list(all_tools())

    store: SessionStore | None = None
    recorder: Any = None
    loop: AgentLoop | None = None
    try:
        if store_path is not None:
            store = SessionStore(store_path)

        provider = provider_factory()
        # Assemble the agent the same way `loca chat` and the web UI do, so a
        # score describes the agent that actually ships rather than a
        # benchmark-only configuration. The one deliberate difference is
        # `tools`: an evaluation run may inject its own set.
        runtime = build_agent(
            CODING_AGENT,
            provider=provider,
            workspace=sandbox,
            session_id=session_id,
            store=store,
            # Each attempt gets a fresh sandbox and a fresh session id, so its
            # checkpoints start at 0 — nothing to resume.
            step_index=0,
            tools=tool_list,
            system_prompt=system_prompt,
            max_steps=limit,
            token_budget=token_budget,
            keep_recent=keep_recent,
            provider_name=provider_name,
            trace=trace,
        )
        loop, ctx, recorder = runtime.loop, runtime.ctx, runtime.recorder
        if store is not None:
            # The row has to exist before a transcript can be saved; the CLI
            # does the same thing before it starts a session.
            store.ensure_session(
                session_id,
                workspace=sandbox,
                provider=provider_name or getattr(provider, "name", ""),
                model=model,
            )

        timed_out = False
        error_message: str | None = None
        finish_reason: str | None = None
        for event in loop.run(ctx, task.prompt):
            if recorder is not None:
                recorder.observe(event)

            if event.type is EventType.DONE:
                data = event.data
                finish_reason = str(data.get("reason", "stop"))
                result.steps = int(data.get("steps", 0))
                result.tokens = int(data.get("total_tokens", 0))
            elif event.type is EventType.ERROR:
                error_message = str(event.data.get("message", "provider error"))
            elif event.type is EventType.TOOL_RESULT:
                result.tool_calls += 1
                if event.data.get("is_error"):
                    result.tool_errors += 1
            elif event.type is EventType.RECOVERY:
                # Two things share this event: the loop's "carry on after the
                # output cap" nudge, and a transient provider failure the retry
                # wrapper absorbed. They are counted apart — a truncated reply
                # is not a provider fault, and a benchmark that conflated them
                # could not tell "the model rambles" from "the network wobbles".
                if event.data.get("reason") == "length":
                    result.continuations += 1
                else:
                    result.retries += 1
            elif event.type is EventType.USAGE:
                result.prompt_tokens += int(event.data.get("prompt_tokens", 0))
                result.completion_tokens += int(event.data.get("completion_tokens", 0))

            if time.monotonic() - started > deadline_s:
                # Consume the event, *then* stop. A turn that finished just past
                # the deadline is a finished turn, not a timeout: checking
                # before the DONE branch threw its result away and recorded
                # steps=0 / tokens=0 for a run that had done the work.
                timed_out = finish_reason is None
                break

        if store is not None:
            store.set_next_step(session_id, ctx.step_index)
            if loop.last_transcript:
                store.save_transcript(session_id, loop.last_transcript)

        # ---- classify -----------------------------------------------------
        if error_message is not None:
            result.outcome = "provider_error"
            result.detail = error_message
        elif timed_out:
            result.outcome = "timeout"
            result.detail = f"exceeded {deadline_s}s wall clock"
        elif finish_reason == "max_steps":
            result.outcome = "max_steps"
            result.detail = f"stopped after {limit} steps without finishing"
        else:
            try:
                verdict = task.check(sandbox)
            except TaskError as exc:
                result.outcome = "grader_error"
                result.detail = str(exc)
            else:
                result.outcome = "passed" if verdict.passed else "wrong_answer"
                result.detail = verdict.detail
    except Exception as exc:  # noqa: BLE001 - a harness crash must not kill the run
        result.outcome = "crash"
        result.detail = f"{type(exc).__name__}: {exc}"
    finally:
        if recorder is not None:
            try:
                recorder.close()
            except Exception:  # pragma: no cover - never mask the real outcome
                pass
        if store is not None:
            store.close()

    result.duration_s = time.monotonic() - started
    return result


# ---- the run ----------------------------------------------------------------


def run_benchmark(
    tasks: Sequence[EvalTask] | TaskSet | None = None,
    *,
    provider_factory: Callable[[], LLMProvider],
    provider_name: str = "",
    model: str | None = None,
    attempts: int = 1,
    workers: int = 4,
    max_steps: int | None = None,
    timeout_s: int | None = None,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    keep_recent: int = DEFAULT_KEEP_RECENT,
    workdir: Path | str,
    store_path: Path | str | None = None,
    trace: bool = True,
    keep: bool = False,
    system_prompt: str | None = None,
    progress: Callable[[int, int, TaskResult], None] | None = None,
    on_start: Callable[[int], None] | None = None,
) -> BenchmarkReport:
    """Run every task ``attempts`` times across a thread pool.

    ``workdir`` gets one subdirectory per attempt. It is removed at the end
    unless ``keep`` is set — *including* when the run itself failed, so pass
    ``keep=True`` when you need the sandboxes of a broken run. (This docstring
    used to promise the opposite of what the ``finally`` block did.)
    """
    if tasks is None:
        tasks = load_tasks()
    selected: list[EvalTask] = list(tasks)
    if not selected:
        raise BenchmarkError("no tasks selected")
    if attempts < 1:
        raise BenchmarkError("attempts must be at least 1")

    # The report has to name the model it measured. ``--model`` is usually
    # unset, and a ``"model": null`` in an archived run leaves the evidence
    # unable to state what produced it.
    if model is None:
        model = _resolve_model(provider_factory)

    # Registering into the global registry once, up front, keeps the worker
    # threads from racing to do it (and from mutating it mid-run).
    from loca.tools import register_default_tools

    register_default_tools()
    tool_list = list(all_tools())

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    units = [(task, n + 1) for task in selected for n in range(attempts)]
    total = len(units)
    if on_start is not None:
        on_start(total)

    report = BenchmarkReport(
        provider=provider_name,
        model=model,
        attempts_per_task=attempts,
        workers=max(1, workers),
        started_at=time.time(),
        workdir=str(workdir),
    )

    started = time.monotonic()
    done = 0
    try:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {
                pool.submit(
                    run_attempt,
                    task,
                    provider_factory=provider_factory,
                    sandbox=workdir / f"{task.id}-a{attempt}",
                    attempt=attempt,
                    provider_name=provider_name,
                    model=model,
                    max_steps=max_steps,
                    timeout_s=timeout_s,
                    token_budget=token_budget,
                    keep_recent=keep_recent,
                    tools=tool_list,
                    store_path=store_path,
                    trace=trace,
                    system_prompt=system_prompt,
                ): (task, attempt)
                for task, attempt in units
            }
            for future in as_completed(futures):
                result = future.result()
                report.results.append(result)
                done += 1
                if progress is not None:
                    progress(done, total, result)
    finally:
        report.duration_s = time.monotonic() - started
        if not keep:
            shutil.rmtree(workdir, ignore_errors=True)

    # Stable ordering for reading and diffing: task, then attempt.
    report.results.sort(key=lambda r: (r.task_id, r.attempt))
    return report


def compare(reports: Iterable[BenchmarkReport]) -> list[dict[str, Any]]:
    """Flatten several runs into rows for a side-by-side table.

    Only meaningful when the runs share a task set; the caller is responsible
    for that (the CLI enforces the same ``--limit``/``--difficulty`` filters).
    """
    rows: list[dict[str, Any]] = []
    for report in reports:
        rows.append(
            {
                "provider": report.provider or "?",
                "model": report.model or "(default)",
                "tasks": report.task_count,
                "attempts": report.total_attempts,
                "pass_at_1": report.pass_at_1,
                "pass_at_k": report.pass_at_k,
                "tokens_per_pass": report.cost()["tokens_per_pass"],
                "steps_per_pass": report.cost()["steps_per_pass"],
                "failures": report.failure_breakdown(),
                "duration_s": report.duration_s,
            }
        )
    return rows


# ---- task-set integrity -----------------------------------------------------


@dataclass(slots=True)
class TaskIntegrity:
    """Whether a task behaves the way a task has to behave.

    Three properties are checked, and all of them matter:

    ``fails_on_seed``
        The grader rejects the starting workspace. A task whose grader already
        passes measures nothing — an agent that does nothing would score 100%.
    ``passes_with_solution``
        The grader accepts the reference answer. A task whose grader rejects
        the intended fix is unsolvable, and every failure it reports is noise.
    ``has_solution``
        There is a reference answer to run in the first place. Without this,
        the previous two are vacuous for that task: "the reference solution
        passes" cannot be checked, and not-checked was quietly scored as fine.
    """

    task_id: str
    difficulty: str
    fails_on_seed: bool = False
    passes_with_solution: bool | None = None
    seed_detail: str = ""
    solution_detail: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        """Healthy on all three counts.

        ``passes_with_solution is True``, not ``is not False``: a task with no
        ``solution/`` directory leaves the field ``None``, and letting that
        count as a pass is how a task set reports "all 36 check out" while
        containing tasks nobody can demonstrate are solvable.
        """
        return self.fails_on_seed and self.passes_with_solution is True and not self.error

    @property
    def has_solution(self) -> bool:
        """Did the task ship a reference answer at all?"""
        return self.passes_with_solution is not None


def verify_task_set(
    tasks: Sequence[EvalTask] | TaskSet | None = None,
    *,
    workdir: Path | str,
    keep: bool = False,
) -> list[TaskIntegrity]:
    """Check every task fails on its seed and passes with its reference answer.

    This is the task set's own test suite. It runs without any provider, so it
    is cheap and can be part of ordinary maintenance.

    A task with no ``solution/`` directory fails the check rather than being
    skipped: the whole point is to demonstrate that the task is solvable, and
    "we never checked" is not a demonstration.
    """
    if tasks is None:
        tasks = load_tasks()
    selected = list(tasks)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    report: list[TaskIntegrity] = []
    try:
        for task in selected:
            entry = TaskIntegrity(task_id=task.id, difficulty=task.difficulty)
            try:
                seed_dir = workdir / f"{task.id}-seed"
                task.seed(seed_dir)
                verdict = task.check(seed_dir)
                entry.fails_on_seed = not verdict.passed
                entry.seed_detail = verdict.detail

                if task.has_solution:
                    solved_dir = workdir / f"{task.id}-solved"
                    task.seed(solved_dir)
                    task.apply_solution(solved_dir)
                    solved = task.check(solved_dir)
                    entry.passes_with_solution = solved.passed
                    entry.solution_detail = solved.detail
            except TaskError as exc:
                entry.error = str(exc)
            report.append(entry)
    finally:
        if not keep:
            shutil.rmtree(workdir, ignore_errors=True)
    return report
