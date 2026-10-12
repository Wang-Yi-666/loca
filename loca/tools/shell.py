"""Shared machinery for the command-running tools: ``bash`` and ``powershell``.

loca targets **Windows only** and offers two command tools rather than one:

``bash``
    Git Bash (MSYS). The default. Coding agents are markedly more reliable in
    a POSIX shell than in PowerShell — bash dominates their training data, and
    a Unix shell's text-stream output matches how a model reasons about text.
``powershell``
    PowerShell 7 when installed, otherwise the Windows-bundled 5.1. For
    Windows-native work (services, ACLs, the registry) and cmdlets.

Everything in this module is interpreter-agnostic: the deadline, the
process-tree kill, the pipe draining, the output caps and the byte decoding.
A subclass supplies five things — its ``name``, its ``description``, how to
find its interpreter, how to turn a command line into an argv, and how to
render that line for the transcript. The split matters because the failure
modes documented below were each learned once, and should not have to be
learned again per shell.

Timeouts are a hard bound
-------------------------

``timeout`` is a wall-clock ceiling, not a suggestion. The direct child is the
interpreter, while the real work happens in grandchildren (``python``,
``pytest``, ``npm``…) that inherit the stdout pipe. Killing only the
interpreter leaves those grandchildren alive *and holding the pipe open*, so
collecting the output keeps blocking until they exit on their own — which is
how a declared 2-second timeout ends up taking 8 seconds. On expiry the whole
process tree is therefore killed with ``taskkill /F /T`` before the pipes are
read. See :func:`_kill_process_tree` for what that does and does not reach.

Interpreter resolution
----------------------

Neither tool trusts ``%COMSPEC%`` or a bare program name. Each resolves an
**absolute** path to a file that exists, because ``CreateProcess`` resolves an
``lpApplicationName`` with no directory against the *current directory* — it
does **not** search ``PATH``. A bare ``"bash"`` handed to ``Popen`` therefore
fails with ``WinError 2``. ``shutil.which`` does the searching for us, and the
well-known install locations are checked first so a bundled or shim copy on
``PATH`` cannot quietly win.

Unlike the filesystem tools, the shells are *not* sandboxed to the workspace —
the model is expected to run ``git``, ``pip``, ``pytest`` and other commands
that live elsewhere. Only the *working directory* is checked. Safety comes
from showing the command, the working directory and a clear exit code, so the
operator can see what the agent did.
"""

from __future__ import annotations

import locale
import os
import subprocess
import threading
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
_MAX_TIMEOUT = 600

#: How long to wait for a killed process (and its pipe readers) to finish
#: after the tree kill has closed the write ends. This only covers scheduling.
_REAP_TIMEOUT = 5.0

#: Read size for the pipe-draining threads.
_READ_CHUNK = 8192


def _decode(data: bytes) -> str:
    """Decode child-process output without ever crashing the reader.

    Most CLIs emit UTF-8, and Git Bash does. The Windows-bundled PowerShell
    5.1 does not: it writes its console in the OEM codepage (cp936 on a
    Chinese system), so a strict UTF-8 read would raise on any localized
    message. Try UTF-8 first, then the locale encoding, then replace.
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


def _system32_exe(name: str) -> str | None:
    """Absolute path to a Windows system executable, or ``None`` if absent.

    ``CreateProcess`` resolves an ``lpApplicationName`` that has no directory
    against the *current directory* — it does **not** search ``PATH`` and it
    does not search ``System32``. Any system binary handed to ``subprocess`` as
    ``executable=`` therefore has to be spelled out in full.
    """
    for root in (os.environ.get("SystemRoot"), os.environ.get("windir")):
        if not root:
            continue
        candidate = Path(root) / "System32" / name
        if candidate.is_file():
            return str(candidate)
    return None


def _kill_process_tree(pid: int) -> None:
    """Kill ``pid`` and every process it spawned. Best effort; never raises.

    ``taskkill /T`` walks the parent/child chain and takes the whole set down,
    which closes the stdout/stderr pipes the grandchildren were holding open —
    the step that makes the timeout an actual bound.

    Limitation, stated rather than implied: ``/T`` follows parent-child links,
    so a process that re-parents itself, or a grandchild whose parent has
    already exited, is out of reach. This is still strictly better than
    terminating the interpreter alone.
    """
    taskkill = _system32_exe("taskkill.exe")
    if taskkill is None:  # pragma: no cover - every Windows ships taskkill
        return
    try:
        subprocess.run(
            [taskkill, "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_REAP_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - defensive
        pass


def _drain(stream: Any, sink: list[bytes]) -> None:
    """Read a pipe to EOF, appending to ``sink``. Runs on its own thread."""
    try:
        while True:
            chunk = stream.read(_READ_CHUNK)
            if not chunk:
                break
            sink.append(chunk)
    except (OSError, ValueError):  # pragma: no cover - pipe closed under us
        pass
    finally:
        try:
            stream.close()
        except OSError:  # pragma: no cover
            pass


def _reap(process: subprocess.Popen[bytes]) -> None:
    """Collect a process we just killed without ever blocking forever."""
    try:
        process.wait(timeout=_REAP_TIMEOUT)
        return
    except subprocess.TimeoutExpired:  # pragma: no cover - taskkill found nothing
        pass
    try:
        process.kill()
        process.wait(timeout=_REAP_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):  # pragma: no cover - defensive
        pass


def _run_command(
    argv: list[str],
    *,
    cwd: Path,
    timeout: int,
    env: dict[str, str],
) -> tuple[bytes, bytes, int | None, bool]:
    """Run ``argv``, returning ``(stdout, stderr, exit_code, timed_out)``.

    ``argv`` is an explicit argument list, never ``shell=True``: the
    interpreter is named outright, so there is no intermediate ``/c`` to get
    wrong and no ``%COMSPEC%`` to hijack.

    The pipes are drained by two daemon threads while the main thread waits on
    the process handle. That split is the whole point: ``communicate(timeout=)``
    cannot honour a deadline here, because on expiry it terminates the
    interpreter and *then* waits for the readers — and the readers cannot finish
    until the grandchildren let go of the pipe.
    """
    process = subprocess.Popen(
        argv,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        # Its own process group is what makes the tree addressable as a unit.
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    out_chunks: list[bytes] = []
    err_chunks: list[bytes] = []
    readers = [
        threading.Thread(target=_drain, args=(process.stdout, out_chunks), daemon=True),
        threading.Thread(target=_drain, args=(process.stderr, err_chunks), daemon=True),
    ]
    for reader in readers:
        reader.start()

    timed_out = False
    try:
        # ``wait`` does not touch the pipes, so the deadline is real.
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_tree(process.pid)
        _reap(process)
    for reader in readers:
        reader.join(_REAP_TIMEOUT)

    return b"".join(out_chunks), b"".join(err_chunks), process.returncode, timed_out


class ShellTool(Tool):
    """Base for the command-running tools. Not registered on its own.

    Subclasses provide the five pieces listed in the module docstring. The
    three abstract hooks are deliberately explicit rather than inferred from
    the program's filename: guessing which shell the model is writing for is
    the exact mistake this design removes.
    """

    #: Overridden. The base value is never registered.
    name = "shell"
    description = "Run a command line and return its stdout, stderr and exit code."

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    "The command line to run. Written in the language of the "
                    "shell this tool names, not in any other shell's syntax."
                ),
            },
            "timeout": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MAX_TIMEOUT,
                "description": (
                    f"Timeout in seconds. Default {_DEFAULT_TIMEOUT}, "
                    f"max {_MAX_TIMEOUT}."
                ),
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

    # ---- hooks a subclass must supply -------------------------------------

    def _resolve_program(self) -> str:
        """Absolute path to this tool's interpreter. Raise when unavailable.

        Must return a path to a **file that exists**: the value ends up in
        ``argv[0]``, and a bare name is not searched on ``PATH``.
        """
        raise NotImplementedError

    def _build_argv(self, command: str, program: str) -> list[str]:
        """Turn the model's command line into the argv to execute."""
        raise NotImplementedError

    def _format_command(self, command: str) -> str:
        """Render the command for the transcript header, in this shell's style.

        Display only — ``subprocess`` always receives the raw string.
        """
        raise NotImplementedError

    # ---- the shared pipeline ----------------------------------------------

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

        try:
            program = self._resolve_program()
        except RuntimeError as exc:
            return ToolResult(content=str(exc), is_error=True)

        argv = self._build_argv(command, program)

        # Surface the environment to the model. We at least set HOME so npm,
        # pip etc. can write cache files. (Avoid leaking LOCA_* keys though.)
        env = {k: v for k, v in os.environ.items() if not k.startswith("LOCA_")}

        start = time.monotonic()
        try:
            # Byte capture rather than text=True: PowerShell 5.1 emits its
            # console in the OEM codepage, so a strict UTF-8 decode would
            # crash the reader thread on any localized message.
            raw_out, raw_err, exit_code, timed_out = _run_command(
                argv, cwd=cwd_path, timeout=timeout, env=env
            )
        except Exception as exc:  # pragma: no cover - defensive
            return ToolResult(content=f"Failed to execute: {exc}", is_error=True)

        elapsed = time.monotonic() - start
        # Both paths truncate, so a command that floods the console before
        # being killed cannot push megabytes into the context window.
        stdout = self._truncate(_decode(raw_out))
        stderr = self._truncate(_decode(raw_err))

        if timed_out:
            return ToolResult(
                content=self._render(
                    command=command,
                    cwd_path=cwd_path,
                    stdout=stdout,
                    stderr=stderr,
                    attrs=f"timed_out=true elapsed={elapsed:.2f}s timeout={timeout}s",
                    empty_note="(no output before the timeout)",
                )
                + f"\n\nCommand timed out after {timeout}s. The process tree "
                f"({self.name} and everything it spawned) was killed.",
                is_error=True,
            )

        return ToolResult(
            content=self._render(
                command=command,
                cwd_path=cwd_path,
                stdout=stdout,
                stderr=stderr,
                attrs=(
                    f"exit_code={exit_code} elapsed={elapsed:.2f}s "
                    f"timeout={timeout}s"
                ),
            ),
            is_error=exit_code != 0,
        )

    def _render(
        self,
        *,
        command: str,
        cwd_path: Path,
        stdout: str,
        stderr: str,
        attrs: str,
        empty_note: str = "(no output)",
    ) -> str:
        """The transcript block for one command. stdout and stderr stay apart.

        The header carries the tool name, so a transcript (or a trace) shows
        which interpreter actually ran the line.
        """
        parts = [
            f"<{self.name} command={self._format_command(command)} "
            f"cwd={cwd_path} {attrs}>"
        ]
        if stdout:
            parts.append(f"--- stdout ---\n{stdout}")
        if stderr:
            parts.append(f"--- stderr ---\n{stderr}")
        if not stdout and not stderr:
            parts.append(empty_note)
        return "\n".join(parts)

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
