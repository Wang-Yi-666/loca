"""Tests for loca.tools.bash.BashTool."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from loca.tools.base import ToolContext
from loca.tools.bash import BashTool
from loca.tools.validation import SchemaValidationError


@pytest.fixture
def tool() -> BashTool:
    return BashTool()


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(workspace=workspace, session_id="test", step_index=0)


def test_simple_echo(tool: BashTool, ctx: ToolContext) -> None:
    out = tool.execute({"command": "echo hello"}, ctx)
    assert not out.is_error
    assert "hello" in out.content
    assert "exit_code=0" in out.content


def test_exit_code_nonzero_is_error(tool: BashTool, ctx: ToolContext) -> None:
    out = tool.execute({"command": "exit 7"}, ctx)
    assert out.is_error
    assert "exit_code=7" in out.content


def test_stderr_is_captured(tool: BashTool, ctx: ToolContext) -> None:
    if sys.platform == "win32":
        # cmd.exe doesn't have a clean stderr-only test; use a Python one-liner.
        cmd = f'{sys.executable} -c "import sys; sys.stderr.write(\'oops\\n\')"'
    else:
        cmd = "echo oops 1>&2"
    out = tool.execute({"command": cmd}, ctx)
    assert "oops" in out.content
    assert "stderr" in out.content.lower()


def test_no_output_message(tool: BashTool, ctx: ToolContext) -> None:
    # `true` is a POSIX binary; cmd.exe's silent no-op is `rem`.
    cmd = "rem" if sys.platform == "win32" else "true"
    out = tool.execute({"command": cmd}, ctx)
    assert not out.is_error
    assert "no output" in out.content


def test_command_uses_workspace_cwd(tool: BashTool, ctx: ToolContext, workspace: Path) -> None:
    # pwd should resolve to the workspace path
    if sys.platform == "win32":
        cmd = "cd"
    else:
        cmd = "pwd"
    out = tool.execute({"command": cmd}, ctx)
    assert str(workspace) in out.content


def test_explicit_cwd_inside_workspace(
    tool: BashTool, ctx: ToolContext, workspace: Path
) -> None:
    sub = workspace / "subdir"
    sub.mkdir()
    if sys.platform == "win32":
        cmd = "cd"
    else:
        cmd = "pwd"
    out = tool.execute({"command": cmd, "cwd": "subdir"}, ctx)
    assert "subdir" in out.content


def test_explicit_cwd_outside_workspace_rejected(
    tool: BashTool, ctx: ToolContext
) -> None:
    out = tool.execute({"command": "pwd", "cwd": "../.."}, ctx)
    assert out.is_error
    assert "outside the workspace" in out.content


def test_timeout_is_respected(tool: BashTool, ctx: ToolContext) -> None:
    if sys.platform == "win32":
        # On Windows we sleep via Python.
        cmd = f"{sys.executable} -c \"import time; time.sleep(3)\""
    else:
        cmd = "sleep 3"
    out = tool.execute({"command": cmd, "timeout": 1}, ctx)
    assert out.is_error
    assert "timed out" in out.content.lower()


def test_output_is_truncated_when_huge(
    tool: BashTool, ctx: ToolContext, workspace: Path
) -> None:
    # Generate ~50000 bytes of output
    if sys.platform == "win32":
        cmd = f"{sys.executable} -c \"print('x' * 50000)\""
    else:
        cmd = "python3 -c \"print('x' * 50000)\" || echo xxxxxx"
    out = tool.execute({"command": cmd}, ctx)
    # Truncation marker should appear
    assert "truncated" in out.content.lower()


def test_environment_isolates_loca_keys(
    tool: BashTool, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCA_DEEPSEEK_API_KEY", "sk-secret-should-not-leak")
    probe = "import os; print('LEAK' if 'LOCA_DEEPSEEK_API_KEY' in os.environ else 'clean')"
    cmd = (
        f'{sys.executable} -c "{probe}"'
        if sys.platform == "win32"
        else f'python3 -c "{probe}" || echo clean'
    )
    out = tool.execute({"command": cmd}, ctx)
    # The command string itself contains the word "LEAK" (we print it on
    # leak), so we can't search the whole result. The actual stdout/stderr
    # of the child process is what matters — it should say "clean".
    stdout_section = out.content.split("--- stdout ---", 1)[-1]
    assert "clean" in stdout_section
    assert "LEAK" not in stdout_section.split("--- stderr ---")[0]


def test_missing_command_argument(tool: BashTool, ctx: ToolContext) -> None:
    with pytest.raises(SchemaValidationError):
        tool.execute({}, ctx)


def test_timeout_must_be_positive(tool: BashTool, ctx: ToolContext) -> None:
    with pytest.raises(SchemaValidationError):
        tool.execute({"command": "echo", "timeout": 0}, ctx)


def test_unknown_argument_rejected(tool: BashTool, ctx: ToolContext) -> None:
    with pytest.raises(SchemaValidationError):
        tool.execute({"command": "echo", "mystery": 1}, ctx)
