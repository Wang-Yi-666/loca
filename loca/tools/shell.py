"""Shell tool: execute command lines through Windows ``cmd.exe``.

loca targets **Windows only**. Commands are handed to ``cmd.exe`` and every
path the agent sees or produces is a Windows path (``D:\\repo``, not
``/d/repo``). There is deliberately no POSIX/macOS branch: if a command needs
``ls``, write ``dir``.

Unlike filesystem tools, the shell is *not* sandboxed to the workspace — the
model is expected to run ``git``, ``pip``, ``pytest`` and other commands that
live elsewhere. Safety comes from showing the command, the working directory,
and a clear exit code so the operator can see what the agent did.
"""

from __future__ import annotations

import locale
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from loca.tools.base import Tool, ToolContext, ToolResult
from loca.tools.validation import validate_arguments

# Output caps — large outputs blow the model context window fast.
_MAX_OUTPUT_BYTES = 30_000
_MAX_LINE_LEN = 2_000
_MAX_LINES = 500
_DEFAULT_TIMEOUT = 30  # seconds


def _as_bytes(data: bytes | str | None) -> bytes:
    """Normalize partial-output payloads (TimeoutExpired may give either)."""
    if data is None:
        return b""
    return data if isinstance(data, bytes) else data.encode("utf-8", errors="replace")


def _decode(data: bytes) -> str:
    """Decode child-process output without ever crashing the reader.

    Most CLIs emit UTF-8, but Windows console programs (cmd.exe itself)
    emit text in the ANSI codepage. Try UTF-8 first, then the locale
    encoding, and replace undecodable bytes as a last resort.
    """
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode(locale.getencoding(), errors="replace")
    except (LookupError, UnicodeDecodeError):
        return data.decode("utf-8", errors="replace")


def _format_command(command: str) -> str:
    """Render a command for the transcript header using cmd.exe quoting.

    ``shlex.quote`` produces POSIX single-quoting (``'dir /b'``), which is not
    how cmd.exe reads a line. cmd.exe has no real escape character, so the
    convention is to wrap the whole line in double quotes and double any
    embedded quotes. This is for display only — ``subprocess`` receives the
    raw string.
    """
    return '"' + command.replace('"', '""') + '"'


def _shell_executable() -> str:
    """The shell every command runs through: always cmd.exe, never anything else.

    ``shell=True`` resolves the interpreter from ``%COMSPEC%``. We pin it so a
    COMSPEC someone pointed at PowerShell or Git-Bash cannot silently change the
    command language the model is told to write. A non-``cmd.exe`` COMSPEC is
    ignored in favour of ``cmd.exe`` found on PATH.
    """
    comspec = os.environ.get("COMSPEC")
    if comspec and Path(comspec).stem.lower() == "cmd":
        return comspec
    return "cmd.exe"


class ShellTool(Tool):
    """Execute a command line through cmd.exe and return stdout / stderr / code."""

    name = "shell"
    description = (
        "Run a command line through the Windows command interpreter "
        "(cmd.exe) and return its combined output. Use Windows commands "
        "(dir, type, copy, del, findstr, ...) and Windows paths "
        "(D:\\Projects\\repo) — this is not a POSIX shell, so ls/cat/rm will "
        "not work. By default the working directory is the workspace and the "
        "timeout is 30s. Long output is truncated. Use this to run tests, "
        "install packages, or invoke other CLIs."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The cmd.exe command line to run.",
            },
            "timeout": {
                "type": "integer",
                "minimum": 1,
                "maximum": 600,
                "description": "Timeout in seconds. Default 30, max 600.",
            },
            "cwd": {
                "type": "string",
                "description": (
                    "Working directory for the command, as a Windows path. "
                    "Defaults to the workspace. Must be inside the workspace."
                ),
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        validate_arguments(self.input_schema, arguments)

        command = arguments["command"]
        timeout = int(arguments.get("timeout", _DEFAULT_TIMEOUT))
        cwd_str = arguments.get("cwd")
        if cwd_str is not None:
            cwd_path = (ctx.workspace / cwd_str).resolve()
            try:
                cwd_path.relative_to(ctx.workspace.resolve())
            except ValueError:
                return ToolResult(
                    content=f"Working directory {cwd_str!r} is outside the workspace.",
                    is_error=True,
                )
        else:
            cwd_path = ctx.workspace
            cwd_path.mkdir(parents=True, exist_ok=True)

        # Surface the environment to the model. We at least set HOME so npm,
        # pip etc. can write cache files. (Avoid leaking LOCA_* keys though.)
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("LOCA_")
        }

        start = time.monotonic()
        try:
            # Windows-only: shell=True hands the line to cmd.exe; `executable`
            # pins it so %COMSPEC% can't swap in a different interpreter.
            # Byte capture: cmd.exe and other console programs emit text in the
            # ANSI codepage (e.g. cp936), not UTF-8, so text=True would crash
            # the reader thread on any localized message.
            completed = subprocess.run(
                command,
                shell=True,
                executable=_shell_executable(),
                cwd=str(cwd_path),
                capture_output=True,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.monotonic() - start
            partial = _decode(_as_bytes(exc.stdout)) + _decode(_as_bytes(exc.stderr))
            return ToolResult(
                content=(
                    f"Command timed out after {timeout}s (elapsed {elapsed:.1f}s). "
                    f"Partial output:\n{partial}"
                ),
                is_error=True,
            )
        except Exception as exc:  # pragma: no cover - defensive
            return ToolResult(content=f"Failed to execute: {exc}", is_error=True)

        elapsed = time.monotonic() - start
        stdout = self._truncate(_decode(completed.stdout))
        stderr = self._truncate(_decode(completed.stderr))
        exit_code = completed.returncode

        parts = [
            f"<shell command={_format_command(command)} cwd={cwd_path} "
            f"exit_code={exit_code} elapsed={elapsed:.2f}s timeout={timeout}s>"
        ]
        if stdout:
            parts.append(f"--- stdout ---\n{stdout}")
        if stderr:
            parts.append(f"--- stderr ---\n{stderr}")
        if not stdout and not stderr:
            parts.append("(no output)")

        return ToolResult(
            content="\n".join(parts),
            is_error=exit_code != 0,
        )

    def _truncate(self, text: str) -> str:
        """Cap line count, line length, and total bytes to keep context bounded."""
        if not text:
            return text
        # Per-line cap (preserves newlines).
        lines = text.splitlines()
        truncated_lines = False
        if len(lines) > _MAX_LINES:
            lines = lines[:_MAX_LINES]
            truncated_lines = True
        rendered: list[str] = []
        for line in lines:
            if len(line) > _MAX_LINE_LEN:
                line = line[:_MAX_LINE_LEN] + f"… <line truncated, {len(line)} chars>"
            rendered.append(line)
        out = "\n".join(rendered)
        if truncated_lines:
            out += f"\n… <{len(lines)} lines shown, more truncated>"
        if len(out.encode("utf-8")) > _MAX_OUTPUT_BYTES:
            out = out.encode("utf-8")[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="ignore")
            out += "\n… <output truncated at 30000 bytes>"
        return out
