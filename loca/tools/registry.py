"""Tool registry.

Week-1 placeholder. Concrete tools (filesystem / shell) land in Week 2.
"""

from __future__ import annotations

from loca.tools.base import Tool

_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    """Register a tool under its ``name``."""
    _REGISTRY[tool.name] = tool


def get(name: str) -> Tool:
    """Look up a tool by name. Raises ``KeyError`` when missing."""
    if name not in _REGISTRY:
        raise KeyError(f"Tool {name!r} is not registered. Known: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def all_tools() -> list[Tool]:
    """Snapshot of all registered tools (order is insertion order)."""
    return list(_REGISTRY.values())
