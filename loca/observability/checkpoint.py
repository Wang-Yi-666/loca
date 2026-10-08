"""File checkpoints: snapshot before a tool edits, restore on demand.

The model is allowed to rewrite your files. That is the point of a coding
agent — and exactly why you want an undo button. Before a file-mutating tool
runs, we copy the *current* content of every path it is about to touch into the
session database; :meth:`CheckpointManager.rollback` writes them back.

Semantics worth stating plainly
-------------------------------

* A checkpoint always holds the state **before** step ``N`` ran. Rolling back
  *to* ``N`` therefore undoes ``N`` **and everything after it** — which is what
  "go back to step N" means to a human.
* Checkpoints in the range are applied newest-first, so the oldest one wins and
  the file ends up exactly as it was before the earliest undone step. Applying
  only the target step would leave the later steps' edits in place.
* A file that did not exist before the step gets **deleted** on rollback, not
  blanked — restoring "absent" is not the same as restoring "empty".
* Only the file tools (``write_file``, ``edit_file``) are tracked. ``shell`` can
  touch anything and snapshotting the whole workspace on every command would be
  absurd, so shell-made changes are *not* restorable. :meth:`rollback` says so
  in its report rather than pretending otherwise.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loca.observability.storage import CheckpointRow, SessionStore, utcnow

_log = logging.getLogger("loca.checkpoint")

#: Files bigger than this are recorded (so the report can name them) but not
#: stored — a 500 MB artifact has no business sitting in a session database.
DEFAULT_MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024

#: Tools we can undo, and the argument that names the path they write to.
DEFAULT_TRACKED_TOOLS: Mapping[str, Sequence[str]] = {
    "write_file": ("path",),
    "edit_file": ("path",),
}

#: Snapshot encodings.
TEXT = "utf-8"
BINARY = "base64"
ABSENT = "absent"
UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class FileSnapshot:
    """The pre-step state of one file.

    ``path`` is always workspace-relative with POSIX separators, so a session
    database stays portable across machines and drives.
    """

    path: str
    existed: bool
    size: int = 0
    encoding: str = ABSENT
    data: str | None = None

    @property
    def restorable(self) -> bool:
        """Can this snapshot actually be written back?"""
        if not self.existed:
            return True  # restore == delete
        return self.data is not None

    def restore_bytes(self) -> bytes | None:
        """The literal bytes to write, or ``None`` when not restorable."""
        if self.data is None:
            return None
        if self.encoding == TEXT:
            return self.data.encode("utf-8")
        if self.encoding == BINARY:
            return base64.b64decode(self.data)
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "existed": self.existed,
            "size": self.size,
            "encoding": self.encoding,
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FileSnapshot:
        return cls(
            path=data["path"],
            existed=bool(data.get("existed")),
            size=int(data.get("size") or 0),
            encoding=data.get("encoding") or ABSENT,
            data=data.get("data"),
        )

    def describe(self) -> str:
        if not self.existed:
            return f"{self.path} (created)"
        if not self.restorable:
            return f"{self.path} ({self.size} B, too large to snapshot)"
        return f"{self.path} ({self.size} B)"


@dataclass(slots=True)
class Checkpoint:
    """One checkpoint row: what the workspace looked like before ``step``."""

    session_id: str
    step: int
    tool: str | None
    workspace: str
    created_at: str
    snapshots: list[FileSnapshot] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "step": self.step,
            "tool": self.tool,
            "workspace": self.workspace,
            "created_at": self.created_at,
            "snapshots": [s.to_dict() for s in self.snapshots],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Checkpoint:
        return cls(
            session_id=data["session_id"],
            step=int(data["step"]),
            tool=data.get("tool"),
            workspace=data.get("workspace") or "",
            created_at=data.get("created_at") or "",
            snapshots=[FileSnapshot.from_dict(s) for s in data.get("snapshots") or []],
        )


@dataclass(slots=True)
class RollbackReport:
    """What a rollback actually did — reported, never guessed at."""

    session_id: str
    step: int
    applied_checkpoints: int
    restored: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    #: ``(path, reason)`` per skip. Kept as pairs rather than pre-rendered
    #: strings so callers never have to parse a path back out of a message —
    #: file names are allowed to contain ``" ("``.
    skips: list[tuple[str, str]] = field(default_factory=list)
    #: ``(action, path)`` in the order applied. Several checkpoints can touch
    #: the same file (edit it twice → undo both), so callers should report
    #: :meth:`settled` rather than the raw lists.
    actions: list[tuple[str, str]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.restored or self.deleted)

    @property
    def skipped(self) -> list[str]:
        """Skipped files, rendered as ``"path (reason)"`` for humans."""
        return [f"{path} ({reason})" for path, reason in self.skips]

    def settled(self) -> dict[str, str]:
        """Final action per file: ``restored``, ``deleted`` or ``skipped``.

        Built from :attr:`actions`, whose paths are the raw workspace-relative
        ones. :attr:`skipped` renders the same paths with a reason attached, so
        it must not be used as the key source.
        """
        final: dict[str, str] = {}
        for action, path in self.actions:
            final[path] = action
        return final


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class CheckpointManager:
    """Capture pre-edit snapshots and roll them back.

    Parameters
    ----------
    store:
        Where snapshots are persisted.
    tracked:
        ``{tool_name: (argument_name, ...)}`` — which tools touch files, and
        which of their arguments name the paths. Override to teach the manager
        about a new tool without touching this module.
    max_snapshot_bytes:
        Larger files are recorded by name only.
    """

    def __init__(
        self,
        store: SessionStore,
        *,
        tracked: Mapping[str, Sequence[str]] | None = None,
        max_snapshot_bytes: int = DEFAULT_MAX_SNAPSHOT_BYTES,
    ) -> None:
        self.store = store
        self.tracked: dict[str, tuple[str, ...]] = {
            name: tuple(keys) for name, keys in (tracked or DEFAULT_TRACKED_TOOLS).items()
        }
        self.max_snapshot_bytes = max_snapshot_bytes

    # ---- capture ----------------------------------------------------------

    def paths_for(self, tool: str, arguments: Mapping[str, Any]) -> list[str]:
        """The workspace-relative paths this call will touch (may be empty)."""
        keys = self.tracked.get(tool)
        if not keys:
            return []
        found: list[str] = []
        for key in keys:
            value = arguments.get(key)
            if isinstance(value, str) and value.strip():
                found.append(value)
        return found

    def capture(
        self,
        *,
        session_id: str,
        step: int,
        tool: str,
        arguments: Mapping[str, Any],
        workspace: Path | str,
    ) -> Checkpoint | None:
        """Snapshot the tool's targets *before* it runs.

        Returns ``None`` when there is nothing to snapshot (the tool is not
        tracked, or every path it named is unusable/outside the workspace).

        Never raises. Checkpointing is an observer: a store that is locked,
        full or mid-repair must not turn "no snapshot could be taken" into "the
        agent stopped working". Failures are logged and degrade to ``None``.
        """
        raw_paths = self.paths_for(tool, arguments)
        if not raw_paths:
            return None

        root = Path(workspace)
        snapshots: list[FileSnapshot] = []
        for raw in raw_paths:
            target = resolve_within_workspace(root, raw)
            if target is None:
                # Outside the sandbox: the tool will refuse it anyway, and we
                # must not read files beyond the workspace on a model's say-so.
                _log.debug("checkpoint skipped out-of-workspace path %r", raw)
                continue
            snapshots.append(self._snapshot(root, target))
        if not snapshots:
            return None

        checkpoint = Checkpoint(
            session_id=session_id,
            step=step,
            tool=tool,
            workspace=str(root),
            created_at=utcnow(),
            snapshots=snapshots,
        )
        try:
            self.store.save_checkpoint(
                session_id, step=step, tool=tool, payload=checkpoint.to_dict()
            )
        except Exception as exc:  # noqa: BLE001 - see the docstring
            _log.warning("could not persist checkpoint for %s: %s", tool, exc)
            return None
        return checkpoint

    def _snapshot(self, root: Path, target: Path) -> FileSnapshot:
        rel = _relative(root, target)
        try:
            if not target.is_file():
                return FileSnapshot(path=rel, existed=False, encoding=ABSENT)
            size = target.stat().st_size
        except OSError as exc:  # pragma: no cover - unreadable path
            _log.warning("cannot stat %s for checkpoint: %s", target, exc)
            return FileSnapshot(path=rel, existed=True, encoding=UNAVAILABLE)

        if size > self.max_snapshot_bytes:
            _log.warning(
                "not snapshotting %s: %d bytes exceeds the %d-byte limit",
                rel,
                size,
                self.max_snapshot_bytes,
            )
            return FileSnapshot(path=rel, existed=True, size=size, encoding=UNAVAILABLE)

        try:
            raw = target.read_bytes()
        except OSError as exc:
            # ``stat()`` and ``read_bytes()`` are two syscalls: the file can be
            # deleted or lose its permissions in between. A checkpoint is an
            # observer — it must never be the thing that aborts a run, so a
            # failed read degrades to "recorded but not restorable".
            _log.warning("cannot read %s for checkpoint: %s", rel, exc)
            return FileSnapshot(path=rel, existed=True, size=size, encoding=UNAVAILABLE)
        try:
            return FileSnapshot(
                path=rel,
                existed=True,
                size=size,
                encoding=TEXT,
                data=raw.decode("utf-8"),
            )
        except UnicodeDecodeError:
            return FileSnapshot(
                path=rel,
                existed=True,
                size=size,
                encoding=BINARY,
                data=base64.b64encode(raw).decode("ascii"),
            )

    # ---- rollback ---------------------------------------------------------

    def rollback(
        self,
        session_id: str,
        step: int,
        *,
        workspace: Path | str | None = None,
    ) -> RollbackReport:
        """Undo every checkpoint at ``step`` and later.

        Newest checkpoint first, so the earliest undone step's pre-state is the
        one that survives — the file ends up as it was before ``step`` ran.

        The ordering key is ``(step, id)``, not ``step`` alone. Several
        checkpoints legitimately share a step: one model reply can call
        ``write_file`` twice on the same path (the loop captures each call with
        the same ``global_step``), and a crash mid-turn makes the restart reuse
        the step. Sorting on ``step`` alone leaves those in insertion order —
        oldest first — which applies the *oldest* pre-state first and lets the
        newest one win, the exact opposite of the documented semantics.
        """
        rows: list[CheckpointRow] = [
            r for r in self.store.list_checkpoints(session_id) if r.step >= step
        ]
        rows.sort(key=lambda r: (r.step, r.id), reverse=True)

        report = RollbackReport(
            session_id=session_id, step=step, applied_checkpoints=len(rows)
        )
        if not rows:
            return report

        session = self.store.get_session(session_id)
        default_workspace = (
            str(workspace) if workspace is not None else (session.workspace if session else None)
        )

        for row in rows:
            checkpoint = Checkpoint.from_dict(row.payload)
            root_value = str(workspace) if workspace is not None else checkpoint.workspace
            if not root_value:
                root_value = default_workspace
            root = Path(root_value).expanduser() if root_value else None
            for snapshot in checkpoint.snapshots:
                self._restore(root, snapshot, report)
        return report

    def _restore(
        self, root: Path | None, snapshot: FileSnapshot, report: RollbackReport
    ) -> None:
        if root is None:
            report.skips.append((snapshot.path, "no workspace recorded"))
            report.actions.append(("skipped", snapshot.path))
            return
        target = resolve_within_workspace(root, snapshot.path)
        if target is None:
            report.skips.append((snapshot.path, "outside workspace"))
            report.actions.append(("skipped", snapshot.path))
            return

        if not snapshot.existed:
            try:
                if target.exists():
                    target.unlink()
                    report.deleted.append(snapshot.path)
                    report.actions.append(("deleted", snapshot.path))
            except OSError as exc:  # pragma: no cover - permission or lock
                report.skips.append((snapshot.path, str(exc)))
                report.actions.append(("skipped", snapshot.path))
            return

        payload = snapshot.restore_bytes()
        if payload is None:
            report.skips.append((snapshot.path, "not captured"))
            report.actions.append(("skipped", snapshot.path))
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            report.restored.append(snapshot.path)
            report.actions.append(("restored", snapshot.path))
        except OSError as exc:  # pragma: no cover - permission or lock
            report.skips.append((snapshot.path, str(exc)))
            report.actions.append(("skipped", snapshot.path))


# ---------------------------------------------------------------------------
# path helpers
# ---------------------------------------------------------------------------


def resolve_within_workspace(workspace: Path, raw: str) -> Path | None:
    """Resolve ``raw`` against ``workspace``, or ``None`` if it escapes it.

    Same sandbox contract as the filesystem tools: an agent's arguments must
    never let the harness read or write outside the directory it was pointed at.
    """
    try:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = workspace / candidate
        resolved = candidate.resolve()
        root = workspace.resolve()
    except (OSError, ValueError):  # pragma: no cover - malformed path
        return None
    if resolved == root or root in resolved.parents:
        return resolved
    return None


def _relative(root: Path, target: Path) -> str:
    """Workspace-relative POSIX path, with an absolute fallback."""
    try:
        return target.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:  # pragma: no cover - guarded by resolve_within_workspace
        return target.as_posix()


__all__ = [
    "ABSENT",
    "BINARY",
    "DEFAULT_MAX_SNAPSHOT_BYTES",
    "DEFAULT_TRACKED_TOOLS",
    "TEXT",
    "UNAVAILABLE",
    "Checkpoint",
    "CheckpointManager",
    "FileSnapshot",
    "RollbackReport",
    "resolve_within_workspace",
]
