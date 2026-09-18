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
