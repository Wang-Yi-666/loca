"""Tests for loca.tools.filesystem (ReadFileTool, WriteFileTool, EditFileTool)."""

from __future__ import annotations

from pathlib import Path

import pytest

from loca.tools.base import ToolContext
from loca.tools.filesystem import EditFileTool, ReadFileTool, WriteFileTool
from loca.tools.validation import SchemaValidationError


@pytest.fixture
def tool() -> ReadFileTool:
    return ReadFileTool()


def _write(p: Path, content: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ---- happy path -------------------------------------------------------------


def test_reads_whole_file(tool: ReadFileTool, ctx: ToolContext, workspace: Path) -> None:
    _write(workspace / "hello.txt", "alpha\nbeta\ngamma\n")
    out = tool.execute({"path": "hello.txt"}, ctx)
    assert not out.is_error
    assert "alpha" in out.content
    assert "beta" in out.content
    assert "gamma" in out.content


def test_reads_line_slice(tool: ReadFileTool, ctx: ToolContext, workspace: Path) -> None:
    _write(workspace / "x.txt", "\n".join(f"L{i}" for i in range(10)))
    out = tool.execute({"path": "x.txt", "start_line": 3, "end_line": 6}, ctx)
    assert not out.is_error
    assert "L3" in out.content
    assert "L4" in out.content
    assert "L5" in out.content
    assert "L6" not in out.content
    assert "L2" not in out.content


def test_reads_from_start_line_only(tool: ReadFileTool, ctx: ToolContext, workspace: Path) -> None:
    _write(workspace / "x.txt", "a\nb\nc\nd\n")
    out = tool.execute({"path": "x.txt", "start_line": 2}, ctx)
    # Line numbers are 6-wide: "     2\tc", "     3\td". The earlier
    # "a"/"b" rows are not present.
    assert "     2\tc" in out.content
    assert "     3\td" in out.content
    assert "     0\t" not in out.content
    assert "     1\t" not in out.content


def test_header_reports_total_and_showing(
    tool: ReadFileTool, ctx: ToolContext, workspace: Path
) -> None:
    _write(workspace / "x.txt", "\n".join(f"L{i}" for i in range(5)))
    out = tool.execute({"path": "x.txt", "start_line": 1, "end_line": 3}, ctx)
    assert "total_lines=5" in out.content
    assert "showing=2" in out.content


# ---- line truncation -------------------------------------------------------


def test_long_lines_are_truncated(tool: ReadFileTool, ctx: ToolContext, workspace: Path) -> None:
    long_line = "x" * 10_000
    _write(workspace / "big.txt", long_line + "\n")
    out = tool.execute({"path": "big.txt"}, ctx)
    assert "truncated" in out.content
    # 4000 char cap means the body chunk of "x"s is bounded
    assert "x" * 5000 not in out.content


def test_line_count_is_capped_and_paging_is_explained(
    tool: ReadFileTool, ctx: ToolContext, workspace: Path
) -> None:
    """A 5,000-line file used to come back whole — 290,202 characters of it."""
    _write(workspace / "log.txt", "\n".join(f"L{i}" for i in range(5_000)))
    out = tool.execute({"path": "log.txt"}, ctx)

    assert "total_lines=5000" in out.content
    assert "showing=2000" in out.content
    # A cap the model cannot get past is a dead end; say where to resume.
    assert "re-read with start_line=2000" in out.content
    assert len(out.content) < 40_000

    page = tool.execute({"path": "log.txt", "start_line": 2000}, ctx)
    assert f"{2000:6d}\tL2000" in page.content
    assert f"{0:6d}\tL0" not in page.content


def test_total_bytes_are_capped_even_when_every_line_is_legal(
    tool: ReadFileTool, ctx: ToolContext, workspace: Path
) -> None:
    """The line count alone does not bound the payload — 100 legal long lines don't fit."""
    _write(workspace / "wide.txt", "\n".join("y" * 3_900 for _ in range(100)))
    out = tool.execute({"path": "wide.txt"}, ctx)

    assert "truncated at" in out.content
    assert len(out.content.encode("utf-8")) < 120_000


# ---- error paths -----------------------------------------------------------


def test_missing_file(tool: ReadFileTool, ctx: ToolContext, workspace: Path) -> None:
    out = tool.execute({"path": "nope.txt"}, ctx)
    assert out.is_error
    assert "not found" in out.content.lower()


def test_path_is_a_directory(tool: ReadFileTool, ctx: ToolContext, workspace: Path) -> None:
    (workspace / "subdir").mkdir()
    out = tool.execute({"path": "subdir"}, ctx)
    assert out.is_error
    assert "not a file" in out.content.lower()


def test_end_line_smaller_than_start(tool: ReadFileTool, ctx: ToolContext, workspace: Path) -> None:
    _write(workspace / "x.txt", "a\nb\nc\n")
    out = tool.execute({"path": "x.txt", "start_line": 2, "end_line": 1}, ctx)
    assert out.is_error


def test_non_utf8_file_reports_error(tool: ReadFileTool, ctx: ToolContext, workspace: Path) -> None:
    bad = workspace / "bin.dat"
    bad.write_bytes(b"\xff\xfe\x00bad")
    out = tool.execute({"path": "bin.dat"}, ctx)
    assert out.is_error
    assert "utf-8" in out.content.lower() or "utf" in out.content.lower()


# ---- path sandbox ---------------------------------------------------------


def test_path_outside_workspace_is_rejected(
    tool: ReadFileTool, ctx: ToolContext, workspace: Path
) -> None:
    """Point at a real file outside the workspace.

    The old version used ``Path.home()/".bashrc"`` and skipped when it was
    missing — which is always, on the only platform loca supports. The
    assertion never ran.
    """
    outside = workspace.parent / "outside-the-workspace.txt"
    outside.write_text("secret", encoding="utf-8")
    out = tool.execute({"path": str(outside)}, ctx)
    assert out.is_error
    assert "outside the workspace" in out.content


def test_path_traversal_is_rejected(tool: ReadFileTool, ctx: ToolContext, workspace: Path) -> None:
    # Resolved path tries to escape via ../. The tool's policy should reject it.
    out = tool.execute({"path": "../../../etc/passwd"}, ctx)
    assert out.is_error
    assert "outside the workspace" in out.content


# ---- input validation ------------------------------------------------------


def test_missing_path_argument(tool: ReadFileTool, ctx: ToolContext) -> None:
    with pytest.raises(SchemaValidationError):
        tool.execute({}, ctx)


def test_wrong_type_for_start_line(tool: ReadFileTool, ctx: ToolContext, workspace: Path) -> None:
    _write(workspace / "x.txt", "a\n")
    with pytest.raises(SchemaValidationError):
        tool.execute({"path": "x.txt", "start_line": "zero"}, ctx)


def test_unknown_argument_rejected(tool: ReadFileTool, ctx: ToolContext, workspace: Path) -> None:
    _write(workspace / "x.txt", "a\n")
    with pytest.raises(SchemaValidationError):
        tool.execute({"path": "x.txt", "mystery": 1}, ctx)


# ===========================================================================
# WriteFileTool
# ===========================================================================


@pytest.fixture
def write_tool() -> WriteFileTool:
    return WriteFileTool()


def test_write_creates_new_file(
    write_tool: WriteFileTool, ctx: ToolContext, workspace: Path
) -> None:
    out = write_tool.execute({"path": "new.txt", "content": "hello\n"}, ctx)
    assert not out.is_error
    assert "wrote" in out.content
    assert "new file" in out.content
    assert (workspace / "new.txt").read_text(encoding="utf-8") == "hello\n"


def test_write_overwrites_existing_file(
    write_tool: WriteFileTool, ctx: ToolContext, workspace: Path
) -> None:
    _write(workspace / "x.txt", "old")
    out = write_tool.execute({"path": "x.txt", "content": "new"}, ctx)
    assert not out.is_error
    assert (workspace / "x.txt").read_text(encoding="utf-8") == "new"


def test_write_append_mode(
    write_tool: WriteFileTool, ctx: ToolContext, workspace: Path
) -> None:
    _write(workspace / "x.txt", "first\n")
    out = write_tool.execute(
        {"path": "x.txt", "content": "second\n", "mode": "append"}, ctx
    )
    assert not out.is_error
    assert (workspace / "x.txt").read_text(encoding="utf-8") == "first\nsecond\n"


def test_write_creates_parent_directories(
    write_tool: WriteFileTool, ctx: ToolContext, workspace: Path
) -> None:
    out = write_tool.execute({"path": "a/b/c/deep.txt", "content": "x"}, ctx)
    assert not out.is_error
    assert (workspace / "a" / "b" / "c" / "deep.txt").read_text(encoding="utf-8") == "x"


def test_write_empty_string_is_allowed(
    write_tool: WriteFileTool, ctx: ToolContext, workspace: Path
) -> None:
    out = write_tool.execute({"path": "empty.txt", "content": ""}, ctx)
    assert not out.is_error
    assert (workspace / "empty.txt").read_text(encoding="utf-8") == ""


def test_write_refuses_to_overwrite_directory(
    write_tool: WriteFileTool, ctx: ToolContext, workspace: Path
) -> None:
    (workspace / "subdir").mkdir()
    out = write_tool.execute({"path": "subdir", "content": "x"}, ctx)
    assert out.is_error
    assert "directory" in out.content.lower()


def test_write_rejects_path_outside_workspace(
    write_tool: WriteFileTool, ctx: ToolContext
) -> None:
    out = write_tool.execute(
        {"path": "../../../tmp/evil.txt", "content": "bad"}, ctx
    )
    assert out.is_error
    assert "outside the workspace" in out.content


def test_write_rejects_oversized_content(
    write_tool: WriteFileTool, ctx: ToolContext, workspace: Path
) -> None:
    huge = "x" * (1_000_001)
    out = write_tool.execute({"path": "huge.txt", "content": huge}, ctx)
    assert out.is_error
    assert "cap" in out.content


def test_write_requires_path_and_content(
    write_tool: WriteFileTool, ctx: ToolContext
) -> None:
    with pytest.raises(SchemaValidationError):
        write_tool.execute({"content": "x"}, ctx)
    with pytest.raises(SchemaValidationError):
        write_tool.execute({"path": "x.txt"}, ctx)


def test_write_rejects_invalid_mode(
    write_tool: WriteFileTool, ctx: ToolContext
) -> None:
    with pytest.raises(SchemaValidationError):
        write_tool.execute(
            {"path": "x.txt", "content": "y", "mode": "sideways"}, ctx
        )


# ===========================================================================
# EditFileTool
# ===========================================================================


@pytest.fixture
def edit_tool() -> EditFileTool:
    return EditFileTool()


def test_edit_replaces_unique_match(
    edit_tool: EditFileTool, ctx: ToolContext, workspace: Path
) -> None:
    _write(workspace / "x.txt", "hello world\n")
    out = edit_tool.execute(
        {"path": "x.txt", "find": "world", "replace": "loca"}, ctx
    )
    assert not out.is_error
    assert "Replaced 1 occurrence" in out.content
    assert (workspace / "x.txt").read_text(encoding="utf-8") == "hello loca\n"


def test_edit_ambiguous_match_rejected(
    edit_tool: EditFileTool, ctx: ToolContext, workspace: Path
) -> None:
    _write(workspace / "x.txt", "foo bar foo\n")
    out = edit_tool.execute(
        {"path": "x.txt", "find": "foo", "replace": "baz"}, ctx
    )
    assert out.is_error
    assert "2 times" in out.content


def test_edit_global_replace_replaces_all(
    edit_tool: EditFileTool, ctx: ToolContext, workspace: Path
) -> None:
    _write(workspace / "x.txt", "foo bar foo\n")
    out = edit_tool.execute(
        {
            "path": "x.txt",
            "find": "foo",
            "replace": "baz",
            "global_replace": True,
        },
        ctx,
    )
    assert not out.is_error
    assert "Replaced 2 occurrence" in out.content
    assert (workspace / "x.txt").read_text(encoding="utf-8") == "baz bar baz\n"


def test_edit_no_match_is_error(
    edit_tool: EditFileTool, ctx: ToolContext, workspace: Path
) -> None:
    _write(workspace / "x.txt", "hello\n")
    out = edit_tool.execute(
        {"path": "x.txt", "find": "missing", "replace": "x"}, ctx
    )
    assert out.is_error
    assert "did not match" in out.content


def test_edit_empty_find_rejected(
    edit_tool: EditFileTool, ctx: ToolContext, workspace: Path
) -> None:
    # The schema enforces minLength=1, so the validator rejects an empty
    # find string before execute() is even reached.
    with pytest.raises(SchemaValidationError):
        edit_tool.execute(
            {"path": "x.txt", "find": "", "replace": "x"}, ctx
        )


def test_edit_replace_with_empty_string_deletes(
    edit_tool: EditFileTool, ctx: ToolContext, workspace: Path
) -> None:
    _write(workspace / "x.txt", "abcXXXdef\n")
    out = edit_tool.execute(
        {"path": "x.txt", "find": "XXX", "replace": ""}, ctx
    )
    assert not out.is_error
    assert (workspace / "x.txt").read_text(encoding="utf-8") == "abcdef\n"


def test_edit_file_not_found(
    edit_tool: EditFileTool, ctx: ToolContext, workspace: Path
) -> None:
    out = edit_tool.execute(
        {"path": "missing.txt", "find": "x", "replace": "y"}, ctx
    )
    assert out.is_error
    assert "not found" in out.content.lower()


def test_edit_rejects_path_outside_workspace(
    edit_tool: EditFileTool, ctx: ToolContext
) -> None:
    out = edit_tool.execute(
        {"path": "../../../etc/hosts", "find": "x", "replace": "y"}, ctx
    )
    assert out.is_error
    assert "outside the workspace" in out.content


def test_edit_response_contains_diff_hint(
    edit_tool: EditFileTool, ctx: ToolContext, workspace: Path
) -> None:
    _write(workspace / "x.txt", "alpha\nbeta\ngamma\n")
    out = edit_tool.execute(
        {"path": "x.txt", "find": "beta", "replace": "BETA"}, ctx
    )
    # The diff is rendered via difflib.unified_diff — it should at minimum
    # mention the file path. We don't pin format tightly; just sanity check.
    assert "x.txt" in out.content
    assert "BETA" in out.content


def test_edit_unknown_argument_rejected(
    edit_tool: EditFileTool, ctx: ToolContext, workspace: Path
) -> None:
    _write(workspace / "x.txt", "abc")
    with pytest.raises(SchemaValidationError):
        edit_tool.execute(
            {"path": "x.txt", "find": "a", "replace": "b", "magic": 1}, ctx
        )


def test_edit_keeps_lf_line_endings(
    edit_tool: EditFileTool, ctx: ToolContext, workspace: Path
) -> None:
    """A one-line edit must not rewrite every line ending in the file.

    ``Path.write_text`` defaults to ``newline=None``, which translates every
    ``\\n`` to ``os.linesep``: the edit below used to turn an all-LF file into
    an all-CRLF one, so ``git diff`` showed the whole file.
    """
    target = workspace / "lf.txt"
    target.write_bytes(b"alpha\nbeta\ngamma\n")

    out = edit_tool.execute({"path": "lf.txt", "find": "beta", "replace": "BETA"}, ctx)

    assert not out.is_error
    assert target.read_bytes() == b"alpha\nBETA\ngamma\n"


def test_edit_keeps_crlf_line_endings(
    edit_tool: EditFileTool, ctx: ToolContext, workspace: Path
) -> None:
    """The mirror case: writing with newline="" would have flattened a CRLF file."""
    target = workspace / "crlf.txt"
    target.write_bytes(b"alpha\r\nbeta\r\ngamma\r\n")

    out = edit_tool.execute({"path": "crlf.txt", "find": "beta", "replace": "BETA"}, ctx)

    assert not out.is_error
    assert target.read_bytes() == b"alpha\r\nBETA\r\ngamma\r\n"


def test_edit_matches_lf_find_against_a_crlf_file(
    edit_tool: EditFileTool, ctx: ToolContext, workspace: Path
) -> None:
    """The model sees LF (read_file normalises), so `find` arrives with LF."""
    target = workspace / "crlf.txt"
    target.write_bytes(b"one\r\ntwo\r\nthree\r\n")

    out = edit_tool.execute(
        {"path": "crlf.txt", "find": "one\ntwo", "replace": "one\ntwo\n1.5"}, ctx
    )

    assert not out.is_error
    assert target.read_bytes() == b"one\r\ntwo\r\n1.5\r\nthree\r\n"
