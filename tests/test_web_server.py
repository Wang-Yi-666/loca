"""Offline tests for the FastAPI/SSE chat endpoint.

The provider is monkeypatched, so nothing here touches the network. These
tests pin the wire format the browser client depends on — including the
``error`` and ``context_trimmed`` events added in Week 3.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import web.server as server
from loca.agents import CODING_AGENT
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


@pytest.fixture(autouse=True)
def _isolated_session_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let these tests touch the developer's real session database.

    ``/api/chat`` now opens the same database the CLI uses (that is what lets
    ``loca rollback`` undo a browser turn), so without this every test would
    write sessions and file snapshots into ``~/.loca/sessions.db``.
    """
    monkeypatch.setenv("LOCA_DB", str(tmp_path / "web-sessions.db"))


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


# ---------------------------------------------------------------------------
# Week 4: the new event types must reach the browser
# ---------------------------------------------------------------------------


def test_serialize_event_maps_checkpoint_and_summary() -> None:
    from loca.core.events import AgentEvent, EventType

    checkpoint = server._serialize_event(
        AgentEvent(
            type=EventType.CHECKPOINT,
            data={"step": 3, "tool": "write_file", "files": ["a.py"], "restorable": True},
        )
    )
    assert checkpoint == {
        "type": "checkpoint",
        "step": 3,
        "tool": "write_file",
        "files": ["a.py"],
        "restorable": True,
    }

    summarized = server._serialize_event(
        AgentEvent(
            type=EventType.CONTEXT_SUMMARIZED,
            data={
                "summarized": 8,
                "dropped": 8,
                "summary_tokens": 120,
                "estimated_tokens": 900,
                "budget": 800,
            },
        )
    )
    assert summarized is not None
    assert summarized["type"] == "context_summarized"
    assert summarized["summarized"] == 8
    assert summarized["summary_tokens"] == 120


def test_serialize_event_ignores_step_start() -> None:
    from loca.core.events import AgentEvent, EventType

    assert server._serialize_event(AgentEvent(type=EventType.STEP_START, data={"step": 0})) is None


# ---------------------------------------------------------------------------
# Workspace selection
#
# The web UI has to be able to point the agent somewhere other than the project
# root, and a bad path has to fail loudly rather than quietly running the tools
# in the wrong directory.
# ---------------------------------------------------------------------------


def _run_turn(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    monkeypatch.setattr(server, "get_provider", lambda *a, **k: _read_then_answer())
    with client.stream("POST", "/api/chat", json=payload) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    return _events(body)


def test_chat_runs_in_the_workspace_the_request_names(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A per-request workspace must actually reach the tools.

    The scripted provider reads ``pyproject.toml``. The content that comes back
    has to be the one planted in ``tmp_path`` and not the real file at the
    project root — otherwise the field is accepted and then ignored.
    """
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'elsewhere'\n", encoding="utf-8"
    )

    events = _run_turn(
        client,
        monkeypatch,
        {"message": "what is this project?", "workspace": str(tmp_path)},
    )

    result = next(e for e in events if e["type"] == "tool_result")
    assert result["is_error"] is False
    assert "name = 'elsewhere'" in result["content"]
    # Compare a key only the real file carries. Asserting on the bare word
    # "loca" would fire spuriously — the sandbox path contains it too.
    assert "requires-python" not in result["content"]


def test_chat_still_defaults_to_the_project_root(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Omitting the field keeps the previous behaviour."""
    events = _run_turn(client, monkeypatch, {"message": "what is this project?"})

    result = next(e for e in events if e["type"] == "tool_result")
    assert 'name = "loca"' in result["content"]


def test_blank_workspace_falls_back_to_the_default() -> None:
    for blank in (None, "", "   "):
        assert server._workspace_for(blank) == server.DEFAULT_WORKSPACE


def test_workspace_rejects_a_path_that_does_not_exist(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        server._workspace_for(str(tmp_path / "nope"))


def test_workspace_rejects_a_file(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ValueError, match="not a directory"):
        server._workspace_for(str(target))


def test_workspace_rejects_a_git_bash_path() -> None:
    with pytest.raises(ValueError, match="Git-Bash"):
        server._workspace_for("/d/repo")


def test_a_bad_workspace_is_reported_before_the_provider_is_called(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The path is the one thing the caller just typed, so it is checked first."""
    provider = _read_then_answer()
    monkeypatch.setattr(server, "get_provider", lambda *a, **k: provider)

    with client.stream(
        "POST",
        "/api/chat",
        json={"message": "hello", "workspace": str(tmp_path / "missing")},
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())

    events = _events(body)
    errors = [e for e in events if e["type"] == "error"]
    assert len(errors) == 1
    assert "does not exist" in errors[0]["message"]
    assert "done" not in [e["type"] for e in events]
    assert provider.calls == 0


# ---------------------------------------------------------------------------
# Checkpoints, sessions and undo
#
# The browser is the surface where undo matters most — the file on disk is out
# of sight while you type — so a turn that edits a file has to leave a snapshot
# behind, and there has to be a way back to it.
# ---------------------------------------------------------------------------


def _writer(path: str, content: str) -> ScriptedProvider:
    """A provider that writes ``path`` once, then answers."""
    return ScriptedProvider(
        [
            [
                StreamChunk(
                    delta_content="writing. ",
                    delta_tool_calls=[
                        ToolCall(
                            id="c1",
                            name="write_file",
                            arguments={"path": path, "content": content},
                        )
                    ],
                    finish_reason=FinishReason.TOOL_USE,
                )
            ],
            [StreamChunk(delta_content="done", finish_reason=FinishReason.STOP)],
        ]
    )


def _stream_turn(client: TestClient, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """POST one turn and parse the stream. Patch the provider first."""
    with client.stream("POST", "/api/chat", json=payload) as resp:
        assert resp.status_code == 200
        return _events("".join(resp.iter_text()))


def _session_of(events: list[dict[str, Any]]) -> str:
    """The id the server announced as the first event of the turn."""
    assert events[0]["type"] == "session"
    return events[0]["id"]


def _checkpoint_of(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(e for e in events if e["type"] == "checkpoint")


def test_the_turn_announces_its_session_first(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "get_provider", lambda *a, **k: _read_then_answer())

    events = _stream_turn(client, {"message": "what is this project?"})

    assert events[0]["type"] == "session"
    assert events[0]["id"]


def test_the_announced_session_id_round_trips(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Echoing the id back has to land in the *same* session, not a new one."""
    monkeypatch.setattr(server, "get_provider", lambda *a, **k: _read_then_answer())

    session_id = _session_of(_stream_turn(client, {"message": "hello"}))
    again = _session_of(_stream_turn(client, {"message": "again", "session_id": session_id}))

    assert again == session_id
    store = server.open_store()
    try:
        info = store.get_session(session_id)
        assert info is not None
        # The transcript is stored too, which is what makes
        # `loca sessions show <id>` able to explain what the checkpoints belong to.
        assert store.message_count(session_id) > 0
    finally:
        store.close()


def test_a_turn_runs_a_fully_assembled_agent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The regression guard for a bug that shipped here twice.

    The web entry point used to assemble its own loop. It had no
    ``CheckpointManager`` — so no ``checkpoint`` event ever fired and the undo
    button was dead code — and later no ``ContextManager``, so a long browser
    conversation dropped its oldest turns instead of summarizing them. Both are
    the same omission, so this asserts on the *built* loop rather than on the
    source: moving the omission somewhere else must not pass.
    """
    monkeypatch.setattr(server, "get_provider", lambda *a, **k: _read_then_answer())

    seen: dict[str, Any] = {}
    real_build = server.build_agent

    def spy(spec: Any, **kwargs: Any) -> Any:
        runtime = real_build(spec, **kwargs)
        seen["spec"] = spec
        seen["loop"] = runtime.loop
        return runtime

    monkeypatch.setattr(server, "build_agent", spy)

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text('name = "loca"\n', encoding="utf-8")

    _stream_turn(client, {"message": "what is this?", "workspace": str(workspace)})

    loop = seen["loop"]
    assert seen["spec"] is CODING_AGENT
    assert loop.system_prompt == CODING_AGENT.system_prompt
    assert [tool.name for tool in loop.tools] == list(CODING_AGENT.tool_names)
    assert loop.checkpoint_manager is not None, "no checkpoints — undo has nothing to attach to"
    assert loop.context_manager is not None, "a long chat would silently drop its history"
    assert loop.context_token_budget is None, "one policy: the manager owns the budget"


def test_a_file_edit_is_checkpointed_and_can_be_undone(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / "notes.txt"
    target.write_text("before\n", encoding="utf-8")
    monkeypatch.setattr(
        server, "get_provider", lambda *a, **k: _writer("notes.txt", "after\n")
    )

    events = _stream_turn(client, {"message": "rewrite notes.txt", "workspace": str(workspace)})

    checkpoint = _checkpoint_of(events)
    assert checkpoint["files"] == ["notes.txt"]
    assert checkpoint["tool"] == "write_file"
    assert checkpoint["restorable"] is True
    assert target.read_text(encoding="utf-8") == "after\n"

    undone = client.post(
        "/api/rollback",
        json={"session_id": _session_of(events), "step": checkpoint["step"]},
    ).json()

    assert undone["ok"] is True
    assert undone["applied"] == 1
    assert undone["files"] == [{"path": "notes.txt", "action": "restored"}]
    assert target.read_text(encoding="utf-8") == "before\n"


def test_a_created_file_is_deleted_on_rollback(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Restoring "did not exist" is not the same as restoring "empty"."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setattr(server, "get_provider", lambda *a, **k: _writer("new.txt", "hi\n"))

    events = _stream_turn(client, {"message": "create new.txt", "workspace": str(workspace)})
    created = workspace / "new.txt"
    assert created.exists()

    undone = client.post(
        "/api/rollback",
        json={"session_id": _session_of(events), "step": _checkpoint_of(events)["step"]},
    ).json()

    assert undone["ok"] is True
    assert undone["files"] == [{"path": "new.txt", "action": "deleted"}]
    assert not created.exists()


def test_each_turn_checkpoints_at_a_new_step(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two turns must not both checkpoint at step 0.

    Rollback undoes a step *and everything after it*, so colliding steps would
    make "undo just this turn" impossible to express — and the second turn's
    undo would silently swallow the first turn's edit.
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / "notes.txt"

    monkeypatch.setattr(server, "get_provider", lambda *a, **k: _writer("notes.txt", "v1\n"))
    first = _stream_turn(client, {"message": "write v1", "workspace": str(workspace)})
    session_id = _session_of(first)

    monkeypatch.setattr(server, "get_provider", lambda *a, **k: _writer("notes.txt", "v2\n"))
    second = _stream_turn(
        client,
        {"message": "write v2", "session_id": session_id, "workspace": str(workspace)},
    )

    step_one, step_two = _checkpoint_of(first)["step"], _checkpoint_of(second)["step"]
    assert step_two > step_one, "the step counter restarted, so both turns share a step"
    assert target.read_text(encoding="utf-8") == "v2\n"

    undone = client.post(
        "/api/rollback", json={"session_id": session_id, "step": step_two}
    ).json()

    assert undone["ok"] is True
    assert undone["applied"] == 1
    assert target.read_text(encoding="utf-8") == "v1\n"


def test_rollback_restores_each_workspace_from_its_own_snapshot(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The snapshot is taken relative to the workspace the edit happened in.

    Both workspaces hold a file with the same name, and both were edited in one
    session. Undoing the whole session has to put each file back where it came
    from — a rollback driven by a single "current workspace" would either write
    one directory's bytes into the other or skip half the work.
    """
    first_ws, second_ws = tmp_path / "first", tmp_path / "second"
    first_ws.mkdir()
    second_ws.mkdir()
    (first_ws / "notes.txt").write_text("first before\n", encoding="utf-8")
    (second_ws / "notes.txt").write_text("second before\n", encoding="utf-8")

    monkeypatch.setattr(
        server, "get_provider", lambda *a, **k: _writer("notes.txt", "first after\n")
    )
    first = _stream_turn(client, {"message": "edit here", "workspace": str(first_ws)})
    session_id = _session_of(first)
    step = _checkpoint_of(first)["step"]

    monkeypatch.setattr(
        server, "get_provider", lambda *a, **k: _writer("notes.txt", "second after\n")
    )
    _stream_turn(
        client,
        {"message": "now edit over there", "session_id": session_id, "workspace": str(second_ws)},
    )

    undone = client.post(
        "/api/rollback", json={"session_id": session_id, "step": step}
    ).json()

    assert undone["ok"] is True
    assert undone["applied"] == 2
    assert (first_ws / "notes.txt").read_text(encoding="utf-8") == "first before\n"
    assert (second_ws / "notes.txt").read_text(encoding="utf-8") == "second before\n"


def test_rollback_reports_an_unknown_session(client: TestClient) -> None:
    out = client.post(
        "/api/rollback", json={"session_id": "20260101-000000-abcdef", "step": 0}
    ).json()

    assert out["ok"] is False
    assert "unknown session" in out["message"]


def test_rollback_without_checkpoints_says_so(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A turn that only read files leaves nothing to undo."""
    monkeypatch.setattr(server, "get_provider", lambda *a, **k: _read_then_answer())
    events = _stream_turn(client, {"message": "what is this project?"})
    assert "checkpoint" not in [e["type"] for e in events]

    out = client.post(
        "/api/rollback", json={"session_id": _session_of(events), "step": 0}
    ).json()

    assert out["ok"] is False
    assert "nothing to undo" in out["message"]


def test_rollback_rejects_a_session_id_we_never_issued(client: TestClient) -> None:
    out = client.post(
        "/api/rollback", json={"session_id": "not a session id!", "step": 0}
    ).json()

    assert out["ok"] is False
    assert "not a loca session id" in out["message"]


def test_a_bad_session_id_is_refused_before_the_provider_is_called(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _read_then_answer()
    monkeypatch.setattr(server, "get_provider", lambda *a, **k: provider)

    events = _stream_turn(client, {"message": "hello", "session_id": "/d/repo"})

    errors = [e for e in events if e["type"] == "error"]
    assert len(errors) == 1
    assert "not a loca session id" in errors[0]["message"]
    # No session event either: nothing was created, so nothing was announced.
    assert "session" not in [e["type"] for e in events]
    assert provider.calls == 0
