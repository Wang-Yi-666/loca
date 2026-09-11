"""Argument validation against a tool's JSON Schema.

The model emits ``tool_calls`` whose ``arguments`` are JSON-decoded into a
``dict``. Before we hand those arguments to a tool's ``execute()`` we want
two guarantees:

1. The shape matches the tool's ``input_schema`` (the model didn't lie about
   field names or types).
2. The arguments are safe — paths are absolute and inside the workspace,
   dangerous command flags are filtered, etc.

This module handles (1). Per-tool safety policies live next to the tool
itself (see ``loca.tools.filesystem`` for the path-sandbox policy).
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft7Validator
from jsonschema.exceptions import SchemaError


class SchemaValidationError(ValueError):
    """Raised when ``arguments`` do not satisfy ``schema``."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_arguments(schema: dict[str, Any], arguments: Any) -> None:
    """Validate ``arguments`` against ``schema``. Raise on failure.

    A non-dict ``arguments`` is treated as a schema violation — the model
    was supposed to emit a JSON object.
    """
    try:
        Draft7Validator.check_schema(schema)
    except SchemaError as exc:
        # The tool author wrote a bad schema. This is a programming bug, not
        # a model failure, so we surface it loudly.
        raise RuntimeError(f"Invalid JSON Schema on tool: {exc.message}") from exc

    if not isinstance(arguments, dict):
        raise SchemaValidationError(
            [f"arguments must be a JSON object, got {type(arguments).__name__}"]
        )

    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(arguments), key=lambda e: e.path)
    if errors:
        messages = [_format_error(e) for e in errors]
        raise SchemaValidationError(messages)


def _format_error(err: Any) -> str:
    """Turn a jsonschema error into a one-line, model-friendly message."""
    path = "/".join(str(p) for p in err.absolute_path) or "<root>"
    return f"{path}: {err.message}"
