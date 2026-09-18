"""FastAPI server that exposes the loca agent as a streaming chat API.

The HTML page lives at ``GET /`` and POSTs to ``/api/chat`` which returns an
SSE stream. Each event is one of:

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

Run::

    .venv/Scripts/python.exe -m uvicorn web.server:app --reload --port 8765

Then open http://localhost:8765 in a browser.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from loca.core.events import AgentEvent, EventType
from loca.core.loop import AgentLoop
from loca.providers import LLMProvider
from loca.providers.registry import get_provider
from loca.tools import register_default_tools
from loca.tools.base import ToolContext

# Load .env so the API key is available without manual setup.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Register the four built-in tools once at import time.
register_default_tools()

# Default workspace is the project root. In a real product this would be
# configurable per-session.
DEFAULT_WORKSPACE = Path(__file__).resolve().parent.parent

app = FastAPI(title="loca agent", version="0.1.0")


# ---- request/response models -----------------------------------------------


class ChatTurn(BaseModel):
    """A single user turn plus optional history for multi-turn chats."""

    message: str
    history: list[dict] | None = None  # [{"role": "user|assistant|tool", "content": "..."}]


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
        # Resolve provider lazily so missing keys surface as a friendly error
        # event instead of crashing the worker.
        try:
            provider: LLMProvider = get_provider()
        except Exception as exc:
            yield {"event": "message", "data": _json({"type": "error", "message": str(exc)})}
            return

        ctx = ToolContext(
            workspace=DEFAULT_WORKSPACE,
            session_id="web",
            step_index=0,
        )
        loop = AgentLoop(provider=provider)

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

    return EventSourceResponse(event_source())


def _serialize_event(event: AgentEvent) -> dict | None:
    """Map a loop event onto the payload shape the browser expects.

    Returns ``None`` for events the UI has nothing to render (``step_start``).
    Kept out of the async generator so it can be unit-tested on its own.
    """
    data = event.data
    kind = event.type

    if kind is EventType.TEXT_DELTA:
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
        return {"type": "recovery", "reason": data["reason"], "step": data["step"]}
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
