"""``bash`` tool: run command lines through Git Bash (MSYS) on Windows.

Why bash is the default
-----------------------

This is not a matter of taste. bash dominates the training corpora of every
model loca talks to: it has been the default shell of the Unix world since
1989, while PowerShell arrived in 2006 and is used mostly by Windows system
administrators rather than by software developers. Two consequences follow,
and both are observable in practice:

- A model writing bash is writing its first language. A model writing
  PowerShell is translating, and translation is where the errors come from —
  quoting rules that differ, hallucinated cmdlets, and long structured error
  text that is easy to misread as success.
- A Unix shell's output is a plain text stream, which is the shape a language
  model reasons about. PowerShell's pipeline carries .NET objects, and how
  they serialise to text depends on the object type and the format settings.

Git Bash is used in preference to WSL because it needs no virtual machine and
crosses no filesystem boundary: ``D:\\Projects\\repo`` stays a Windows path,
and the Windows toolchain on ``PATH`` — the project's own ``.venv``, ``node``,
``git`` — stays reachable.

Exit codes propagate natively here. ``bash -c "pytest"`` returns pytest's own
code, so a failing test run is visible as a failure. That is *not* true of
PowerShell; see :mod:`loca.tools.powershell` for the guard it needs.
"""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path

from loca.tools.shell import ShellTool

#: Well-known Git for Windows install locations. Checked before ``PATH`` so a
#: bundled or shim copy of bash cannot quietly win.
_GIT_BASH_LOCATIONS = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
)


def _find_bash() -> str | None:
    """Absolute path to a real ``bash.exe``, or ``None``.

    Order: ``$LOCA_BASH_PATH`` (an explicit override, the same escape hatch
    Claude Code provides as ``CLAUDE_CODE_GIT_BASH_PATH`` and pi as
    ``shellPath``), then the standard Git for Windows locations, then whatever
    ``PATH`` offers.
    """
    override = os.environ.get("LOCA_BASH_PATH")
    if override and Path(override).is_file():
        return override
    for candidate in _GIT_BASH_LOCATIONS:
        if Path(candidate).is_file():
            return candidate
    return shutil.which("bash")


class BashTool(ShellTool):
    """Run a command line through Git Bash."""

    name = "bash"
    description = (
        "Run a command line through Git Bash — a POSIX shell available on "
        "Windows. Prefer this tool over `powershell` for general work: it is "
        "the shell that most code, CI pipelines and documentation are written "
        "for, so a command is more likely to be right the first time. Use "
        "POSIX commands (ls, cat, grep, find, sed, head, wc), pipes, and "
        "`&&` / `||` chains. Paths may be written POSIX-style "
        "(/d/Projects/repo) or as Windows paths with forward slashes "
        "(D:/Projects/repo) — do not use backslashes here. The working "
        "directory defaults to the workspace and the timeout to 30s; on expiry "
        "the whole process tree is killed. The exit code is the command's own, "
        "so a failing test run reports a non-zero code. Long output is "
        "truncated."
    )

    def _resolve_program(self) -> str:
        located = _find_bash()
        if located is None:
            raise RuntimeError(
                "cannot locate bash.exe. Install Git for Windows "
                "(https://git-scm.com/download/win), or point $LOCA_BASH_PATH "
                "at your bash.exe."
            )
        return located

    def _build_argv(self, command: str, program: str) -> list[str]:
        # -c, not -lc. A login shell would source the user's profile on every
        # single call: slower, and it makes the model's command depend on
        # dotfiles it cannot see.
        return [program, "-c", command]

    def _format_command(self, command: str) -> str:
        # Display only — subprocess receives the raw string. POSIX quoting is
        # the correct spelling for this shell, which is the opposite of the
        # cmd.exe rule this tool used to carry.
        return shlex.quote(command)
