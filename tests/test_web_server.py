"""Offline tests for the FastAPI/SSE chat endpoint.

The provider is monkeypatched, so nothing here touches the network. These
tests pin the wire format the browser client depends on — including the
``error`` and ``context_trimmed`` events added in Week 3.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

import web.server as server
from loca.providers.base import LLMProvider
from loca.providers.types import (
    ChatRequest,
    ChatResponse,
    FinishReason,
    StreamChunk,
    ToolCall,
)


class ScriptedProvider(LLMProvider):
    """Replays a fixed list of stream chunks for every call."""

    name = "scripted"

    def __init__(self, turns: list[list[Any]]) -> None:
        self._turns = turns
        self.calls = 0
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:  # pragma: no cover
        raise NotImplementedError

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamChunk]:
        self.requests.append(request)
        turn = self._turns[min(self.calls, len(self._turns) - 1)]
        self.calls += 1
        for item in turn:
            if isinstance(item, BaseException):
                raise item
            yield item


def _read_then_answer() -> ScriptedProvider:
    return ScriptedProvider(
        [
            [
                StreamChunk(
                    delta_content="Let me look. ",
                    delta_tool_calls=[
                        ToolCall(
                            id="c1",
                            name="read_file",
                            arguments={"path": "pyproject.toml"},
                        )
                    ],
                    finish_reason=FinishReason.TOOL_USE,
                )
            ],
            [
                StreamChunk(
                    delta_content="It declares the loca package.",
                    finish_reason=FinishReason.STOP,
                )
            ],
        ]
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(server.app)


def _events(body: str) -> list[dict[str, Any]]:
    """Parse an SSE body into the JSON payloads of each ``data:`` line."""
    out: list[dict[str, Any]] = []
    for block in body.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data: "):
                out.append(json.loads(line[len("data: ") :]))
    return out


def test_health_endpoint(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    assert "default_workspace" in payload


def test_index_serves_the_chat_page(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "loca" in resp.text


def test_chat_streams_tool_call_then_done(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "get_provider", lambda *a, **k: _read_then_answer())

    with client.stream("POST", "/api/chat", json={"message": "what is this project?"}) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())

    events = _events(body)
    types = [e["type"] for e in events]
    assert "tool_call" in types
    assert "tool_result" in types
    assert "text" in types
    assert types[-1] == "done"

    tool_call = next(e for e in events if e["type"] == "tool_call")
    assert tool_call["name"] == "read_file"
    assert tool_call["args"] == {"path": "pyproject.toml"}

    tool_result = next(e for e in events if e["type"] == "tool_result")
    assert tool_result["is_error"] is False
    assert "loca" in tool_result["content"]

    text = "".join(e["content"] for e in events if e["type"] == "text")
    assert "Let me look." in text
    assert "loca package" in text

    done = events[-1]
    assert done["reason"] == "stop"
    assert done["steps"] == 2


def test_chat_reports_provider_failure_as_error_event(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dead provider must not break the SSE stream mid-flight."""
    failing = ScriptedProvider([[ValueError("invalid api key")]])
    monkeypatch.setattr(server, "get_provider", lambda *a, **k: failing)

    with client.stream("POST", "/api/chat", json={"message": "hello"}) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())

    events = _events(body)
    errors = [e for e in events if e["type"] == "error"]
    assert len(errors) == 1
    assert "invalid api key" in errors[0]["message"]
    assert errors[0]["retryable"] is False
    # No ``done`` event: the turn died before the model produced an answer.
    assert "done" not in [e["type"] for e in events]


def test_chat_reports_missing_provider_as_error_event(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a: Any, **k: Any) -> None:
        raise ValueError("LOCA_DEEPSEEK_API_KEY is not set")

    monkeypatch.setattr(server, "get_provider", boom)

    with client.stream("POST", "/api/chat", json={"message": "hello"}) as resp:
        body = "".join(resp.iter_text())

    errors = [e for e in _events(body) if e["type"] == "error"]
    assert errors and "LOCA_DEEPSEEK_API_KEY" in errors[0]["message"]


def test_chat_forwards_multi_turn_history(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ScriptedProvider(
        [[StreamChunk(delta_content="ok", finish_reason=FinishReason.STOP)]]
    )
    monkeypatch.setattr(server, "get_provider", lambda *a, **k: provider)

    with client.stream(
        "POST",
        "/api/chat",
        json={
            "message": "and then?",
            "history": [
                {"role": "user", "content": "first question"},
                {"role": "assistant", "content": "first answer"},
            ],
        },
    ) as resp:
        body = "".join(resp.iter_text())

    assert [e["type"] for e in _events(body)][-1] == "done"

    # The prior turns really were replayed to the provider, in order.
    sent = provider.requests[0].messages
    assert [m.role.value for m in sent] == ["system", "user", "assistant", "user"]
    assert [m.content for m in sent[1:]] == [
        "first question",
        "first answer",
        "and then?",
    ]
