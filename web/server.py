"""FastAPI server that exposes the loca agent as a streaming chat API.

The HTML page lives at ``GET /`` and POSTs to ``/api/chat`` which returns an
SSE stream. Each event is one of:

- ``{"type": "session", "id": "..."}``              always first: which session this is
- ``{"type": "text", "content": "..."}``            streaming text
- ``{"type": "tool_call", "name": "...", "args": {...}}``
- ``{"type": "tool_result", "name": "...", "content": "...", "is_error": bool}``
- ``{"type": "checkpoint", "step": N, "tool": "...", "files": [...], "restorable": bool}``
- ``{"type": "usage", "prompt": N, "completion": N, "total": N}``
- ``{"type": "context_trimmed", "dropped": N, "estimated_tokens": N, "budget": N}``
- ``{"type": "context_summarized", "summarized": N, "summary_tokens": N,
  "estimated_tokens": N, "budget": N}``
- ``{"type": "recovery", "reason": "length", "step": N}``
- ``{"type": "done", "reason": "stop|max_steps", "steps": N, "total_tokens": N}``
- ``{"type": "error", "message": "...", "retryable": bool}``

The workspace every turn runs in defaults to the project root and can be
overridden per request with the ``workspace`` field of the chat body — see
:func:`_workspace_for` for the validation rules.

Every turn also belongs to a *session*: the same SQLite database the CLI writes
to, holding the transcript and the pre-edit file snapshots. That is what makes
the undo button work — ``POST /api/rollback`` replays those snapshots. A client
that does not send a ``session_id`` gets a fresh one, announced as the first
event of the stream; echoing it back keeps the turn in the same session.

Run::

    .venv/Scripts/python.exe -m uvicorn web.server:app --reload --port 8765

Then open http://localhost:8765 in a browser.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import AsyncIterator
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from loca.agents import CODING_AGENT, build_agent
from loca.core.events import AgentEvent, EventType
from loca.core.loop import AgentLoop
from loca.observability import (
    CheckpointManager,
    SessionStore,
    default_db_path,
    new_session_id,
)
from loca.providers import LLMProvider
from loca.providers.registry import get_provider
from loca.tools import register_default_tools
from loca.tools.base import ToolContext
from loca.workspace import resolve_workspace

_log = logging.getLogger("loca.web")

# Load .env so the API key is available without manual setup.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Register the four built-in tools once at import time.
register_default_tools()

# Fallback workspace used when a request does not name one: the project root.
# Any request may override it — see :func:`_workspace_for`.
DEFAULT_WORKSPACE = Path(__file__).resolve().parent.parent

#: Shape of an id this server hands out (see ``new_session_id``). A client is
#: allowed to send one back, not to invent a novel one: the id is a primary key
#: in the session database, and a blank or malformed value used to mean "start a
#: new session" silently.
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{3,63}$")

app = FastAPI(title="loca agent", version="0.1.0")


def open_store() -> SessionStore:
    """Open the session database for one request.

    A fresh connection per request rather than a module-level singleton, for a
    concrete reason: sqlite3 connections are bound to the thread that created
    them, and an ASGI server is free to run each request on a different thread
    (Starlette's ``TestClient`` does exactly that). Sharing one connection
    across requests worked by luck until the tooling changed the thread.

    The file is the one the CLI uses — ``$LOCA_DB`` or ``~/.loca/sessions.db`` —
    so a turn typed in the browser shows up in ``loca sessions`` and can be
    undone from a terminal with ``loca rollback <id> <step>``. WAL mode plus a
    busy timeout (both set by :class:`~loca.observability.SessionStore`) make
    concurrent opens cheap and safe, and the caller closes it when the turn ends.
    """
    return SessionStore(default_db_path())



# ---- request/response models -----------------------------------------------


class ChatTurn(BaseModel):
    """A single user turn, plus the session settings it runs under."""

    message: str
    history: list[dict] | None = None  # [{"role": "user|assistant|tool", "content": "..."}]
    #: Absolute Windows path the tools operate in. ``None`` (or blank) falls
    #: back to :data:`DEFAULT_WORKSPACE`. The directory must already exist —
    #: see :func:`_workspace_for` for why the web API is stricter than the CLI.
    workspace: str | None = None
    #: Which session this turn continues. ``None`` (or blank) starts a new one,
    #: whose id comes back as the first event of the stream; the client sends it
    #: on every later turn so the transcript and the undo history stay together.
    session_id: str | None = None


class RollbackRequest(BaseModel):
    """Body of ``POST /api/rollback``."""

    session_id: str
    #: Undo this step *and every step after it* — the same semantics as
    #: ``loca rollback <session> <step>``.
    step: int


# ---- routes -----------------------------------------------------------------


@app.get("/")
async def index() -> FileResponse:
    """Serve the single-page chat UI."""
    return FileResponse(Path(__file__).parent / "index.html")


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "default_workspace": str(DEFAULT_WORKSPACE),
        "providers_with_keys": [
            name
            for name in ("deepseek", "openai", "anthropic")
            if os.environ.get(f"LOCA_{name.upper()}_API_KEY")
        ],
    }


@app.post("/api/chat")
async def chat(turn: ChatTurn) -> EventSourceResponse:
    """Stream one agent turn as Server-Sent Events."""

    async def event_source() -> AsyncIterator[dict]:
        # Resolve the workspace first: it is the one input the caller just
        # typed, so a bad path is the most useful thing to report back.
        try:
            workspace = _workspace_for(turn.workspace)
            session_id = _session_id_for(turn.session_id)
        except ValueError as exc:
            yield {"event": "message", "data": _json({"type": "error", "message": str(exc)})}
            return

        # Announce the session before anything else. A client that has no id yet
        # (first turn, curl, a reloaded page) learns here which session its
        # checkpoints will land in — and therefore what to echo back, and what
        # to hand to ``loca rollback`` later.
        yield {"event": "message", "data": _json({"type": "session", "id": session_id})}

        # Resolve provider lazily so missing keys surface as a friendly error
        # event instead of crashing the worker.
        try:
            provider: LLMProvider = get_provider()
        except Exception as exc:
            yield {"event": "message", "data": _json({"type": "error", "message": str(exc)})}
            return

        store = open_store()
        store.ensure_session(session_id, workspace=workspace, provider=provider.name)

        # Build through loca.agents, like the CLI and the benchmark do. This is
        # the line that was missing twice: without it the loop runs without a
        # CheckpointManager (no CHECKPOINT event, so the undo button has nothing
        # to attach to) and without a ContextManager (so a long browser
        # conversation dropped its oldest turns instead of summarizing them).
        runtime = build_agent(
            CODING_AGENT,
            provider=provider,
            workspace=workspace,
            session_id=session_id,
            store=store,
        )
        loop, ctx = runtime.loop, runtime.ctx

        # Convert history from JSON into Message objects.
        from loca.providers.types import Message, Role

        history: list[Message] = []
        for item in turn.history or []:
            history.append(
                Message(
                    role=Role(item["role"]),
                    content=item.get("content"),
                )
            )

        try:
            for event in loop.run(ctx, user_message=turn.message, history=history):
                payload = _serialize_event(event)
                if payload is not None:
                    yield {"event": "message", "data": _json(payload)}
        except Exception as exc:  # pragma: no cover - defensive
            yield {
                "event": "message",
                "data": _json({"type": "error", "message": f"{type(exc).__name__}: {exc}"}),
            }
        finally:
            _persist(store, session_id, ctx, loop)
            store.close()

    return EventSourceResponse(event_source())


@app.post("/api/rollback")
async def rollback(request: RollbackRequest) -> dict:
    """Undo every file edit from ``step`` on, reporting what actually changed.

    No ``workspace`` is handed to the manager, on purpose. Each checkpoint
    records the directory it was captured in and restores its files there; using
    the caller's *current* workspace instead would pour the old contents into
    whatever directory the browser happens to point at now — and the workspace
    is switchable per request, so that is a real possibility, not a theoretical
    one.

    Returns ``{"ok": false, "message": ...}`` rather than raising: the browser
    shows the message verbatim, and a refused rollback is information, not a
    server fault.
    """
    try:
        session_id = _validate_session_id(request.session_id)
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}

    store = open_store()
    try:
        if store.get_session(session_id) is None:
            return {"ok": False, "message": f"unknown session: {session_id}"}

        report = CheckpointManager(store).rollback(session_id, request.step)
        if report.applied_checkpoints == 0:
            return {
                "ok": False,
                "message": (
                    f"nothing to undo: no checkpoints at step {request.step} or later "
                    f"in {session_id}"
                ),
            }

        return {
            "ok": True,
            "step": report.step,
            "applied": report.applied_checkpoints,
            "changed": report.changed,
            # One entry per file, in the order applied, with the *final* action —
            # a file edited twice would otherwise be reported twice with opposing
            # outcomes. The paths are workspace-relative, so a session that has
            # been pointed at two workspaces collapses equal names; ``applied``
            # still counts every checkpoint that was replayed.
            "files": [
                {"path": path, "action": action}
                for path, action in report.settled().items()
            ],
            "skipped": report.skipped,
        }
    finally:
        store.close()


def _persist(store: SessionStore, session_id: str, ctx: ToolContext, loop: AgentLoop) -> None:
    """Write the turn's step counter and transcript back to the session database.

    The counter is what keeps rollback unambiguous across turns *and* across a
    server restart; the transcript is what lets ``loca sessions show <id>``
    explain what the checkpoints belong to.
    """
    try:
        store.set_next_step(session_id, ctx.step_index)
        if loop.last_transcript:
            store.save_transcript(session_id, loop.last_transcript)
    except Exception as exc:  # noqa: BLE001 - see comment
        # The answer has already streamed. Turning a locked database into an
        # error event at this point would report the turn as failed when it
        # succeeded, so log it and let the stream end normally: checkpoints are
        # committed as they are taken, so the cost is the transcript, not undo.
        _log.warning("could not persist session %s: %s", session_id, exc)


def _session_id_for(raw: str | None) -> str:
    """The session a chat turn continues, minting a fresh id when absent."""
    if raw is None or not raw.strip():
        return new_session_id()
    return _validate_session_id(raw)


def _validate_session_id(raw: str | None) -> str:
    """Check an id the client sent back against the shape we hand out.

    Raises ``ValueError`` with a message the browser can show verbatim.
    """
    value = (raw or "").strip()
    if not _SESSION_ID_RE.match(value):
        raise ValueError(f"not a loca session id: {raw!r}")
    return value


def _workspace_for(raw: str | None) -> Path:
    """Pick the workspace this request runs in.

    The CLI *creates* a missing ``--workspace`` because an operator typed an
    explicit path on a command line. The web API refuses instead: a typo in a
    text box would otherwise silently create an empty directory and then run the
    agent inside it — the same "succeeds, but in the wrong place" failure that
    :func:`~loca.workspace.resolve_workspace` rejects for Git-Bash paths. An
    unknown path is far likelier here than a deliberately new one, so we ask
    rather than guess.

    Raises ``ValueError`` with a message the browser can show verbatim.
    """
    if raw is None or not raw.strip():
        return DEFAULT_WORKSPACE
    path = resolve_workspace(raw.strip())
    if not path.exists():
        raise ValueError(f"workspace does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"workspace is not a directory: {path}")
    return path


def _serialize_event(event: AgentEvent) -> dict | None:
    """Map a loop event onto the payload shape the browser expects.

    Returns ``None`` for events the UI has nothing to render (``step_start``).
    Kept out of the async generator so it can be unit-tested on its own.
    """
    data = event.data
    kind = event.type

    if kind is EventType.TEXT_DELTA:
        if not data["content"] and data.get("reasoning"):
            return {"type": "reasoning", "content": data["reasoning"]}
        return {"type": "text", "content": data["content"]}
    if kind is EventType.TOOL_CALL:
        return {"type": "tool_call", "name": data["name"], "args": data["arguments"]}
    if kind is EventType.TOOL_RESULT:
        return {
            "type": "tool_result",
            "name": data["name"],
            "content": data["content"],
            "is_error": data["is_error"],
        }
    if kind is EventType.CHECKPOINT:
        return {
            "type": "checkpoint",
            "step": data["step"],
            "tool": data["tool"],
            "files": data["files"],
            "restorable": data.get("restorable", True),
        }
    if kind is EventType.USAGE:
        return {
            "type": "usage",
            "prompt": data["prompt_tokens"],
            "completion": data["completion_tokens"],
            "total": data["total_tokens"],
        }
    if kind is EventType.CONTEXT_TRIMMED:
        return {
            "type": "context_trimmed",
            "dropped": data["dropped"],
            "estimated_tokens": data["estimated_tokens"],
            "budget": data["budget"],
        }
    if kind is EventType.CONTEXT_SUMMARIZED:
        return {
            "type": "context_summarized",
            "summarized": data["summarized"],
            "summary_tokens": data["summary_tokens"],
            "estimated_tokens": data["estimated_tokens"],
            "budget": data["budget"],
        }
    if kind is EventType.RECOVERY:
        return {
            "type": "recovery",
            "reason": data["reason"],
            "detail": data.get("detail", ""),
            "step": data["step"],
        }
    if kind is EventType.ERROR:
        return {
            "type": "error",
            "message": data["message"],
            "retryable": data.get("retryable", False),
        }
    if kind is EventType.DONE:
        return {
            "type": "done",
            "reason": data["reason"],
            "steps": data["steps"],
            "total_tokens": data["total_tokens"],
        }
    return None


def _json(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)
