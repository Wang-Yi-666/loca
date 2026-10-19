"""Offline tests for shell tools: bash, powershell and the shared ShellTool base."""

from __future__ import annotations

from pathlib import Path

import pytest

from loca.tools.base import ToolContext
from loca.tools.bash import BashTool
from loca.tools.powershell import _EXIT_CODE_GUARD, PowerShellTool
from loca.tools.shell import (
    _MAX_LINE_LEN,
    _MAX_LINES,
    _check_dangerous_command,
    _decode,
)


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace=tmp_path, session_id="test-session", step_index=0)


# ---- BashTool -------------------------------------------------------------


def test_bash_build_argv_and_format() -> None:
    tool = BashTool()
    argv = tool._build_argv("echo hello && ls", r"C:\Git\bin\bash.exe")
    assert argv == [r"C:\Git\bin\bash.exe", "-c", "echo hello && ls"]

    formatted = tool._format_command("echo hello")
    assert formatted == "'echo hello'"


def test_bash_resolve_program_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tool = BashTool()
    fake_bash = tmp_path / "fake_bash.exe"
    fake_bash.touch()
    monkeypatch.setenv("LOCA_BASH_PATH", str(fake_bash))
    assert tool._resolve_program() == str(fake_bash)


def test_bash_resolve_program_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = BashTool()
    monkeypatch.setenv("LOCA_BASH_PATH", r"C:\nonexistent\bash.exe")
    monkeypatch.setattr("loca.tools.bash._GIT_BASH_LOCATIONS", ())
    monkeypatch.setattr("shutil.which", lambda _: None)

    with pytest.raises(RuntimeError, match="cannot locate bash.exe"):
        tool._resolve_program()


# ---- PowerShellTool -------------------------------------------------------


def test_powershell_build_argv_and_format() -> None:
    tool = PowerShellTool()
    argv = tool._build_argv("Get-Process", r"C:\Windows\System32\powershell.exe")
    assert argv[:4] == [
        r"C:\Windows\System32\powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
    ]
    assert argv[4] == "Get-Process" + _EXIT_CODE_GUARD

    formatted = tool._format_command("it's a test")
    assert formatted == "'it''s a test'"


def test_powershell_resolve_program_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tool = PowerShellTool()
    fake_pwsh = tmp_path / "fake_pwsh.exe"
    fake_pwsh.touch()
    monkeypatch.setenv("LOCA_PWSH_PATH", str(fake_pwsh))
    assert tool._resolve_program() == str(fake_pwsh)


def test_powershell_resolve_program_missing_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = PowerShellTool()
    monkeypatch.setenv("LOCA_PWSH_PATH", r"C:\nonexistent\pwsh.exe")
    monkeypatch.setattr("loca.tools.powershell._PWSH_LOCATIONS", ())
    monkeypatch.setattr("shutil.which", lambda _: None)
    monkeypatch.setattr("os.environ", {})

    with pytest.raises(RuntimeError, match="cannot locate PowerShell"):
        tool._resolve_program()


# ---- Dangerous Command Guards ---------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        "rm -rf /",
        "rm -rf /*",
        "rm -rf ~",
        "rm -rf C:\\",
        "rm -rf C:/",
        "rm -fr /",
        "del /s /q C:\\Windows",
        "del /q /s C:\\System32",
        "rd /s /q C:\\",
        "rmdir /s /q C:\\",
        "format C:",
        "Remove-Item -Recurse -Force C:\\",
        "ri -r -fo C:\\",
        "shutdown /s",
        "shutdown /r /t 0",
        "Stop-Computer",
        "diskpart",
        "bcdedit /set ...",
    ],
)
def test_dangerous_command_is_detected(cmd: str) -> None:
    assert _check_dangerous_command(cmd) is not None


@pytest.mark.parametrize(
    "cmd",
    [
        "pytest -v",
        "git status",
        "rm -rf build dist .pytest_cache",
        "del temp.log",
        "python -m pytest",
        "npm test",
        "git checkout -- .",
        "Get-ChildItem -Name",
    ],
)
def test_safe_commands_are_not_flagged(cmd: str) -> None:
    assert _check_dangerous_command(cmd) is None


def test_shell_tool_rejects_dangerous_command(ctx: ToolContext) -> None:
    tool = BashTool()
    result = tool.execute({"command": "rm -rf /"}, ctx)
    assert result.is_error is True
    assert "Refusing to execute potentially catastrophic command" in result.content


# ---- Sandboxing and Formatting --------------------------------------------


def test_shell_tool_rejects_cwd_outside_workspace(ctx: ToolContext) -> None:
    tool = BashTool()
    result = tool.execute({"command": "echo ok", "cwd": "../../outside"}, ctx)
    assert result.is_error is True
    assert "outside the workspace" in result.content


def test_decode_handles_utf8_and_corrupt_bytes() -> None:
    assert _decode(b"hello world") == "hello world"
    assert _decode(b"") == ""
    # Should decode without raising UnicodeDecodeError
    corrupt = b"\xff\xfe\x99\x88\xaa"
    res = _decode(corrupt)
    assert isinstance(res, str)


def test_truncate_line_and_length_caps() -> None:
    tool = BashTool()
    # Line length cap
    long_line = "a" * (_MAX_LINE_LEN + 100)
    truncated = tool._truncate(long_line)
    assert "line truncated" in truncated

    # Line count cap
    many_lines = "\n".join(f"line {i}" for i in range(_MAX_LINES + 50))
    truncated_lines = tool._truncate(many_lines)
    assert "lines shown, more truncated" in truncated_lines

    # Byte cap (400 lines of 100 chars = 40k bytes, each line < 2000 and total lines < 500)
    huge_text = "\n".join("x" * 100 for _ in range(400))
    truncated_bytes = tool._truncate(huge_text)
    assert "output truncated at 30000 bytes" in truncated_bytes


# ---- Real Invocation Tests (using built-in PowerShell) --------------------


def test_powershell_real_execution_happy_path(ctx: ToolContext) -> None:
    tool = PowerShellTool()
    result = tool.execute({"command": "Write-Output 'loca_test_ok'"}, ctx)
    assert result.is_error is False
    assert "loca_test_ok" in result.content
    assert "exit_code=0" in result.content


def test_powershell_real_execution_nonzero_exit_code(ctx: ToolContext) -> None:
    tool = PowerShellTool()
    result = tool.execute({"command": "exit 7"}, ctx)
    assert result.is_error is True
    assert "exit_code=7" in result.content
