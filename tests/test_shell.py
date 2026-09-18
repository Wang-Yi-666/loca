"""Tests for loca.tools.shell.ShellTool.

loca is Windows-only, so these tests assume cmd.exe: they use ``rem`` instead
of ``true`` and ``cd`` instead of ``pwd``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from loca.tools.base import ToolContext
from loca.tools.shell import ShellTool, _format_command, _shell_executable
from loca.tools.validation import SchemaValidationError


@pytest.fixture
def tool() -> ShellTool:
    return ShellTool()


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(workspace=workspace, session_id="test", step_index=0)


def _python(code: str) -> str:
    """A one-liner that runs under cmd.exe, whatever the interpreter path is."""
    return f'{sys.executable} -c "{code}"'


def test_simple_echo(tool: ShellTool, ctx: ToolContext) -> None:
    out = tool.execute({"command": "echo hello"}, ctx)
    assert not out.is_error
    assert "hello" in out.content
    assert "exit_code=0" in out.content


def test_header_quotes_command_the_cmd_way(tool: ShellTool, ctx: ToolContext) -> None:
    """The transcript header double-quotes, it does not shlex-quote."""
    out = tool.execute({"command": "echo hello world"}, ctx)
    assert '<shell command="echo hello world"' in out.content


def test_tool_is_named_shell_not_bash(tool: ShellTool) -> None:
    """The name has to match what actually runs: cmd.exe, not bash."""
    assert tool.name == "shell"


def test_format_command_doubles_embedded_quotes() -> None:
    assert _format_command("dir /b") == '"dir /b"'
    assert _format_command('echo "hi"') == '"echo ""hi"""'


def test_shell_executable_is_always_cmd(monkeypatch: pytest.MonkeyPatch) -> None:
    """A COMSPEC pointing at PowerShell must not change the shell."""
    monkeypatch.setenv("COMSPEC", "C:\\Windows\\System32\\cmd.exe")
    assert _shell_executable().lower().endswith("cmd.exe")

    monkeypatch.setenv("COMSPEC", "C:\\Program Files\\PowerShell\\7\\pwsh.exe")
    assert _shell_executable().lower() == "cmd.exe"

    monkeypatch.delenv("COMSPEC", raising=False)
    assert _shell_executable().lower() == "cmd.exe"


def test_exit_code_nonzero_is_error(tool: ShellTool, ctx: ToolContext) -> None:
    out = tool.execute({"command": "exit 7"}, ctx)
    assert out.is_error
    assert "exit_code=7" in out.content


def test_stderr_is_captured(tool: ShellTool, ctx: ToolContext) -> None:
    # cmd.exe has no clean stderr-only redirection; use a Python one-liner.
    cmd = _python("import sys; sys.stderr.write('oops\\n')")
    out = tool.execute({"command": cmd}, ctx)
    assert "oops" in out.content
    assert "stderr" in out.content.lower()


def test_no_output_message(tool: ShellTool, ctx: ToolContext) -> None:
    # `rem` is cmd.exe's silent no-op (the POSIX equivalent is `true`).
    out = tool.execute({"command": "rem"}, ctx)
    assert not out.is_error
    assert "no output" in out.content


def test_command_uses_workspace_cwd(tool: ShellTool, ctx: ToolContext, workspace: Path) -> None:
    # `cd` with no argument prints the current directory on cmd.exe.
    out = tool.execute({"command": "cd"}, ctx)
    assert str(workspace) in out.content


def test_explicit_cwd_inside_workspace(
    tool: ShellTool, ctx: ToolContext, workspace: Path
) -> None:
    sub = workspace / "subdir"
    sub.mkdir()
    out = tool.execute({"command": "cd", "cwd": "subdir"}, ctx)
    assert "subdir" in out.content


def test_explicit_cwd_accepts_windows_absolute_path(
    tool: ShellTool, ctx: ToolContext, workspace: Path
) -> None:
    """A Windows path outside the workspace is still rejected, absolute or not."""
    out = tool.execute(
        {"command": "cd", "cwd": "C:\\Windows\\System32"},
        ctx,
    )
    assert out.is_error
    assert "outside the workspace" in out.content


def test_explicit_cwd_outside_workspace_rejected(
    tool: ShellTool, ctx: ToolContext
) -> None:
    out = tool.execute({"command": "cd", "cwd": "..\\.."}, ctx)
    assert out.is_error
    assert "outside the workspace" in out.content


def test_timeout_is_respected(tool: ShellTool, ctx: ToolContext) -> None:
    out = tool.execute(
        {"command": _python("import time; time.sleep(3)"), "timeout": 1},
        ctx,
    )
    assert out.is_error
    assert "timed out" in out.content.lower()


def test_output_is_truncated_when_huge(
    tool: ShellTool, ctx: ToolContext, workspace: Path
) -> None:
    out = tool.execute({"command": _python("print('x' * 50000)")}, ctx)
    # Truncation marker should appear
    assert "truncated" in out.content.lower()


def test_environment_isolates_loca_keys(
    tool: ShellTool, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCA_DEEPSEEK_API_KEY", "sk-secret-should-not-leak")
    probe = "import os; print('LEAK' if 'LOCA_DEEPSEEK_API_KEY' in os.environ else 'clean')"
    out = tool.execute({"command": _python(probe)}, ctx)
    # The command string itself contains the word "LEAK" (we print it on
    # leak), so we can't search the whole result. The actual stdout/stderr
    # of the child process is what matters — it should say "clean".
    stdout_section = out.content.split("--- stdout ---", 1)[-1]
    assert "clean" in stdout_section
    assert "LEAK" not in stdout_section.split("--- stderr ---")[0]


def test_missing_command_argument(tool: ShellTool, ctx: ToolContext) -> None:
    with pytest.raises(SchemaValidationError):
        tool.execute({}, ctx)


def test_timeout_must_be_positive(tool: ShellTool, ctx: ToolContext) -> None:
    with pytest.raises(SchemaValidationError):
        tool.execute({"command": "echo", "timeout": 0}, ctx)


def test_unknown_argument_rejected(tool: ShellTool, ctx: ToolContext) -> None:
    with pytest.raises(SchemaValidationError):
        tool.execute({"command": "echo", "mystery": 1}, ctx)
