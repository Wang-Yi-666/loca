"""Workspace resolution.

The workspace is the directory every tool is confined to: the filesystem tools
refuse to resolve a path outside it, ``shell`` refuses a ``cwd`` outside it, and
checkpoint paths are stored relative to it. Both front ends — the CLI and the
web API — therefore have to turn operator input into one absolute path *before*
a session starts.

The rule lives here rather than in ``cli.py`` so the two callers cannot drift:
the web UI is a second consumer of the same contract, not a copy of it.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["resolve_workspace"]

#: ``/d/repo`` or ``/c`` — a Git-Bash/MSYS-style path, never valid on Windows.
_MSYS_PATH = re.compile(r"^/([A-Za-z])(?:/|$)")


def resolve_workspace(raw: str) -> Path:
    """Turn an operator-supplied workspace into an absolute Windows path.

    loca is Windows-only, so the value must be a Windows path
    (``D:\\Projects\\repo``). A Git-Bash path like ``/d/repo`` is worse than
    obviously wrong: ``ntpath`` reads it as *drive-relative*, so it silently
    resolves to ``D:\\d\\repo`` — an empty directory. The model would then work
    in a phantom workspace while the operator stares at an untouched repo. We
    reject the shape instead of guessing.

    Only that one shape raises ``ValueError``. Whether the directory must
    already exist is deliberately left to the caller: the CLI creates it (the
    operator typed an explicit path), the web API insists it exists (a typo in
    a text box should not silently produce an empty tree to work in).
    """
    match = _MSYS_PATH.match(raw)
    if match:
        drive = match.group(1).upper()
        tail = raw[3:].replace("/", "\\")
        suggestion = f"{drive}:\\{tail}" if tail else f"{drive}:\\"
        raise ValueError(
            f"workspace {raw!r} looks like a Git-Bash path. loca is "
            f"Windows-only — pass a Windows path instead, e.g. {suggestion}"
        )
    return Path(raw).expanduser().resolve()
