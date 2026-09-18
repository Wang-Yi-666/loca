"""Durable session storage, backed by SQLite.

A *session* is the on-disk form of one agent conversation: the message
transcript, the metadata needed to resume it (workspace, provider, model) and
the checkpoints captured along the way. Persisting it is what turns ``loca
chat`` from "a REPL you can lose by pressing Ctrl-C" into "a task you can come
back to tomorrow".

Design notes
------------

* **The transcript is the source of truth.** The loop hands us a cumulative
  ``list[Message]``; we rewrite the session's rows from it
  (:meth:`SessionStore.save_transcript`) instead of appending deltas. Context
  trimming shrinks that list, so an append-only log would drift away from what
  the model actually saw.
* **SQLite only, no ORM.** Three tables, a handful of indexes, and plain SQL —
  easy to inspect with any client, no migration framework needed for a project
  this size. :data:`SCHEMA_VERSION` is recorded so a future change can branch.
* **Checkpoints are opaque payloads here.** :mod:`loca.observability.checkpoint`
  owns their shape; the store just keeps the JSON blob, which keeps the two
  modules independently testable.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loca.providers.types import Message, Role, ToolCall

#: Bumped when the table layout changes in a way readers must know about.
#:
#: * 1 — sessions, messages, checkpoints, meta
#: * 2 — traces (additive; version 1 databases are upgraded in place by the
#:   ``CREATE TABLE IF NOT EXISTS`` block below, so no migration script exists)
SCHEMA_VERSION = 2

#: Longest auto-derived session title (from the first user message).
TITLE_MAX_CHARS = 72

#: Metadata key holding the session-wide step counter. It must be durable:
#: checkpoint steps are what ``loca rollback`` targets, and checkpoint ids that
#: restarted at 0 on every launch would make rollback ambiguous.
STEP_COUNTER_KEY = "next_step"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    title       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    workspace   TEXT,
    provider    TEXT,
    model       TEXT,
    metadata    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    session_id        TEXT NOT NULL,
    seq               INTEGER NOT NULL,
    role              TEXT NOT NULL,
    content           TEXT,
    tool_calls        TEXT NOT NULL DEFAULT '[]',
    tool_call_id      TEXT,
    reasoning_content TEXT,
    created_at        TEXT NOT NULL,
    PRIMARY KEY (session_id, seq),
    FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS checkpoints (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    step        INTEGER NOT NULL,
    tool        TEXT,
    created_at  TEXT NOT NULL,
    payload     TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_id, seq);
CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON checkpoints (session_id, step);

CREATE TABLE IF NOT EXISTS traces (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    step        INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    payload     TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_traces_session ON traces (session_id, step, id);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def utcnow() -> str:
    """Timestamp used for every row, so ordering is a simple string sort."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def default_db_path() -> Path:
    """Where sessions live unless the caller says otherwise.

    ``$LOCA_DB`` wins so tests and CI can redirect it; otherwise
    ``~/.loca/sessions.db``. One database for all projects — each session
    records its workspace, so sessions stay attributable.
    """
    override = os.environ.get("LOCA_DB")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".loca" / "sessions.db"


def new_session_id() -> str:
    """A short, sortable-ish, collision-free session id."""
    return f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# Message <-> row serialization
# ---------------------------------------------------------------------------


def message_to_dict(message: Message) -> dict[str, Any]:
    """Flatten a :class:`Message` into JSON-safe primitives."""
    return {
        "role": message.role.value,
        "content": message.content,
        "tool_calls": [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in message.tool_calls
        ],
        "tool_call_id": message.tool_call_id,
        "reasoning_content": message.reasoning_content,
    }


def message_from_dict(data: dict[str, Any]) -> Message:
    """Rebuild a :class:`Message` from :func:`message_to_dict` output."""
    return Message(
        role=Role(data["role"]),
        content=data.get("content"),
        tool_calls=[
            ToolCall(id=c["id"], name=c["name"], arguments=c.get("arguments") or {})
            for c in data.get("tool_calls") or []
        ],
        tool_call_id=data.get("tool_call_id"),
        reasoning_content=data.get("reasoning_content"),
    )


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SessionInfo:
    """One row of the ``sessions`` table, plus a message count."""

    session_id: str
    title: str | None
    created_at: str
    updated_at: str
    workspace: str | None = None
    provider: str | None = None
    model: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    message_count: int = 0

    @property
    def display_title(self) -> str:
        return self.title or "(untitled)"

    @property
    def next_step(self) -> int:
        """Session-wide step counter, durable across restarts."""
        try:
            return int(self.metadata.get(STEP_COUNTER_KEY) or 0)
        except (TypeError, ValueError):
            return 0


@dataclass(slots=True)
class CheckpointRow:
    """One stored checkpoint. ``payload`` is owned by the checkpoint module."""

    session_id: str
    step: int
    tool: str | None
    created_at: str
    payload: dict[str, Any]


@dataclass(slots=True)
class TraceRow:
    """One stored step trace. ``payload`` is owned by the trace module."""

    session_id: str
    step: int
    created_at: str
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class SessionStore:
    """SQLite-backed persistence for sessions, transcripts and checkpoints.

    Use it as a context manager, or call :meth:`close` yourself::

        with SessionStore() as store:
            store.create_session(workspace="D:/repo")

    ``path=":memory:"`` gives a throwaway database (handy in tests).
    """

    def __init__(self, path: str | Path | None = None) -> None:
        raw = default_db_path() if path is None else path
        self.path: Path | str = ":memory:" if str(raw) == ":memory:" else Path(raw)
        if self.path != ":memory:":
            assert isinstance(self.path, Path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            # WAL keeps a reader (loca sessions) from blocking the writer (loca chat).
            self._conn.execute("PRAGMA journal_mode = WAL")
            # SQLite's default busy timeout is 0: a second writer fails instantly
            # with "database is locked" instead of waiting. That is fine for the
            # single-threaded CLI, but `loca bench` runs attempts in parallel and
            # each one opens its own connection, so give writers a grace period.
            self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self._conn.commit()

    # ---- lifecycle --------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SessionStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- sessions ---------------------------------------------------------

    def create_session(
        self,
        session_id: str | None = None,
        *,
        title: str | None = None,
        workspace: str | Path | None = None,
        provider: str | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionInfo:
        """Insert a new session. Raises if the id is already taken."""
        sid = session_id or new_session_id()
        now = utcnow()
        try:
            self._conn.execute(
                "INSERT INTO sessions "
                "(session_id, title, created_at, updated_at, workspace, provider, model, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sid,
                    title,
                    now,
                    now,
                    str(workspace) if workspace is not None else None,
                    provider,
                    model,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"session {sid!r} already exists") from exc
        self._conn.commit()
        info = self.get_session(sid)
        assert info is not None  # just inserted
        return info

    def ensure_session(self, session_id: str, **kwargs: Any) -> tuple[SessionInfo, bool]:
        """Return ``(session, created)`` — get the session or create it.

        This is what ``--session`` needs: resuming an old id and starting a
        fresh one are the same call, and the caller only reports which happened.
        """
        existing = self.get_session(session_id)
        if existing is not None:
            return existing, False
        return self.create_session(session_id, **kwargs), True

    def get_session(self, session_id: str) -> SessionInfo | None:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_session(row, message_count=self.message_count(session_id))

    def list_sessions(self, limit: int = 50) -> list[SessionInfo]:
        """Most recently updated first.

        Timestamps only have second resolution, so sessions created in the same
        second would otherwise tie — and the tie was broken by *id*, which put
        ``older`` above ``newer``. ``rowid`` descends in true insertion order,
        so "the most recent session" means what a reader expects.
        """
        rows = self._conn.execute(
            """
            SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.session_id)
                   AS message_count
            FROM sessions s
            ORDER BY s.updated_at DESC, s.rowid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._row_to_session(r, message_count=r["message_count"]) for r in rows]

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and (via ``ON DELETE CASCADE``) its rows."""
        cur = self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def set_title(self, session_id: str, title: str | None) -> bool:
        cur = self._conn.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE session_id = ?",
            (title, utcnow(), session_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def touch(self, session_id: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
            (utcnow(), session_id),
        )
        self._conn.commit()

    def update_metadata(self, session_id: str, **values: Any) -> None:
        """Merge keys into the session's metadata JSON object."""
        current = self.get_session(session_id)
        merged = dict(current.metadata) if current else {}
        merged.update(values)
        self._conn.execute(
            "UPDATE sessions SET metadata = ?, updated_at = ? WHERE session_id = ?",
            (json.dumps(merged, ensure_ascii=False, default=str), utcnow(), session_id),
        )
        self._conn.commit()

    # ---- step counter -----------------------------------------------------

    def next_step(self, session_id: str) -> int:
        """The session's next step number, or 0 for an unknown session.

        Carried in metadata so it keeps counting across process restarts —
        otherwise every launch would re-issue step 0 and a rollback target
        would be ambiguous.
        """
        info = self.get_session(session_id)
        return 0 if info is None else info.next_step

    def set_next_step(self, session_id: str, step: int) -> None:
        self.update_metadata(session_id, **{STEP_COUNTER_KEY: int(step)})

    # ---- messages ---------------------------------------------------------

    def message_count(self, session_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE session_id = ?", (session_id,)
        ).fetchone()
        return int(row["n"])

    def append_message(self, session_id: str, message: Message) -> int:
        """Append one message; returns the sequence number it was stored at."""
        row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), -1) AS last FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        seq = int(row["last"]) + 1
        self._insert_message(session_id, seq, message)
        self._conn.commit()
        return seq

    def replace_messages(self, session_id: str, messages: Sequence[Message]) -> int:
        """Rewrite the whole transcript atomically; returns the message count.

        Used after every turn: the transcript is cumulative and can *shrink*
        (context trimming), so replacing is the honest operation.
        """
        with self._conn:  # transaction: readers never see a half-written turn
            self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            for seq, message in enumerate(messages):
                self._insert_message(session_id, seq, message, commit=False)
            self._conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (utcnow(), session_id),
            )
        return len(messages)

    def load_messages(self, session_id: str) -> list[Message]:
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY seq", (session_id,)
        ).fetchall()
        return [self._row_to_message(r) for r in rows]

    def save_transcript(
        self,
        session_id: str,
        messages: Sequence[Message],
        *,
        derive_title: bool = True,
    ) -> SessionInfo:
        """Persist a full transcript and refresh the session row.

        Derives a readable title from the first user message when the session
        has none yet, so ``loca sessions`` shows something better than a hex id.
        """
        self.replace_messages(session_id, messages)
        if derive_title:
            session = self.get_session(session_id)
            if session is not None and not session.title:
                title = derive_title_from(messages)
                if title:
                    self.set_title(session_id, title)
        info = self.get_session(session_id)
        assert info is not None, f"session {session_id!r} vanished mid-save"
        return info

    # ---- checkpoints ------------------------------------------------------

    def save_checkpoint(
        self,
        session_id: str,
        *,
        step: int,
        tool: str | None,
        payload: dict[str, Any],
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO checkpoints (session_id, step, tool, created_at, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, step, tool, utcnow(), json.dumps(payload, ensure_ascii=False)),
        )
        self._conn.commit()
        return int(cur.lastrowid or 0)

    def list_checkpoints(self, session_id: str) -> list[CheckpointRow]:
        """All checkpoints for a session, oldest step first."""
        rows = self._conn.execute(
            "SELECT * FROM checkpoints WHERE session_id = ? ORDER BY step, id",
            (session_id,),
        ).fetchall()
        return [
            CheckpointRow(
                session_id=r["session_id"],
                step=r["step"],
                tool=r["tool"],
                created_at=r["created_at"],
                payload=json.loads(r["payload"]),
            )
            for r in rows
        ]

    def delete_checkpoints(self, session_id: str) -> int:
        cur = self._conn.execute("DELETE FROM checkpoints WHERE session_id = ?", (session_id,))
        self._conn.commit()
        return cur.rowcount

    # ---- traces -----------------------------------------------------------

    def save_trace(
        self,
        session_id: str,
        *,
        step: int,
        payload: dict[str, Any],
        created_at: str | None = None,
    ) -> int:
        """Append one step trace. Returns its row id."""
        cur = self._conn.execute(
            "INSERT INTO traces (session_id, step, created_at, payload) VALUES (?, ?, ?, ?)",
            (
                session_id,
                step,
                created_at or utcnow(),
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid or 0)

    def list_traces(self, session_id: str) -> list[TraceRow]:
        """All step traces for a session, in the order they were recorded."""
        rows = self._conn.execute(
            "SELECT * FROM traces WHERE session_id = ? ORDER BY step, id", (session_id,)
        ).fetchall()
        return [
            TraceRow(
                session_id=r["session_id"],
                step=r["step"],
                created_at=r["created_at"],
                payload=json.loads(r["payload"]),
            )
            for r in rows
        ]

    def count_traces(self, session_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM traces WHERE session_id = ?", (session_id,)
        ).fetchone()
        return int(row["n"])

    def delete_traces(self, session_id: str) -> int:
        cur = self._conn.execute("DELETE FROM traces WHERE session_id = ?", (session_id,))
        self._conn.commit()
        return cur.rowcount

    # ---- internals --------------------------------------------------------

    def _insert_message(
        self, session_id: str, seq: int, message: Message, *, commit: bool = True
    ) -> None:
        data = message_to_dict(message)
        self._conn.execute(
            "INSERT INTO messages "
            "(session_id, seq, role, content, tool_calls, tool_call_id, "
            " reasoning_content, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                seq,
                data["role"],
                data["content"],
                json.dumps(data["tool_calls"], ensure_ascii=False),
                data["tool_call_id"],
                data["reasoning_content"],
                utcnow(),
            ),
        )
        if commit:
            self._conn.commit()

    def _row_to_message(self, row: sqlite3.Row) -> Message:
        return message_from_dict(
            {
                "role": row["role"],
                "content": row["content"],
                "tool_calls": json.loads(row["tool_calls"]),
                "tool_call_id": row["tool_call_id"],
                "reasoning_content": row["reasoning_content"],
            }
        )

    def _row_to_session(self, row: sqlite3.Row, *, message_count: int = 0) -> SessionInfo:
        return SessionInfo(
            session_id=row["session_id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            workspace=row["workspace"],
            provider=row["provider"],
            model=row["model"],
            metadata=json.loads(row["metadata"] or "{}"),
            message_count=message_count,
        )


def derive_title_from(messages: Sequence[Message]) -> str | None:
    """First user message, first line, trimmed to a sane length."""
    for message in messages:
        if message.role is Role.USER and message.content:
            first_line = message.content.strip().splitlines()[0].strip()
            if not first_line:
                continue
            if len(first_line) > TITLE_MAX_CHARS:
                return first_line[: TITLE_MAX_CHARS - 1] + "…"
            return first_line
    return None


__all__ = [
    "SCHEMA_VERSION",
    "STEP_COUNTER_KEY",
    "TITLE_MAX_CHARS",
    "CheckpointRow",
    "SessionInfo",
    "SessionStore",
    "TraceRow",
    "default_db_path",
    "derive_title_from",
    "message_from_dict",
    "message_to_dict",
    "new_session_id",
    "utcnow",
]
