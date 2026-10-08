"""Offline tests for file checkpoints — snapshot before edit, restore on demand."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from loca.core.events import EventType
from loca.core.loop import AgentLoop
from loca.observability.checkpoint import (
    ABSENT,
    BINARY,
    TEXT,
    UNAVAILABLE,
    CheckpointManager,
    FileSnapshot,
    resolve_within_workspace,
)
from loca.observability.storage import SessionStore
from loca.providers.base import LLMProvider
from loca.providers.types import (
    ChatRequest,
    ChatResponse,
    FinishReason,
    StreamChunk,
    ToolCall,
)
from loca.tools.base import ToolContext


@pytest.fixture
def store(tmp_path: Path):  # type: ignore[no-untyped-def]
    with SessionStore(tmp_path / "sessions.db") as s:
        s.create_session(session_id="s1", workspace=tmp_path)
        yield s


@pytest.fixture
def manager(store: SessionStore) -> CheckpointManager:
    return CheckpointManager(store)


def _capture(
    manager: CheckpointManager,
    workspace: Path,
    *,
    tool: str = "write_file",
    step: int = 0,
    **arguments: Any,
):
    return manager.capture(
        session_id="s1",
        step=step,
        tool=tool,
        arguments=arguments,
        workspace=workspace,
    )


# ---------------------------------------------------------------------------
# capture
# ---------------------------------------------------------------------------


def test_capture_records_a_file_that_did_not_exist(
    manager: CheckpointManager, workspace: Path
) -> None:
    checkpoint = _capture(manager, workspace, path="new.txt", content="hi")
    assert checkpoint is not None
    snapshot = checkpoint.snapshots[0]
    assert snapshot.path == "new.txt"
    assert snapshot.existed is False
    assert snapshot.encoding == ABSENT
    assert snapshot.restorable is True


def test_capture_stores_previous_content(
    manager: CheckpointManager, workspace: Path
) -> None:
    original = "original\n"
    (workspace / "a.txt").write_text(original, encoding="utf-8")
    # Read the bytes back: Windows text mode rewrites "\n" to "\r\n", and the
    # snapshot must reproduce the file byte-for-byte, not the source string.
    on_disk = (workspace / "a.txt").read_bytes()

    checkpoint = _capture(
        manager, workspace, tool="edit_file", path="a.txt", find="x", replace="y"
    )

    assert checkpoint is not None
    snapshot = checkpoint.snapshots[0]
    assert snapshot.existed is True
    assert snapshot.encoding == TEXT
    assert snapshot.size == len(on_disk)
    assert snapshot.restore_bytes() == on_disk


def test_capture_handles_binary_files(
    manager: CheckpointManager, workspace: Path
) -> None:
    payload = bytes(range(256))
    (workspace / "blob.bin").write_bytes(payload)
    checkpoint = _capture(manager, workspace, path="blob.bin")
    assert checkpoint is not None
    snapshot = checkpoint.snapshots[0]
    assert snapshot.encoding == BINARY
    assert snapshot.restore_bytes() == payload
    assert base64.b64decode(snapshot.data or "") == payload


def test_oversized_files_are_recorded_but_not_stored(tmp_path: Path, workspace: Path) -> None:
    with SessionStore(tmp_path / "s.db") as store:
        store.create_session(session_id="s1", workspace=workspace)
        manager = CheckpointManager(store, max_snapshot_bytes=8)
        (workspace / "big.txt").write_text("x" * 64, encoding="utf-8")
        checkpoint = _capture(manager, workspace, path="big.txt")
    assert checkpoint is not None
    snapshot = checkpoint.snapshots[0]
    assert snapshot.encoding == UNAVAILABLE
    assert snapshot.restorable is False


def test_capture_survives_a_file_that_vanishes_between_stat_and_read(
    manager: CheckpointManager, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkpoint observes. It must never be what aborts the turn."""
    (workspace / "a.txt").write_text("data", encoding="utf-8")

    def boom(self: Path) -> bytes:
        raise OSError("vanished between stat and read")

    monkeypatch.setattr(Path, "read_bytes", boom)
    checkpoint = _capture(manager, workspace, path="a.txt")

    assert checkpoint is not None
    assert checkpoint.snapshots[0].encoding == UNAVAILABLE
    assert checkpoint.snapshots[0].restorable is False


def test_capture_survives_a_store_that_refuses_to_write(
    manager: CheckpointManager, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A locked or full database degrades to "no snapshot", not to a crash."""
    (workspace / "a.txt").write_text("data", encoding="utf-8")

    def boom(*args: Any, **kwargs: Any) -> int:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(manager.store, "save_checkpoint", boom)

    assert _capture(manager, workspace, path="a.txt") is None


def test_capture_returns_none_for_untracked_tools(
    manager: CheckpointManager, workspace: Path
) -> None:
    """The shell can touch anything; we must not pretend we can undo it."""
    assert _capture(manager, workspace, tool="shell", command="rm -rf /", path="a.txt") is None
    assert _capture(manager, workspace, tool="read_file", path="a.txt") is None


def test_capture_returns_none_without_a_usable_path(
    manager: CheckpointManager, workspace: Path
) -> None:
    assert _capture(manager, workspace, content="no path here") is None
    assert _capture(manager, workspace, path="   ") is None
    assert _capture(manager, workspace, path=123) is None


def test_capture_refuses_paths_outside_the_workspace(
    manager: CheckpointManager, workspace: Path
) -> None:
    assert _capture(manager, workspace, path="../escape.txt") is None
    assert _capture(manager, workspace, path="C:/Windows/System32/drivers/etc/hosts") is None


def test_capture_is_recorded_in_the_store(
    manager: CheckpointManager, store: SessionStore, workspace: Path
) -> None:
    _capture(manager, workspace, path="a.txt", content="x")
    rows = store.list_checkpoints("s1")
    assert len(rows) == 1
    assert rows[0].tool == "write_file"
    assert rows[0].payload["snapshots"][0]["path"] == "a.txt"
    assert rows[0].payload["workspace"] == str(workspace)


def test_paths_are_stored_relative_and_posix(
    manager: CheckpointManager, workspace: Path
) -> None:
    (workspace / "pkg").mkdir()
    checkpoint = _capture(manager, workspace, path="pkg/mod.py", content="x")
    assert checkpoint is not None
    assert checkpoint.snapshots[0].path == "pkg/mod.py"
    assert "\\" not in checkpoint.snapshots[0].path


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------


def test_rollback_restores_previous_content(
    manager: CheckpointManager, store: SessionStore, workspace: Path
) -> None:
    target = workspace / "note.txt"
    target.write_text("before", encoding="utf-8")
    _capture(manager, workspace, tool="edit_file", path="note.txt", find="before", replace="after")
    target.write_text("after", encoding="utf-8")

    report = manager.rollback("s1", 0)

    assert report.changed is True
    assert report.restored == ["note.txt"]
    assert target.read_text(encoding="utf-8") == "before"


def test_rollback_deletes_files_that_were_new(
    manager: CheckpointManager, workspace: Path
) -> None:
    _capture(manager, workspace, path="created.txt", content="hello")
    (workspace / "created.txt").write_text("hello", encoding="utf-8")

    report = manager.rollback("s1", 0)

    assert report.deleted == ["created.txt"]
    assert not (workspace / "created.txt").exists()


def test_rollback_to_an_earlier_step_undoes_everything_after_it(
    manager: CheckpointManager, workspace: Path
) -> None:
    """Two edits to the same file: rolling back to 0 must restore the earliest."""
    target = workspace / "f.txt"
    target.write_text("v0", encoding="utf-8")
    _capture(manager, workspace, tool="edit_file", step=0, path="f.txt")  # pre-v0
    target.write_text("v1", encoding="utf-8")
    _capture(manager, workspace, tool="edit_file", step=1, path="f.txt")  # pre-v1
    target.write_text("v2", encoding="utf-8")

    report = manager.rollback("s1", 0)

    assert report.applied_checkpoints == 2
    assert target.read_text(encoding="utf-8") == "v0"


def test_rollback_from_a_later_step_leaves_earlier_edits_alone(
    manager: CheckpointManager, workspace: Path
) -> None:
    target = workspace / "f.txt"
    target.write_text("v0", encoding="utf-8")
    _capture(manager, workspace, step=0, path="f.txt")
    target.write_text("v1", encoding="utf-8")
    _capture(manager, workspace, step=1, path="f.txt")
    target.write_text("v2", encoding="utf-8")

    manager.rollback("s1", 1)

    assert target.read_text(encoding="utf-8") == "v1"


def test_rollback_reports_the_final_state_of_each_file(
    manager: CheckpointManager, workspace: Path
) -> None:
    """One file, two checkpoints: the report must show where it ended up."""
    _capture(manager, workspace, step=0, path="created.txt", content="first")
    (workspace / "created.txt").write_text("first", encoding="utf-8")
    _capture(manager, workspace, step=1, path="created.txt", content="second")
    (workspace / "created.txt").write_text("second", encoding="utf-8")

    report = manager.rollback("s1", 0)

    # Both actions really happened...
    assert report.restored == ["created.txt"]
    assert report.deleted == ["created.txt"]
    # ...but the file did not exist before step 0, so that is the final answer.
    assert report.settled() == {"created.txt": "deleted"}
    assert not (workspace / "created.txt").exists()


def test_rollback_undoes_several_writes_within_one_step(
    manager: CheckpointManager, workspace: Path
) -> None:
    """One step, three writes to the same path: the file must end up absent.

    The loop captures every tool call with the same ``global_step``, so this is
    the ordinary shape for a model that writes a file twice in one reply — and
    a crash mid-turn makes a restart reuse the step too. Ordering by ``step``
    alone left these in insertion order, so the *oldest* pre-state was applied
    first and the newest won: the file came back as the intermediate ``v2``.
    """
    target = workspace / "f.txt"
    for content in ("v1", "v2", "v3"):
        _capture(manager, workspace, step=1, path="f.txt", content=content)
        target.write_text(content, encoding="utf-8")

    report = manager.rollback("s1", 1)

    assert report.settled() == {"f.txt": "deleted"}
    assert report.deleted == ["f.txt"]
    assert not target.exists()


def test_settled_keeps_filenames_that_contain_parentheses(
    manager: CheckpointManager, workspace: Path
) -> None:
    """A path is a path; only the human-readable message may contain ``" ("``."""
    name = "notes (final).md"
    target = workspace / name
    target.write_text("before", encoding="utf-8")
    _capture(manager, workspace, step=0, path=name)
    target.write_text("after", encoding="utf-8")

    report = manager.rollback("s1", 0)

    assert report.settled() == {name: "restored"}
    assert target.read_text(encoding="utf-8") == "before"


def test_skips_keep_the_path_and_the_reason_apart(tmp_path: Path, workspace: Path) -> None:
    name = "notes (draft).md"
    with SessionStore(tmp_path / "s.db") as store:
        store.create_session(session_id="s1", workspace=workspace)
        manager = CheckpointManager(store, max_snapshot_bytes=4)
        (workspace / name).write_text("0123456789", encoding="utf-8")
        _capture(manager, workspace, path=name)

        report = manager.rollback("s1", 0)

    assert report.skips == [(name, "not captured")]
    assert report.skipped == [f"{name} (not captured)"]


def test_rollback_with_no_checkpoints_is_a_no_op(
    manager: CheckpointManager, workspace: Path
) -> None:
    report = manager.rollback("s1", 0)
    assert report.applied_checkpoints == 0
    assert report.changed is False


def test_rollback_skips_unrestorable_snapshots(
    tmp_path: Path, workspace: Path
) -> None:
    with SessionStore(tmp_path / "s.db") as store:
        store.create_session(session_id="s1", workspace=workspace)
        manager = CheckpointManager(store, max_snapshot_bytes=4)
        (workspace / "big.txt").write_text("0123456789", encoding="utf-8")
        _capture(manager, workspace, path="big.txt")

        report = manager.rollback("s1", 0)

    assert report.restored == []
    assert any("big.txt" in entry for entry in report.skipped)
    assert (workspace / "big.txt").read_text(encoding="utf-8") == "0123456789"


def test_rollback_uses_the_recorded_workspace_by_default(
    manager: CheckpointManager, workspace: Path
) -> None:
    (workspace / "a.txt").write_text("old", encoding="utf-8")
    _capture(manager, workspace, path="a.txt")
    (workspace / "a.txt").write_text("new", encoding="utf-8")

    manager.rollback("s1", 0)  # no explicit workspace

    assert (workspace / "a.txt").read_text(encoding="utf-8") == "old"


def test_rollback_accepts_an_explicit_workspace(
    manager: CheckpointManager, workspace: Path, tmp_path: Path
) -> None:
    """A moved workspace can be restored somewhere else."""
    (workspace / "a.txt").write_text("old", encoding="utf-8")
    _capture(manager, workspace, path="a.txt")
    elsewhere = tmp_path / "clone"
    elsewhere.mkdir()
    (elsewhere / "a.txt").write_text("new", encoding="utf-8")

    manager.rollback("s1", 0, workspace=elsewhere)

    assert (elsewhere / "a.txt").read_text(encoding="utf-8") == "old"


def test_rollback_skips_paths_that_escaped_the_workspace(
    manager: CheckpointManager, store: SessionStore, workspace: Path
) -> None:
    """A hand-edited (or hostile) snapshot must not write outside the workspace."""
    store.save_checkpoint(
        "s1",
        step=0,
        tool="write_file",
        payload={
            "session_id": "s1",
            "step": 0,
            "tool": "write_file",
            "workspace": str(workspace),
            "created_at": "2026-01-01T00:00:00+00:00",
            "snapshots": [
                FileSnapshot(
                    path="../../evil.txt", existed=True, size=1, encoding=TEXT, data="x"
                ).to_dict()
            ],
        },
    )

    report = manager.rollback("s1", 0)

    assert report.restored == []
    assert any("outside workspace" in entry for entry in report.skipped)


def test_checkpoint_payload_round_trips(manager: CheckpointManager, workspace: Path) -> None:
    (workspace / "a.txt").write_text("data", encoding="utf-8")
    original = _capture(manager, workspace, path="a.txt")
    assert original is not None
    restored = type(original).from_dict(original.to_dict())
    assert restored.snapshots[0].data == original.snapshots[0].data
    assert restored.workspace == original.workspace


# ---------------------------------------------------------------------------
# sandbox helper
# ---------------------------------------------------------------------------


def test_resolve_within_workspace(workspace: Path) -> None:
    (workspace / "sub").mkdir()
    expected = (workspace / "sub" / "f.txt").resolve()
    assert resolve_within_workspace(workspace, "sub/f.txt") == expected
    assert resolve_within_workspace(workspace, "../x") is None
    assert resolve_within_workspace(workspace, str(workspace / "ok.txt")) is not None
    assert resolve_within_workspace(workspace, ".") is not None


# ---------------------------------------------------------------------------
# loop integration
# ---------------------------------------------------------------------------


class _OneToolCallProvider(LLMProvider):
    name = "scripted"

    def __init__(self, calls: list[ToolCall]) -> None:
        self._calls = calls
        self._turn = 0

    def chat(self, request: ChatRequest) -> ChatResponse:  # pragma: no cover
        raise NotImplementedError

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamChunk]:
        self._turn += 1
        if self._turn == 1:
            yield StreamChunk(
                delta_tool_calls=list(self._calls), finish_reason=FinishReason.TOOL_USE
            )
        else:
            yield StreamChunk(delta_content="done", finish_reason=FinishReason.STOP)


def test_loop_emits_a_checkpoint_event_before_the_tool_runs(
    store: SessionStore, workspace: Path
) -> None:
    (workspace / "target.txt").write_text("before", encoding="utf-8")
    provider = _OneToolCallProvider(
        [ToolCall(id="c1", name="edit_file", arguments={"path": "target.txt"})]
    )
    loop = AgentLoop(
        provider=provider,
        tools=[],
        system_prompt="sys",
        retries=0,
        checkpoint_manager=CheckpointManager(store),
    )
    ctx = ToolContext(workspace=workspace, session_id="s1", step_index=0)

    events = list(loop.run(ctx, user_message="edit it"))

    checkpoints = [e for e in events if e.type is EventType.CHECKPOINT]
    assert len(checkpoints) == 1
    assert checkpoints[0].data["files"] == ["target.txt"]
    assert checkpoints[0].data["restorable"] is True
    # The checkpoint precedes the result, and the model still saw a reply.
    kinds = [e.type for e in events]
    assert kinds.index(EventType.CHECKPOINT) < kinds.index(EventType.TOOL_RESULT)
    assert kinds[-1] is EventType.DONE


def test_loop_advances_the_session_global_step_counter(
    store: SessionStore, workspace: Path
) -> None:
    provider = _OneToolCallProvider(
        [ToolCall(id="c1", name="write_file", arguments={"path": "a.txt", "content": "x"})]
    )
    loop = AgentLoop(
        provider=provider,
        tools=[],
        system_prompt="sys",
        retries=0,
        checkpoint_manager=CheckpointManager(store),
    )
    ctx = ToolContext(workspace=workspace, session_id="s1", step_index=0)

    list(loop.run(ctx, user_message="write it"))
    first_turn_end = ctx.step_index
    assert first_turn_end > 0

    list(loop.run(ctx, user_message="again"))
    assert ctx.step_index > first_turn_end


def test_step_numbers_do_not_collide_across_restarts(
    store: SessionStore, workspace: Path
) -> None:
    """Two loops (i.e. two CLI launches) must not both write checkpoint step 0."""
    from loca.observability.storage import STEP_COUNTER_KEY

    def one_turn() -> None:
        provider = _OneToolCallProvider(
            [ToolCall(id="c1", name="write_file", arguments={"path": "a.txt", "content": "x"})]
        )
        loop = AgentLoop(
            provider=provider,
            tools=[],
            system_prompt="sys",
            retries=0,
            checkpoint_manager=CheckpointManager(store),
        )
        ctx = ToolContext(
            workspace=workspace,
            session_id="s1",
            step_index=store.next_step("s1"),  # what the CLI does on startup
        )
        list(loop.run(ctx, user_message="write it"))
        store.set_next_step("s1", ctx.step_index)

    one_turn()
    one_turn()

    steps = [row.step for row in store.list_checkpoints("s1")]
    # One number per model step, and the counter kept going across the restart
    # (each turn here is: call the tool, then answer — two steps).
    assert steps == [0, 2]
    assert len(set(steps)) == len(steps), "checkpoint steps must never collide"
    assert store.get_session("s1").metadata[STEP_COUNTER_KEY] == 4


def test_loop_without_a_manager_emits_no_checkpoints(workspace: Path) -> None:
    provider = _OneToolCallProvider(
        [ToolCall(id="c1", name="write_file", arguments={"path": "a.txt", "content": "x"})]
    )
    loop = AgentLoop(provider=provider, tools=[], system_prompt="sys", retries=0)
    ctx = ToolContext(workspace=workspace, session_id="s1", step_index=0)

    events = list(loop.run(ctx, user_message="write it"))

    assert not [e for e in events if e.type is EventType.CHECKPOINT]
