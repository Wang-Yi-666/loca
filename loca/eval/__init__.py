"""Benchmark and evaluation harness.

Week 6 gives the project a way to answer "is it actually any good?" with a
number instead of an impression: a task set, a runner that grades real
end-to-end agent runs, and a report that separates "the model could not do it"
from "the harness fell over".

The pieces:

``loca.eval.tasks``
    Task definitions, loading, sandbox seeding and grading.
``loca.eval.benchmark``
    The runner: seed → run the real agent loop → grade → aggregate.
``loca.eval.report``
    Rich and JSON rendering for ``loca bench``.

One thing worth being precise about: the task set is raw Python coding work,
and the loop it drives is the reference coding agent —
:data:`loca.agents.CODING_AGENT`, the same prompt and four tools ``loca chat``
and the web UI use. A score therefore reads "this agent solved N of 36 tasks",
not "this harness is N% good": change the spec and the number changes while the
harness does not. ``loca.eval`` sits inside the package because it drives the
real loop rather than a mock, and it is the only part of the project that is
tied to one particular agent.
"""

from loca.eval.benchmark import (
    DEFAULT_MAX_STEPS,
    DEFAULT_TASK_TIMEOUT,
    GRADER_FAULTS,
    OUTCOMES,
    BenchmarkError,
    BenchmarkReport,
    DifficultyStat,
    TaskIntegrity,
    TaskResult,
    compare,
    run_attempt,
    run_benchmark,
    verify_task_set,
)
from loca.eval.report import (
    render,
    render_comparison,
    render_comparison_json,
    render_json,
)
from loca.eval.tasks import (
    DIFFICULTIES,
    TASKS_DIR,
    CheckResult,
    EvalTask,
    TaskError,
    TaskSet,
    load_task,
    load_tasks,
)

__all__ = [
    "DEFAULT_MAX_STEPS",
    "DEFAULT_TASK_TIMEOUT",
    "DIFFICULTIES",
    "GRADER_FAULTS",
    "OUTCOMES",
    "TASKS_DIR",
    "BenchmarkError",
    "BenchmarkReport",
    "CheckResult",
    "DifficultyStat",
    "EvalTask",
    "TaskError",
    "TaskIntegrity",
    "TaskResult",
    "TaskSet",
    "compare",
    "load_task",
    "load_tasks",
    "render",
    "render_comparison",
    "render_comparison_json",
    "render_json",
    "run_attempt",
    "run_benchmark",
    "verify_task_set",
]
