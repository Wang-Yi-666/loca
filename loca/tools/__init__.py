"""Tool protocol and execution.

The harness exposes a curated set of tools to the model. Each tool has:

- A name and a human-readable description (what the model sees).
- A JSON Schema describing the tool's input (used both for the model and for
  validation when the model returns a call).
- An ``execute(arguments, ctx) -> str`` method that performs the action.

The harness never lets the model invoke arbitrary code — every action must go
through a registered tool, so that arguments can be validated, the call can be
observed, and the blast radius can be bounded. "Bounded" is deliberately not
"sandboxed": the filesystem tools refuse to leave the workspace, while the two
shells are not confined at all — they exist to run programs that live
elsewhere (git, pytest, node). That boundary is documented rather than
pretended away.

Two shells, not one:

``bash``
    Git Bash. The default, because language models are far more reliable in a
    POSIX shell than in PowerShell.
``powershell``
    For Windows-native work — services, ACLs, the registry, cmdlets.
"""

from loca.tools.base import Tool, ToolContext, ToolResult

__all__ = ["Tool", "ToolContext", "ToolResult"]


def register_default_tools() -> None:
    """Register the five built-in tools.

    ``read_file``, ``write_file``, ``edit_file``, ``bash`` and ``powershell``.

    Safe to call multiple times — registration is idempotent.
    """
    from loca.tools.bash import BashTool
    from loca.tools.filesystem import EditFileTool, ReadFileTool, WriteFileTool
    from loca.tools.powershell import PowerShellTool
    from loca.tools.registry import register

    for tool in (
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        BashTool(),
        PowerShellTool(),
    ):
        register(tool)
