"""Tests for the Week-6 evaluation task set: loading, sandboxing and grading.

Nothing here touches a provider. The interesting properties are about the task
*set* rather than any one model run:

- a task's ``hidden/`` files are withheld from the agent but restored before
  grading, so a model cannot pass by editing its own grader;
- a task is only valid if its grader rejects the starting workspace and accepts
  the reference answer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loca.eval.benchmark import verify_task_set
from loca.eval.tasks import (
    CheckResult,
    EvalTask,
    TaskError,
    TaskSet,
    load_task,
    load_tasks,
)

# A reference "add" module and the grader that checks it. Several tests need the
# same three-line fixture, so they are named once and reused.
ADD_OK = "def add(a, b):\n    return a + b\n"
ADD_BROKEN = "def add(a, b):\n    return a - b\n"
GRADES_ADD = "from solution import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
GRADES_ADD_IMPOSSIBLY = (
    "from solution import add\n\n\ndef test_add():\n    assert add(1, 2) == 99\n"
)


def _write_task(
    root: Path,
    task_id: str = "t1",
    *,
    seed: dict[str, str] | None = None,
    hidden: dict[str, str] | None = None,
    solution: dict[str, str] | None = None,
    checks: dict | None = None,
    difficulty: str = "simple",
    extra: dict | None = None,
) -> Path:
    """Build a throwaway task directory."""
    path = root / task_id
    (path / "workspace").mkdir(parents=True)
    for name, content in (seed or {}).items():
        (path / "workspace" / name).write_text(content, encoding="utf-8", newline="\n")
    if hidden:
        (path / "hidden").mkdir()
        for name, content in hidden.items():
            (path / "hidden" / name).write_text(content, encoding="utf-8", newline="\n")
    if solution:
        (path / "solution").mkdir()
        for name, content in solution.items():
            (path / "solution" / name).write_text(content, encoding="utf-8", newline="\n")

    manifest = {
        "id": task_id,
        "title": f"task {task_id}",
        "difficulty": difficulty,
        "prompt": "do the thing",
        "checks": checks or {"kind": "pytest", "paths": ["test_it.py"]},
    }
    manifest.update(extra or {})
    (path / "task.json").write_text(json.dumps(manifest), encoding="utf-8")
    return path


# ---- the shipped task set ---------------------------------------------------


def test_the_shipped_task_set_loads() -> None:
    tasks = load_tasks()
    assert len(tasks) >= 30, "a benchmark needs a meaningful task count"
    assert tasks.counts() == {"simple": 14, "medium": 12, "hard": 10}


def test_every_shipped_task_has_the_fields_a_runner_needs() -> None:
    for task in load_tasks():
        assert task.prompt.strip(), task.id
        assert task.title.strip(), task.id
        assert task.tags, task.id
        assert task.checks.get("kind") in {"pytest", "run", "script"}, task.id


def test_every_shipped_task_ships_a_reference_solution() -> None:
    """Without one, the task cannot be proven solvable.

    The solution is only *inspected* here, never applied: writing it over the
    shipped seed would quietly destroy the deliberately-broken starting state.
    """
    for task in load_tasks():
        assert task.has_solution, task.id
        assert any(p.is_file() for p in task.solution_dir.rglob("*")), task.id


def test_shipped_tasks_are_ordered_easiest_first() -> None:
    order = [t.difficulty for t in load_tasks()]
    rank = {"simple": 0, "medium": 1, "hard": 2}
    assert [rank[d] for d in order] == sorted(rank[d] for d in order)


def test_shipped_grader_files_are_withheld_from_the_agent() -> None:
    """A grader the agent can read is a grader the agent can fit to."""
    for task in load_tasks():
        assert task.hidden_dir.is_dir(), task.id
        hidden_names = {p.name for p in task.hidden_dir.iterdir()}
        seed_names = {p.name for p in task.seed_dir.iterdir()} if task.seed_dir.is_dir() else set()
        assert not (hidden_names & seed_names), f"{task.id} seeds a file it also hides"


def test_shipped_seeds_are_not_already_solved() -> None:
    """A regression guard: the seed must differ from the reference answer.

    If a stray ``apply_solution`` ever overwrites a shipped ``workspace/``, the
    task silently stops measuring anything — every attempt would pass for free.
    Comparing the files on disk catches that without spending a provider call.
    """
    for task in load_tasks():
        identical = []
        for source in (p for p in task.solution_dir.rglob("*") if p.is_file()):
            target = task.seed_dir / source.relative_to(task.solution_dir)
            if target.is_file() and target.read_bytes() == source.read_bytes():
                identical.append(source.name)
        assert not identical, f"{task.id}: seed already contains {identical}"


# ---- loading and validation -------------------------------------------------


def test_load_task_reads_the_manifest(tmp_path: Path) -> None:
    path = _write_task(tmp_path, "alpha", extra={"tags": ["x"], "timeout_s": 5})
    task = load_task(path)
    assert task.id == "alpha"
    assert task.difficulty == "simple"
    assert task.tags == ("x",)
    assert task.timeout_s == 5


def test_load_tasks_reports_counts_and_ignores_private_dirs(tmp_path: Path) -> None:
    _write_task(tmp_path, "a")
    _write_task(tmp_path, "b", difficulty="hard")
    (tmp_path / "_scratch").mkdir()
    (tmp_path / ".hidden").mkdir()
    tasks = load_tasks(tmp_path)
    assert [t.id for t in tasks] == ["a", "b"]
    assert tasks.counts() == {"simple": 1, "medium": 0, "hard": 1}


def test_load_tasks_on_a_missing_directory_is_empty(tmp_path: Path) -> None:
    assert len(load_tasks(tmp_path / "nope")) == 0


@pytest.mark.parametrize("missing", ["id", "title", "difficulty", "prompt", "checks"])
def test_a_missing_manifest_key_is_rejected(tmp_path: Path, missing: str) -> None:
    path = _write_task(tmp_path)
    raw = json.loads((path / "task.json").read_text(encoding="utf-8"))
    del raw[missing]
    (path / "task.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(TaskError, match=missing):
        load_task(path)


def test_an_unknown_difficulty_is_rejected(tmp_path: Path) -> None:
    path = _write_task(tmp_path, difficulty="impossible")
    with pytest.raises(TaskError, match="difficulty"):
        load_task(path)


def test_malformed_json_is_reported_as_a_task_error(tmp_path: Path) -> None:
    path = _write_task(tmp_path)
    (path / "task.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(TaskError, match="not valid JSON"):
        load_task(path)


def test_a_missing_manifest_is_reported(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(TaskError, match="task.json missing"):
        load_task(tmp_path / "empty")


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    _write_task(tmp_path, "dup")
    # A second directory claiming the same id.
    other = tmp_path / "other"
    other.mkdir()
    raw = json.loads((tmp_path / "dup" / "task.json").read_text(encoding="utf-8"))
    (other / "task.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(TaskError, match="duplicate"):
        load_tasks(tmp_path)


def test_checks_without_a_kind_is_rejected(tmp_path: Path) -> None:
    path = _write_task(tmp_path, checks={"paths": ["x.py"]})
    with pytest.raises(TaskError, match="kind"):
        load_task(path)


# ---- selecting --------------------------------------------------------------


def test_select_filters_by_difficulty_id_and_limit(tmp_path: Path) -> None:
    _write_task(tmp_path, "a", difficulty="simple")
    _write_task(tmp_path, "b", difficulty="medium")
    _write_task(tmp_path, "c", difficulty="hard")
    tasks = load_tasks(tmp_path)

    assert [t.id for t in tasks.select(difficulties=["medium"])] == ["b"]
    assert [t.id for t in tasks.select(ids=["c", "a"])] == ["a", "c"]
    assert [t.id for t in tasks.select(limit=2)] == ["a", "b"]
    assert tasks.select(limit=0) == tasks.tasks
    assert tasks.select(ids=["nope"]) == []


def test_get_raises_for_an_unknown_id(tmp_path: Path) -> None:
    _write_task(tmp_path, "a")
    tasks = load_tasks(tmp_path)
    assert tasks.get("a").id == "a"
    with pytest.raises(KeyError):
        tasks.get("zzz")


def test_task_set_is_iterable_and_sized(tmp_path: Path) -> None:
    _write_task(tmp_path, "a")
    tasks: TaskSet = load_tasks(tmp_path)
    assert len(tasks) == 1
    assert [t.id for t in tasks] == ["a"]


# ---- sandbox lifecycle ------------------------------------------------------


def test_seed_copies_the_workspace_but_not_the_hidden_files(tmp_path: Path) -> None:
    path = _write_task(
        tmp_path,
        seed={"main.py": "x = 1\n"},
        hidden={"test_it.py": "def test_x(): pass\n"},
    )
    task = load_task(path)
    sandbox = tmp_path / "sandbox"
    task.seed(sandbox)

    assert (sandbox / "main.py").read_text(encoding="utf-8") == "x = 1\n"
    assert not (sandbox / "test_it.py").exists(), "hidden graders must not be seeded"


def test_restore_hidden_overwrites_whatever_the_agent_left_behind(tmp_path: Path) -> None:
    """The anti-reward-hack property: editing the grader cannot help."""
    path = _write_task(tmp_path, hidden={"test_it.py": "original\n"})
    task = load_task(path)
    sandbox = tmp_path / "sandbox"
    task.seed(sandbox)

    (sandbox / "test_it.py").write_text("def test_everything(): pass\n", encoding="utf-8")
    restored = task.restore_hidden(sandbox)

    assert restored == ["test_it.py"]
    assert (sandbox / "test_it.py").read_text(encoding="utf-8") == "original\n"


def test_restore_hidden_on_a_task_without_hidden_files_is_a_no_op(tmp_path: Path) -> None:
    path = _write_task(tmp_path)
    task = load_task(path)
    sandbox = tmp_path / "sandbox"
    task.seed(sandbox)
    assert task.restore_hidden(sandbox) == []


def test_seeding_an_empty_workspace_is_allowed(tmp_path: Path) -> None:
    """Some tasks start from nothing and ask the agent to create the file."""
    path = tmp_path / "empty-task"
    path.mkdir()
    (path / "task.json").write_text(
        json.dumps(
            {
                "id": "empty-task",
                "title": "from scratch",
                "difficulty": "simple",
                "prompt": "create hello.py",
                "checks": {"kind": "run", "file": "hello.py", "expect_stdout": "hi"},
            }
        ),
        encoding="utf-8",
    )
    task = load_task(path)
    sandbox = tmp_path / "sandbox"
    task.seed(sandbox)
    assert sandbox.is_dir()
    assert list(sandbox.iterdir()) == []


# ---- grading kinds ----------------------------------------------------------


def test_pytest_grader_accepts_a_correct_file(tmp_path: Path) -> None:
    path = _write_task(
        tmp_path,
        seed={"solution.py": ADD_OK},
        hidden={"test_it.py": GRADES_ADD},
    )
    task = load_task(path)
    sandbox = tmp_path / "sandbox"
    task.seed(sandbox)
    assert task.check(sandbox).passed


def test_pytest_grader_rejects_a_wrong_file(tmp_path: Path) -> None:
    path = _write_task(
        tmp_path,
        seed={"solution.py": ADD_BROKEN},
        hidden={"test_it.py": GRADES_ADD},
    )
    task = load_task(path)
    sandbox = tmp_path / "sandbox"
    task.seed(sandbox)
    result = task.check(sandbox)
    assert not result.passed
    assert "assert" in result.detail


def test_run_grader_compares_stdout_and_exit_code(tmp_path: Path) -> None:
    path = _write_task(
        tmp_path,
        seed={"main.py": 'print("42")\n'},
        checks={"kind": "run", "file": "main.py", "expect_stdout": "42"},
    )
    task = load_task(path)
    sandbox = tmp_path / "sandbox"
    task.seed(sandbox)
    assert task.check(sandbox).passed


def test_run_grader_tolerates_windows_line_endings(tmp_path: Path) -> None:
    path = _write_task(
        tmp_path,
        seed={"main.py": 'print("a")\nprint("b")\n'},
        checks={"kind": "run", "file": "main.py", "expect_stdout": "a\nb"},
    )
    task = load_task(path)
    sandbox = tmp_path / "sandbox"
    task.seed(sandbox)
    assert task.check(sandbox).passed


def test_run_grader_reports_a_stdout_mismatch(tmp_path: Path) -> None:
    path = _write_task(
        tmp_path,
        seed={"main.py": 'print("nope")\n'},
        checks={"kind": "run", "file": "main.py", "expect_stdout": "42"},
    )
    task = load_task(path)
    sandbox = tmp_path / "sandbox"
    task.seed(sandbox)
    result = task.check(sandbox)
    assert not result.passed
    assert "mismatch" in result.detail


def test_run_grader_checks_the_exit_code(tmp_path: Path) -> None:
    path = _write_task(
        tmp_path,
        seed={"main.py": "raise SystemExit(3)\n"},
        checks={"kind": "run", "file": "main.py", "expect_exit": 3},
    )
    task = load_task(path)
    sandbox = tmp_path / "sandbox"
    task.seed(sandbox)
    assert task.check(sandbox).passed


def test_run_grader_passes_stdin(tmp_path: Path) -> None:
    path = _write_task(
        tmp_path,
        seed={"main.py": "import sys\nprint(sys.stdin.read().upper())\n"},
        checks={"kind": "run", "file": "main.py", "stdin": "hi", "expect_stdout": "HI"},
    )
    task = load_task(path)
    sandbox = tmp_path / "sandbox"
    task.seed(sandbox)
    assert task.check(sandbox).passed


def test_script_grader_can_inspect_the_workspace(tmp_path: Path) -> None:
    path = _write_task(tmp_path, seed={"note.txt": "hello\n"})
    (path / "checks.py").write_text(
        "from pathlib import Path\n\n\n"
        "def verify(workspace):\n"
        "    text = (Path(workspace) / 'note.txt').read_text(encoding='utf-8').strip()\n"
        "    return text == 'hello', f'saw {text!r}'\n",
        encoding="utf-8",
    )
    task = load_task(path)
    task.checks = {"kind": "script", "entry": "checks.py"}
    sandbox = tmp_path / "sandbox"
    task.seed(sandbox)
    result = task.check(sandbox)
    assert isinstance(result, CheckResult)
    assert result.passed


def test_script_grader_reports_its_detail(tmp_path: Path) -> None:
    path = _write_task(tmp_path, seed={"note.txt": "bye\n"})
    (path / "checks.py").write_text(
        "def verify(workspace):\n    return False, 'nope'\n", encoding="utf-8"
    )
    task = load_task(path)
    task.checks = {"kind": "script", "entry": "checks.py"}
    sandbox = tmp_path / "sandbox"
    task.seed(sandbox)
    result = task.check(sandbox)
    assert not result.passed
    assert result.detail == "nope"


def test_script_grader_accepts_a_bool(tmp_path: Path) -> None:
    path = _write_task(tmp_path)
    (path / "checks.py").write_text("def verify(workspace):\n    return True\n", encoding="utf-8")
    task = load_task(path)
    task.checks = {"kind": "script", "entry": "checks.py"}
    sandbox = tmp_path / "sandbox"
    task.seed(sandbox)
    assert task.check(sandbox).passed


def test_script_grader_accepts_a_dict(tmp_path: Path) -> None:
    path = _write_task(tmp_path)
    (path / "checks.py").write_text(
        "def verify(workspace):\n    return {'passed': True, 'detail': 'ok'}\n",
        encoding="utf-8",
    )
    task = load_task(path)
    task.checks = {"kind": "script", "entry": "checks.py"}
    sandbox = tmp_path / "sandbox"
    task.seed(sandbox)
    assert task.check(sandbox).passed


def test_unknown_check_kind_is_rejected(tmp_path: Path) -> None:
    path = _write_task(tmp_path, checks={"kind": "vibes"})
    task = load_task(path)
    sandbox = tmp_path / "sandbox"
    task.seed(sandbox)
    with pytest.raises(TaskError, match="unknown check kind"):
        task.check(sandbox)


def test_script_grader_without_the_function_is_rejected(tmp_path: Path) -> None:
    path = _write_task(tmp_path)
    (path / "checks.py").write_text(
        "def something_else(workspace):\n    return True\n", encoding="utf-8"
    )
    task = load_task(path)
    task.checks = {"kind": "script", "entry": "checks.py"}
    sandbox = tmp_path / "sandbox"
    task.seed(sandbox)
    with pytest.raises(TaskError, match="has no verify"):
        task.check(sandbox)


def test_script_grader_without_the_file_is_rejected(tmp_path: Path) -> None:
    path = _write_task(tmp_path)
    task = load_task(path)
    task.checks = {"kind": "script", "entry": "checks.py"}
    sandbox = tmp_path / "sandbox"
    task.seed(sandbox)
    with pytest.raises(TaskError, match="is missing"):
        task.check(sandbox)


# ---- reference solutions ----------------------------------------------------


def test_apply_solution_overlays_the_seed(tmp_path: Path) -> None:
    path = _write_task(
        tmp_path,
        seed={"a.py": "broken\n", "keep.py": "untouched\n"},
        solution={"a.py": "fixed\n"},
    )
    task = load_task(path)
    sandbox = tmp_path / "sandbox"
    task.seed(sandbox)
    applied = task.apply_solution(sandbox)

    assert applied == ["a.py"]
    assert (sandbox / "a.py").read_text(encoding="utf-8") == "fixed\n"
    assert (sandbox / "keep.py").read_text(encoding="utf-8") == "untouched\n"


def test_apply_solution_without_a_solution_is_a_no_op(tmp_path: Path) -> None:
    path = _write_task(tmp_path)
    task = load_task(path)
    sandbox = tmp_path / "sandbox"
    task.seed(sandbox)
    assert task.apply_solution(sandbox) == []


# ---- integrity checking -----------------------------------------------------


def test_verify_task_set_accepts_a_well_formed_task(tmp_path: Path) -> None:
    _write_task(
        tmp_path,
        seed={"solution.py": ADD_BROKEN},
        hidden={"test_it.py": GRADES_ADD},
        solution={"solution.py": ADD_OK},
    )
    report = verify_task_set(load_tasks(tmp_path), workdir=tmp_path / "work")
    assert len(report) == 1
    assert report[0].ok
    assert report[0].fails_on_seed
    assert report[0].passes_with_solution is True


def test_verify_task_set_flags_a_grader_that_already_passes_on_the_seed(tmp_path: Path) -> None:
    """A task you can pass by doing nothing measures nothing."""
    _write_task(
        tmp_path,
        seed={"solution.py": ADD_OK},
        hidden={"test_it.py": GRADES_ADD},
        solution={"solution.py": ADD_OK},
    )
    report = verify_task_set(load_tasks(tmp_path), workdir=tmp_path / "work")
    assert not report[0].ok
    assert not report[0].fails_on_seed


def test_verify_task_set_flags_an_unsolvable_task(tmp_path: Path) -> None:
    _write_task(
        tmp_path,
        seed={"solution.py": ADD_BROKEN},
        hidden={"test_it.py": GRADES_ADD_IMPOSSIBLY},
        solution={"solution.py": ADD_OK},
    )
    report = verify_task_set(load_tasks(tmp_path), workdir=tmp_path / "work")
    assert not report[0].ok
    assert report[0].passes_with_solution is False


def test_verify_task_set_reports_a_task_without_a_solution(tmp_path: Path) -> None:
    _write_task(
        tmp_path,
        seed={"solution.py": ADD_BROKEN},
        hidden={"test_it.py": GRADES_ADD},
    )
    report = verify_task_set(load_tasks(tmp_path), workdir=tmp_path / "work")
    assert report[0].passes_with_solution is None
    assert not report[0].has_solution
    # Still fine as far as "rejects the seed" goes, but not proven solvable.
    assert report[0].ok


def test_verify_task_set_survives_a_crashing_grader(tmp_path: Path) -> None:
    _write_task(tmp_path, checks={"kind": "vibes"})
    report = verify_task_set(load_tasks(tmp_path), workdir=tmp_path / "work")
    assert report[0].error
    assert not report[0].ok


def test_verify_task_set_cleans_up_its_working_directory(tmp_path: Path) -> None:
    _write_task(
        tmp_path,
        seed={"solution.py": ADD_BROKEN},
        hidden={"test_it.py": GRADES_ADD},
    )
    workdir = tmp_path / "work"
    verify_task_set(load_tasks(tmp_path), workdir=workdir)
    assert not workdir.exists(), "the scratch tree is removed, not just emptied"


def test_verify_task_set_can_keep_the_working_directory(tmp_path: Path) -> None:
    _write_task(
        tmp_path,
        seed={"solution.py": ADD_BROKEN},
        hidden={"test_it.py": GRADES_ADD},
    )
    workdir = tmp_path / "work"
    verify_task_set(load_tasks(tmp_path), workdir=workdir, keep=True)
    assert (workdir / "t1-seed").is_dir()


# ---- one real shipped task, end to end --------------------------------------


@pytest.mark.parametrize("task_id", ["fix-off-by-one", "fix-page-boundary"])
def test_a_real_task_fails_on_seed_and_passes_with_its_solution(
    tmp_path: Path, task_id: str
) -> None:
    task: EvalTask = load_tasks().get(task_id)
    seed_dir = tmp_path / f"{task_id}-seed"
    task.seed(seed_dir)
    assert not task.check(seed_dir).passed

    solved_dir = tmp_path / f"{task_id}-solved"
    task.seed(solved_dir)
    task.apply_solution(solved_dir)
    assert task.check(solved_dir).passed
