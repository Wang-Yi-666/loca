"""Tests for loca.tools.validation."""

from __future__ import annotations

import pytest

from loca.tools.validation import SchemaValidationError, validate_arguments


def _ok_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "limit": {"type": "integer", "minimum": 0},
        },
        "required": ["path"],
        "additionalProperties": False,
    }


def test_accepts_minimal_valid_arguments() -> None:
    validate_arguments(_ok_schema(), {"path": "x.txt"})


def test_accepts_all_optional_fields() -> None:
    validate_arguments(_ok_schema(), {"path": "x.txt", "limit": 10})


def test_rejects_missing_required() -> None:
    with pytest.raises(SchemaValidationError) as exc:
        validate_arguments(_ok_schema(), {})
    assert "path" in str(exc.value)


def test_rejects_wrong_type() -> None:
    with pytest.raises(SchemaValidationError):
        validate_arguments(_ok_schema(), {"path": 123})


def test_rejects_unknown_property() -> None:
    with pytest.raises(SchemaValidationError) as exc:
        validate_arguments(_ok_schema(), {"path": "x", "extra": 1})
    assert "extra" in str(exc.value) or "additional" in str(exc.value).lower()


def test_rejects_minimum_violation() -> None:
    with pytest.raises(SchemaValidationError):
        validate_arguments(_ok_schema(), {"path": "x", "limit": -1})


def test_rejects_non_dict_arguments() -> None:
    with pytest.raises(SchemaValidationError) as exc:
        validate_arguments(_ok_schema(), "not a dict")  # type: ignore[arg-type]
    assert "object" in str(exc.value)


def test_rejects_bad_schema_at_definition_time() -> None:
    with pytest.raises(RuntimeError):
        validate_arguments({"type": "not-a-type"}, {"path": "x"})


def test_error_message_includes_path() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "object", "properties": {"b": {"type": "integer"}}}},
        "required": ["a"],
    }
    with pytest.raises(SchemaValidationError) as exc:
        validate_arguments(schema, {"a": {"b": "not-an-int"}})
    assert "b" in str(exc.value)


def test_error_list_is_exposed() -> None:
    with pytest.raises(SchemaValidationError) as exc:
        validate_arguments(_ok_schema(), {})
    assert exc.value.errors  # non-empty
    assert all(isinstance(e, str) for e in exc.value.errors)
