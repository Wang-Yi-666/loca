"""Bash tool: execute shell commands.

Unlike filesystem tools, bash is *not* sandboxed to the workspace — the model
is expected to run ``git``, ``pip``, ``pytest`` and other commands that
live elsewhere. Safety comes from showing the command, the working directory,
and a clear exit code so the operator can see what the agent did.
"""

from __future__ import annotations

import locale
import os
import shlex
import subprocess
import time
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


class BashTool(Tool):
    """Execute a shell command and return stdout / stderr / exit code."""

    name = "bash"
    description = (
        "Execute a shell command (POSIX sh on Unix, cmd.exe on Windows) and "
        "return its combined output. By default the working directory is the "
        "workspace and the timeout is 30s. Long output is truncated. Use "
        "this to run tests, install packages, or invoke other CLIs."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to run.",
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
                    "Working directory for the command. Defaults to the "
                    "workspace. Must be inside the workspace."
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
            # Byte capture: child processes on Windows emit text in the ANSI
            # codepage (e.g. cp936), not UTF-8, so text=True would crash the
            # reader thread on any localized cmd.exe message.
            completed = subprocess.run(
                command,
                shell=True,
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
            f"<bash command={shlex.quote(command)!s} cwd={cwd_path} "
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
