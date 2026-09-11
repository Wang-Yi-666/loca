"""Core tool abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ToolContext:
    """Runtime context passed to every tool invocation.

    Tools can read but must not mutate this object — it represents the harness's
    view of the current session.
    """

    workspace: Path
    session_id: str
    step_index: int


@dataclass(slots=True)
class ToolResult:
    """What a tool returns to the model.

    The string form is what the model sees; ``is_error`` flips the role
    semantics so the model knows the call failed.
    """

    content: str
    is_error: bool = False


class Tool(ABC):
    """Base class for all tools."""

    name: str
    description: str
    input_schema: dict[str, Any]

    @abstractmethod
    def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Run the tool and return its result."""

    def to_openai_tool(self) -> dict[str, Any]:
        """Render this tool in OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }
