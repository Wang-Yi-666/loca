"""Filesystem tools: read_file, write_file, edit_file.

All three tools share one path-sandbox policy: an argument is rejected when the
resolved path lands outside the workspace, so a model cannot reach
``~/.ssh/id_rsa`` through *these* tools even if it tries.

Scoped honestly — this is a sandbox on the file tools, not on the project.
:mod:`loca.tools.shell` runs lines through ``cmd.exe`` on purpose and can reach
anything the user can; the two policies are documented separately so that
neither gets mistaken for a whole-program guarantee.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from loca.tools.base import Tool, ToolContext, ToolResult
from loca.tools.validation import validate_arguments


def _detect_newline(raw: bytes) -> str:
    """The line ending this file already uses, for ``open(newline=...)``.

    Returns ``"\\r\\n"`` when CRLF pairs dominate, otherwise ``""`` (write
    ``\\n`` verbatim). Reading normalises every convention to ``\\n``, so
    writing with the default translates *all* of them to ``\\r\\n`` and turns a
    one-line edit into a whole-file diff. A mixed file is normalised to its
    majority ending, which is the most that can be preserved without rewriting
    the file byte-by-byte.
    """
    crlf = raw.count(b"\r\n")
    lone_lf = raw.count(b"\n") - crlf
    return "\r\n" if crlf > lone_lf else ""


def _resolve_within_workspace(path_str: str, workspace: Path) -> Path:
    """Resolve ``path_str`` and ensure it stays inside ``workspace``.

    Rejects absolute paths outside the workspace, parent-traversal tricks
    (``../``), and symlinks that escape the workspace. Raises ``ValueError``
    on any violation so the tool returns an error to the model.
    """
    candidate = Path(path_str)
    if not candidate.is_absolute():
        candidate = (workspace / candidate).resolve()
    else:
        candidate = candidate.resolve()

    workspace_resolved = workspace.resolve()
    try:
        candidate.relative_to(workspace_resolved)
    except ValueError as exc:
        raise ValueError(
            f"Path {path_str!r} is outside the workspace "
            f"({workspace_resolved}). Access denied."
        ) from exc
    return candidate


class ReadFileTool(Tool):
    """Read the contents of a file, optionally slicing by line range."""

    name = "read_file"
    description = (
        "Read the contents of a UTF-8 text file. By default returns the whole "
        "file. Use start_line and end_line (0-indexed, end exclusive) to read "
        "a slice. Lines longer than 4000 chars are truncated with a marker, "
        "and at most 2000 lines / 100000 bytes are returned per call — the "
        "header says how many lines the file really has, so you can page "
        "through a large file. Path must be inside the workspace."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file, relative to workspace or absolute.",
            },
            "start_line": {
                "type": "integer",
                "minimum": 0,
                "description": "First line to read (0-indexed, inclusive).",
            },
            "end_line": {
                "type": "integer",
                "minimum": 0,
                "description": "Last line to read (0-indexed, exclusive).",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    }
    _MAX_LINE_LEN = 4000
    #: Caps on a single response. ``read_file`` had none of these before the
    #: Week-6 audit: a 5,000-line log came back as 290,202 characters and
    #: pushed the rest of the conversation out of the budget. ``shell`` has
    #: carried a three-way cap since Week 2 — this is the same contract.
    _MAX_LINES = 2000
    _MAX_BYTES = 100_000

    def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        validate_arguments(self.input_schema, arguments)
        try:
            path = _resolve_within_workspace(arguments["path"], ctx.workspace)
        except ValueError as exc:
            return ToolResult(content=str(exc), is_error=True)

        start = int(arguments.get("start_line", 0))
        end = arguments.get("end_line")
        if end is not None:
            end = int(end)
            if end < start:
                return ToolResult(
                    content=f"end_line ({end}) is smaller than start_line ({start}).",
                    is_error=True,
                )

        if not path.exists():
            return ToolResult(content=f"File not found: {path}", is_error=True)
        if not path.is_file():
            return ToolResult(content=f"Not a file: {path}", is_error=True)

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            return ToolResult(
                content=f"File is not valid UTF-8: {exc.reason}", is_error=True
            )

        lines = text.splitlines()
        total = len(lines)
        if end is None:
            sliced = lines[start:]
        else:
            sliced = lines[start:end]

        truncated_lines = len(sliced) > self._MAX_LINES
        if truncated_lines:
            sliced = sliced[: self._MAX_LINES]

        rendered: list[str] = []
        for offset, line in enumerate(sliced):
            line_no = start + offset
            if len(line) > self._MAX_LINE_LEN:
                line = line[: self._MAX_LINE_LEN] + f"… <truncated, {len(line)} chars>"
            rendered.append(f"{line_no:6d}\t{line}")

        header = f"<file path={path} total_lines={total} showing={len(rendered)}>"
        body = "\n".join(rendered)

        notes: list[str] = []
        if truncated_lines:
            # Telling the model where to resume is the difference between a
            # usable cap and a dead end.
            notes.append(
                f"… <{total - (start + len(rendered))} more line(s); "
                f"re-read with start_line={start + len(rendered)}>"
            )
        # Backstop for "many lines, each just under the per-line cap", which the
        # line count alone does not bound.
        if len(body.encode("utf-8")) > self._MAX_BYTES:
            body = body.encode("utf-8")[: self._MAX_BYTES].decode("utf-8", errors="ignore")
            notes.append(f"… <output truncated at {self._MAX_BYTES} bytes>")

        parts = [header]
        if body:
            parts.append(body)
        parts.extend(notes)
        return ToolResult(content="\n".join(parts))


class WriteFileTool(Tool):
    """Write text content to a file (overwrite or append)."""

    name = "write_file"
    description = (
        "Write UTF-8 text content to a file. By default overwrites the file. "
        "Set mode='append' to append. Parent directories are created "
        "automatically. Path must be inside the workspace."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file, relative to workspace or absolute.",
            },
            "content": {
                "type": "string",
                "description": "Text content to write. May be empty.",
            },
            "mode": {
                "type": "string",
                "enum": ["overwrite", "append"],
                "description": "overwrite (default) replaces, append adds to end.",
            },
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }
    _MAX_WRITE_BYTES = 1_000_000  # 1 MB hard cap per write

    def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        validate_arguments(self.input_schema, arguments)
        try:
            path = _resolve_within_workspace(arguments["path"], ctx.workspace)
        except ValueError as exc:
            return ToolResult(content=str(exc), is_error=True)

        content = arguments["content"]
        mode = arguments.get("mode", "overwrite")
        encoded = content.encode("utf-8")
        if len(encoded) > self._MAX_WRITE_BYTES:
            return ToolResult(
                content=(
                    f"Refusing to write {len(encoded)} bytes — exceeds the "
                    f"{self._MAX_WRITE_BYTES} byte cap."
                ),
                is_error=True,
            )

        if path.exists() and path.is_dir():
            return ToolResult(content=f"Path is a directory: {path}", is_error=True)

        existed_before = path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)

        if mode == "append":
            with path.open("a", encoding="utf-8", newline="") as f:
                f.write(content)
        else:
            with path.open("w", encoding="utf-8", newline="") as f:
                f.write(content)

        verb = "appended to" if mode == "append" else "wrote"
        note = " (new file)" if mode == "overwrite" and not existed_before else ""
        return ToolResult(
            content=f"Successfully {verb} {len(encoded)} bytes to {path}{note}"
        )


class EditFileTool(Tool):
    """Replace exact substrings inside a file."""

    name = "edit_file"
    description = (
        "Replace an exact substring inside a file. By default ``find`` must "
        "match exactly once. Set global_replace=true to allow multiple "
        "matches (all will be replaced). ``find`` must be non-empty. Returns "
        "the number of replacements made plus a short unified diff."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file, relative to workspace or absolute.",
            },
            "find": {
                "type": "string",
                "minLength": 1,
                "description": "Exact substring to search for. Must be non-empty.",
            },
            "replace": {
                "type": "string",
                "description": "Replacement text. May be empty (acts as deletion).",
            },
            "global_replace": {
                "type": "boolean",
                "description": "If true, replace every occurrence. Default false.",
            },
        },
        "required": ["path", "find", "replace"],
        "additionalProperties": False,
    }
    _MAX_DIFF_LINES = 60

    def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        validate_arguments(self.input_schema, arguments)
        try:
            path = _resolve_within_workspace(arguments["path"], ctx.workspace)
        except ValueError as exc:
            return ToolResult(content=str(exc), is_error=True)

        find = arguments["find"]
        replace = arguments["replace"]
        global_replace = bool(arguments.get("global_replace", False))

        if not find:
            return ToolResult(content="'find' must be non-empty.", is_error=True)

        if not path.exists():
            return ToolResult(content=f"File not found: {path}", is_error=True)
        if not path.is_file():
            return ToolResult(content=f"Not a file: {path}", is_error=True)

        try:
            raw = path.read_bytes()
        except OSError as exc:
            return ToolResult(content=f"Could not read {path}: {exc}", is_error=True)
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            return ToolResult(
                content=f"File is not valid UTF-8: {exc.reason}", is_error=True
            )
        newline = _detect_newline(raw)
        # Match against the text the model actually saw. ``read_file`` reads
        # with universal newlines, so a CRLF file reaches the model as LF and
        # the ``find`` string copied back out of it is LF as well.
        original = decoded.replace("\r\n", "\n").replace("\r", "\n")

        count = original.count(find)
        if count == 0:
            return ToolResult(
                content=(
                    f"'find' string did not match anywhere in {path}. "
                    "Read the file first and copy the exact text."
                ),
                is_error=True,
            )
        if not global_replace and count > 1:
            return ToolResult(
                content=(
                    f"'find' matches {count} times in {path}. Either narrow "
                    "the search so it matches exactly once, or pass "
                    "global_replace=true to replace all of them."
                ),
                is_error=True,
            )

        updated = (
            original.replace(find, replace)
            if global_replace
            else original.replace(find, replace, 1)
        )
        # Write back in the file's own convention. Writing with the default
        # translates every "\n" to "\r\n" — a one-line edit becomes a whole-file
        # diff and the reported diff stops matching what landed on disk.
        with path.open("w", encoding="utf-8", newline=newline) as handle:
            handle.write(updated)

        diff = self._make_diff(original, updated, path, path)
        return ToolResult(
            content=(
                f"Replaced {count} occurrence(s) in {path}.\n"
                f"--- before: {len(original)} chars / after: {len(updated)} chars ---\n"
                f"{diff}"
            )
        )

    def _make_diff(self, before: str, after: str, old_path: Path, new_path: Path) -> str:
        before_lines = before.splitlines(keepends=True)
        after_lines = after.splitlines(keepends=True)
        diff_lines = list(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=str(old_path),
                tofile=str(new_path),
                n=2,
            )
        )
        if len(diff_lines) > self._MAX_DIFF_LINES:
            shown = "".join(diff_lines[: self._MAX_DIFF_LINES])
            hidden = len(diff_lines) - self._MAX_DIFF_LINES
            return shown + f"\n… <{hidden} more diff lines truncated>"
        return "".join(diff_lines)
