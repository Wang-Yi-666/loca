"""Tool registry.

Tools register themselves at import time and the loop asks for a snapshot with
:func:`all_tools`. There is deliberately no lookup-by-name: the only consumer is
the agent loop, which always wants the whole set.
"""

from __future__ import annotations

from loca.tools.base import Tool

_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    """Register a tool under its ``name``."""
    _REGISTRY[tool.name] = tool


def all_tools() -> list[Tool]:
    """Snapshot of all registered tools (order is insertion order)."""
    return list(_REGISTRY.values())
