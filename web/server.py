"""FastAPI server that exposes the loca agent as a streaming chat API.

The HTML page lives at ``GET /`` and POSTs to ``/api/chat`` which returns an
SSE stream. Each event is one of:

- ``{"type": "text", "content": "..."}``            streaming text
- ``{"type": "tool_call", "name": "...", "args": {...}}``
- ``{"type": "tool_result", "name": "...", "content": "...", "is_error": bool}``
- ``{"type": "usage", "prompt": N, "completion": N, "total": N}``
- ``{"type": "context_trimmed", "dropped": N, "estimated_tokens": N, "budget": N}``
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

from loca.core.events import EventType
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
                if event.type is EventType.TEXT_DELTA:
                    yield {
                        "event": "message",
                        "data": _json({"type": "text", "content": event.data["content"]}),
                    }
                elif event.type is EventType.TOOL_CALL:
                    yield {
                        "event": "message",
                        "data": _json(
                            {
                                "type": "tool_call",
                                "name": event.data["name"],
                                "args": event.data["arguments"],
                            }
                        ),
                    }
                elif event.type is EventType.TOOL_RESULT:
                    yield {
                        "event": "message",
                        "data": _json(
                            {
                                "type": "tool_result",
                                "name": event.data["name"],
                                "content": event.data["content"],
                                "is_error": event.data["is_error"],
                            }
                        ),
                    }
                elif event.type is EventType.USAGE:
                    yield {
                        "event": "message",
                        "data": _json(
                            {
                                "type": "usage",
                                "prompt": event.data["prompt_tokens"],
                                "completion": event.data["completion_tokens"],
                                "total": event.data["total_tokens"],
                            }
                        ),
                    }
                elif event.type is EventType.CONTEXT_TRIMMED:
                    yield {
                        "event": "message",
                        "data": _json(
                            {
                                "type": "context_trimmed",
                                "dropped": event.data["dropped"],
                                "estimated_tokens": event.data["estimated_tokens"],
                                "budget": event.data["budget"],
                            }
                        ),
                    }
                elif event.type is EventType.RECOVERY:
                    yield {
                        "event": "message",
                        "data": _json(
                            {
                                "type": "recovery",
                                "reason": event.data["reason"],
                                "step": event.data["step"],
                            }
                        ),
                    }
                elif event.type is EventType.ERROR:
                    yield {
                        "event": "message",
                        "data": _json(
                            {
                                "type": "error",
                                "message": event.data["message"],
                                "retryable": event.data.get("retryable", False),
                            }
                        ),
                    }
                elif event.type is EventType.DONE:
                    yield {
                        "event": "message",
                        "data": _json(
                            {
                                "type": "done",
                                "reason": event.data["reason"],
                                "steps": event.data["steps"],
                                "total_tokens": event.data["total_tokens"],
                            }
                        ),
                    }
        except Exception as exc:  # pragma: no cover - defensive
            yield {
                "event": "message",
                "data": _json({"type": "error", "message": f"{type(exc).__name__}: {exc}"}),
            }

    return EventSourceResponse(event_source())


def _json(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)
