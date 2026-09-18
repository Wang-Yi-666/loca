"""Tool protocol and execution.

The harness exposes a curated set of tools to the model. Each tool has:

- A name and a human-readable description (what the model sees).
- A JSON Schema describing the tool's input (used both for the model and for
  validation when the model returns a call).
- An ``execute(arguments, ctx) -> str`` method that performs the action.

The harness never lets the model invoke arbitrary code — every action must go
through a registered tool so we can validate, observe, and sandbox it.
"""

from loca.tools.base import Tool, ToolContext, ToolResult

__all__ = ["Tool", "ToolContext", "ToolResult"]


def register_default_tools() -> None:
    """Register the four built-in tools: read_file, write_file, edit_file, shell.

    Safe to call multiple times — registration is idempotent.
    """
    from loca.tools.filesystem import EditFileTool, ReadFileTool, WriteFileTool
    from loca.tools.registry import register
    from loca.tools.shell import ShellTool

    for tool in (ReadFileTool(), WriteFileTool(), EditFileTool(), ShellTool()):
        register(tool)
