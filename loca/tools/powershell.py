"""``powershell`` tool: run command lines through Windows PowerShell.

Which PowerShell
----------------

PowerShell 7 (``pwsh``) is preferred when installed; otherwise the
Windows-bundled 5.1 is used. The distinction matters, because the two do not
accept the same language:

- 5.1 has no ``&&`` / ``||`` chaining, no ternary operator and no
  null-coalescing. A line written for 7 can be a parse error on 5.1.
- 7 writes UTF-8 by default; 5.1 writes its console in the OEM codepage
  (cp936 on a Chinese system), which is why
  :func:`loca.tools.shell._decode` falls back to the locale encoding.

The tool therefore says which one is in use rather than pinning the prompt to
either — the model can adapt, but only if it knows.

Why the exit code needs a guard
-------------------------------

PowerShell's process exit code reflects whether the *script* failed, not
whether the last native program did. ``powershell -Command "pytest"`` returns
0 even when pytest failed. A model that reads exit codes — which is exactly
how loca decides pass or fail — would report a failing test run as a pass.
That is a silent wrong answer, the most expensive kind of bug this project has.

The fix is to append an explicit guard::

    <command>; if ($LASTEXITCODE -ne $null) { exit $LASTEXITCODE }

Measured on PowerShell 5.1 against the alternatives, because both the naive
fix and the tempting one-liner are wrong:

============================  =====  ==============  =======
command                       raw    ; exit $L.E.    guarded
============================  =====  ==============  =======
``exit 7``                      7          7            7
``cmd /c exit 3``               1          3            3
``Get-ChildItem -Name``         0          0            0
``dir /b`` (a parse error)      1          0  <- lies   1
``Write-Error 'boom'``          1          0  <- lies   1
============================  =====  ==============  =======

The middle column turns every PowerShell error into a success. The guarded
form is the only one of the three that is right in all five cases.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from loca.tools.shell import ShellTool

#: PowerShell 7 installs separately from Windows itself.
_PWSH_LOCATIONS = (
    r"C:\Program Files\PowerShell\7\pwsh.exe",
    r"C:\Program Files\PowerShell\7-preview\pwsh.exe",
)

#: Appended to every command so a failing native program actually fails.
#: See the module docstring for the measurements behind this exact form.
_EXIT_CODE_GUARD = "; if ($LASTEXITCODE -ne $null) { exit $LASTEXITCODE }"


def _find_powershell() -> str | None:
    """Absolute path to a PowerShell interpreter, or ``None``.

    Order: ``$LOCA_PWSH_PATH``, then PowerShell 7, then the bundled 5.1.
    """
    override = os.environ.get("LOCA_PWSH_PATH")
    if override and Path(override).is_file():
        return override
    for candidate in _PWSH_LOCATIONS:
        if Path(candidate).is_file():
            return candidate
    located = shutil.which("pwsh")
    if located:
        return located
    located = shutil.which("powershell")
    if located:
        return located
    for root in (os.environ.get("SystemRoot"), os.environ.get("windir")):
        if not root:
            continue
        fallback = (
            Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        )
        if fallback.is_file():
            return str(fallback)
    return None


class PowerShellTool(ShellTool):
    """Run a command line through Windows PowerShell."""

    name = "powershell"
    description = (
        "Run a command line through Windows PowerShell and return its stdout, "
        "stderr and exit code. Use this for Windows-native work — services, "
        "ACLs, the registry, drive and share management, or cmdlets such as "
        "Get-Service, Get-Acl and Get-ItemProperty. For general scripting, "
        "running tests and invoking git, prefer the `bash` tool.\n"
        "The interpreter is PowerShell 7 when installed, otherwise the "
        "Windows-bundled 5.1; the result header names the one that ran. On 5.1 "
        "there is no `&&` / `||` chaining, no ternary operator and no "
        "null-coalescing: sequence with `;` and check `$LASTEXITCODE` "
        "explicitly. The working directory defaults to the workspace and the "
        "timeout to 30s; on expiry the whole process tree is killed. Long "
        "output is truncated."
    )

    def _resolve_program(self) -> str:
        located = _find_powershell()
        if located is None:
            raise RuntimeError(
                "cannot locate PowerShell: neither pwsh.exe nor "
                r"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe "
                "exists"
            )
        return located

    def _build_argv(self, command: str, program: str) -> list[str]:
        # -NoProfile: the user's profile must not change what the model's
        # command does. -NonInteractive: never block on a prompt.
        return [
            program,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command + _EXIT_CODE_GUARD,
        ]

    def _format_command(self, command: str) -> str:
        # Display only. A single-quoted literal with '' escaping is how
        # PowerShell spells one, so the header reads the way the shell would.
        return "'" + command.replace("'", "''") + "'"
