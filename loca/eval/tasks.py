"""Evaluation task definitions, loading and grading.

A task is a small directory:

.. code-block:: text

    loca/eval/tasks/<task_id>/
    ├── task.json      # prompt + metadata + how to grade
    ├── workspace/     # the files the agent starts with
    ├── hidden/        # withheld from the agent, restored before grading
    ├── solution/      # reference answer; proves the task is solvable
    └── checks.py      # optional custom verifier (referenced by task.json)

``solution/`` is never seeded into a sandbox. It exists so
:func:`~loca.eval.benchmark.verify_task_set` can prove that a task's grader
accepts the intended fix — a task nobody can solve reports nothing but noise.

Two design decisions are worth spelling out, because they are what make the
numbers in a benchmark report mean anything:

**Hidden files.** Anything under ``hidden/`` is *not* seeded into the agent's
sandbox, but it *is* copied back in before grading — overwriting whatever the
agent left behind. That gives the task author two things at once: tests the
agent cannot read (so it has to reason from the prompt rather than fit the
assertions), and protection against the obvious reward hack of editing the
grader. A benchmark that lets the model rewrite its own tests measures nothing.

**Grading is behavioural.** Three kinds are supported, and none of them inspect
the agent's source code:

``pytest``
    Run a pytest suite in the sandbox. The suite normally lives in ``hidden/``.
``run``
    Run a script and compare its stdout and exit status.
``script``
    Call ``verify(workspace) -> (bool, str)`` in the task's ``checks.py``.

Checking behaviour instead of diffs is a deliberate trade: it accepts a
different-but-correct solution, which is what a coding agent is for.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Directory holding the shipped task set.
TASKS_DIR = Path(__file__).resolve().parent / "tasks"

#: Ordered from easiest to hardest. Used for sorting and for the report's
#: per-difficulty breakdown.
DIFFICULTIES: tuple[str, ...] = ("simple", "medium", "hard")

#: Default wall-clock ceiling for grading a single attempt.
DEFAULT_VERIFY_TIMEOUT = 120


class TaskError(Exception):
    """A task directory is malformed. This is a bug in the task set."""


@dataclass(slots=True)
class CheckResult:
    """Outcome of grading one sandbox."""

    passed: bool
    detail: str = ""

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return self.passed


@dataclass(slots=True)
class EvalTask:
    """One evaluable coding task."""

    id: str
    title: str
    difficulty: str
    prompt: str
    root: Path
    checks: dict[str, Any]
    tags: tuple[str, ...] = ()
    timeout_s: int = DEFAULT_VERIFY_TIMEOUT
    max_steps: int | None = None

    # ---- layout -----------------------------------------------------------

    @property
    def seed_dir(self) -> Path:
        """Files the agent is given."""
        return self.root / "workspace"

    @property
    def hidden_dir(self) -> Path:
        """Files withheld from the agent, restored before grading."""
        return self.root / "hidden"

    @property
    def solution_dir(self) -> Path:
        """Reference answer, if the task ships one.

        Never seeded into a sandbox — it exists so the task set can prove
        itself solvable (see :func:`~loca.eval.benchmark.verify_task_set`).
        """
        return self.root / "solution"

    @property
    def has_solution(self) -> bool:
        return self.solution_dir.is_dir()

    def apply_solution(self, dest: Path) -> list[str]:
        """Overlay the reference answer onto ``dest``; return the file names."""
        if not self.has_solution:
            return []
        _copy_tree(self.solution_dir, dest)
        return sorted(
            p.relative_to(self.solution_dir).as_posix()
            for p in self.solution_dir.rglob("*")
            if p.is_file()
        )

    # ---- sandbox lifecycle ------------------------------------------------

    def seed(self, dest: Path) -> None:
        """Materialise the starting workspace at ``dest``.

        Only ``workspace/`` is copied: the whole point of ``hidden/`` is that
        the agent never sees it.
        """
        dest.mkdir(parents=True, exist_ok=True)
        if not self.seed_dir.is_dir():
            # A task may start from an empty directory (e.g. "create the file").
            return
        _copy_tree(self.seed_dir, dest)

    def restore_hidden(self, dest: Path) -> list[str]:
        """Copy ``hidden/`` back over the sandbox; return the restored paths.

        Overwriting rather than merging is intentional: a grader the agent has
        edited must not survive into grading.
        """
        if not self.hidden_dir.is_dir():
            return []
        dest.mkdir(parents=True, exist_ok=True)
        _copy_tree(self.hidden_dir, dest)
        return sorted(
            p.relative_to(self.hidden_dir).as_posix()
            for p in self.hidden_dir.rglob("*")
            if p.is_file()
        )

    # ---- grading ----------------------------------------------------------

    def check(self, workspace: Path) -> CheckResult:
        """Grade the sandbox. Restores hidden files first."""
        self.restore_hidden(workspace)
        kind = str(self.checks.get("kind", "")).lower()
        try:
            if kind == "pytest":
                return self._check_pytest(workspace)
            if kind == "run":
                return self._check_run(workspace)
            if kind == "script":
                return self._check_script(workspace)
        except Exception as exc:  # pragma: no cover - defensive
            raise TaskError(
                f"task {self.id!r} grader crashed: {type(exc).__name__}: {exc}"
            ) from exc
        raise TaskError(f"task {self.id!r} has unknown check kind {kind!r}")

    def _check_pytest(self, workspace: Path) -> CheckResult:
        paths = [str(p) for p in self.checks.get("paths", [])] or ["."]
        args = [a for a in self.checks.get("args", [])]
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            *paths,
            "--no-header",
            "-p",
            "no:cacheprovider",
            *args,
        ]
        proc = _run(cmd, cwd=workspace, timeout=self.timeout_s)
        if proc is None:
            return CheckResult(False, f"pytest timed out after {self.timeout_s}s")
        if proc.returncode == 0:
            return CheckResult(True, _tail(proc.stdout, 400))
        return CheckResult(False, _tail(proc.stdout + proc.stderr, 600))

    def _check_run(self, workspace: Path) -> CheckResult:
        script = str(self.checks["file"])
        cmd = [sys.executable, script, *[str(a) for a in self.checks.get("args", [])]]
        stdin = self.checks.get("stdin", "")
        proc = _run(cmd, cwd=workspace, timeout=self.timeout_s, stdin=stdin)
        if proc is None:
            return CheckResult(False, f"script timed out after {self.timeout_s}s")
        expected_exit = int(self.checks.get("expect_exit", 0))
        if proc.returncode != expected_exit:
            return CheckResult(
                False,
                f"exit {proc.returncode} (expected {expected_exit}): "
                + _tail(proc.stdout + proc.stderr, 400),
            )
        expected = self.checks.get("expect_stdout")
        if expected is not None and _normalize(proc.stdout) != _normalize(str(expected)):
            return CheckResult(
                False,
                f"stdout mismatch\n  expected: {_normalize(str(expected))!r}\n"
                f"  actual:   {_normalize(proc.stdout)!r}",
            )
        return CheckResult(True, _tail(proc.stdout, 200))

    def _check_script(self, workspace: Path) -> CheckResult:
        entry = str(self.checks.get("entry", "checks.py"))
        func = str(self.checks.get("func", "verify"))
        module_path = self.root / entry
        if not module_path.is_file():
            raise TaskError(f"task {self.id!r} declares a script grader but {entry} is missing")
        namespace = _load_module(module_path, f"loca_eval_check_{self.id}")
        verify = getattr(namespace, func, None)
        if verify is None:
            raise TaskError(f"task {self.id!r}: {entry} has no {func}()")
        outcome = verify(workspace)
        if isinstance(outcome, CheckResult):
            return outcome
        if isinstance(outcome, tuple) and len(outcome) == 2:
            return CheckResult(bool(outcome[0]), str(outcome[1]))
        if isinstance(outcome, dict):
            return CheckResult(bool(outcome.get("passed")), str(outcome.get("detail", "")))
        if isinstance(outcome, bool):
            return CheckResult(outcome, "")
        raise TaskError(f"task {self.id!r}: {func}() returned {type(outcome).__name__}")


@dataclass(slots=True)
class TaskSet:
    """A loaded collection of tasks, with a by-difficulty index."""

    tasks: list[EvalTask] = field(default_factory=list)
    root: Path = TASKS_DIR

    def __len__(self) -> int:
        return len(self.tasks)

    def __iter__(self):
        return iter(self.tasks)

    def by_difficulty(self) -> dict[str, list[EvalTask]]:
        out: dict[str, list[EvalTask]] = {d: [] for d in DIFFICULTIES}
        for task in self.tasks:
            out.setdefault(task.difficulty, []).append(task)
        return out

    def counts(self) -> dict[str, int]:
        return {d: len(v) for d, v in self.by_difficulty().items()}

    def get(self, task_id: str) -> EvalTask:
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise KeyError(task_id)

    def select(
        self,
        *,
        ids: list[str] | None = None,
        difficulties: list[str] | None = None,
        limit: int | None = None,
    ) -> list[EvalTask]:
        """Filter the set for a run, preserving the on-disk order."""
        out = list(self.tasks)
        if ids:
            wanted = set(ids)
            out = [t for t in out if t.id in wanted]
        if difficulties:
            wanted_d = set(difficulties)
            out = [t for t in out if t.difficulty in wanted_d]
        if limit is not None and limit > 0:
            out = out[:limit]
        return out


# ---- loading ---------------------------------------------------------------


def load_task(path: Path) -> EvalTask:
    """Read one task directory."""
    manifest = path / "task.json"
    if not manifest.is_file():
        raise TaskError(f"{path.name}: task.json missing")
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TaskError(f"{path.name}: task.json is not valid JSON — {exc}") from exc

    for key in ("id", "title", "difficulty", "prompt", "checks"):
        if key not in raw:
            raise TaskError(f"{path.name}: task.json is missing {key!r}")
    difficulty = str(raw["difficulty"]).lower()
    if difficulty not in DIFFICULTIES:
        raise TaskError(
            f"{path.name}: difficulty {difficulty!r} is not one of {list(DIFFICULTIES)}"
        )
    checks = raw["checks"]
    if not isinstance(checks, dict) or "kind" not in checks:
        raise TaskError(f"{path.name}: checks must be an object with a 'kind'")

    return EvalTask(
        id=str(raw["id"]),
        title=str(raw["title"]),
        difficulty=difficulty,
        prompt=str(raw["prompt"]),
        root=path,
        checks=checks,
        tags=tuple(str(t) for t in raw.get("tags", [])),
        timeout_s=int(raw.get("timeout_s", DEFAULT_VERIFY_TIMEOUT)),
        max_steps=raw.get("max_steps"),
    )


def load_tasks(root: Path | None = None) -> TaskSet:
    """Load every task under ``root``, ordered by difficulty then id.

    Directories starting with ``_`` or ``.`` are ignored, so helper files can
    live alongside the tasks.
    """
    root = Path(root) if root is not None else TASKS_DIR
    if not root.is_dir():
        return TaskSet(tasks=[], root=root)
    loaded: list[EvalTask] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith(("_", ".")):
            continue
        loaded.append(load_task(child))

    order = {name: i for i, name in enumerate(DIFFICULTIES)}
    loaded.sort(key=lambda t: (order.get(t.difficulty, len(order)), t.id))

    seen: set[str] = set()
    for task in loaded:
        if task.id in seen:
            raise TaskError(f"duplicate task id {task.id!r}")
        seen.add(task.id)

    return TaskSet(tasks=loaded, root=root)


# ---- helpers ---------------------------------------------------------------


def _copy_tree(src: Path, dest: Path) -> None:
    """Copy ``src``'s contents into ``dest``, overwriting."""
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dest / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            if target.exists():
                target.unlink()
            shutil.copy2(item, target)


def _load_module(path: Path, name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise TaskError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    timeout: int,
    stdin: str = "",
) -> subprocess.CompletedProcess[str] | None:
    """Run a command, returning None if it exceeded ``timeout``.

    ``PYTHONDONTWRITEBYTECODE`` keeps the sandbox tidy — a stray ``__pycache__``
    would otherwise show up as an unexplained file in the run artefacts.
    """
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd),
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return None


def _normalize(text: str) -> str:
    """Compare stdout in a way that survives Windows line endings.

    The agent's script may print ``\\r\\n`` depending on how it opened stdout;
    that difference is an artefact of the platform, not a wrong answer.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _tail(text: str, limit: int) -> str:
    """Keep the end of a long output — that is where failures usually are."""
    text = text.strip()
    if len(text) <= limit:
        return text
    return "…" + text[-limit:]
