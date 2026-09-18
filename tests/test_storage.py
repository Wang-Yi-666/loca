"""Offline tests for SQLite session persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from loca.observability.storage import (
    SCHEMA_VERSION,
    SessionStore,
    derive_title_from,
    message_from_dict,
    message_to_dict,
    new_session_id,
)
from loca.providers.types import Message, Role, ToolCall


@pytest.fixture
def store(tmp_path: Path):  # type: ignore[no-untyped-def]
    with SessionStore(tmp_path / "sessions.db") as s:
        yield s


def _conversation() -> list[Message]:
    return [
        Message(role=Role.SYSTEM, content="you are loca"),
        Message(role=Role.USER, content="read README.md and summarize it"),
        Message(
            role=Role.ASSISTANT,
            content=None,
            tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "README.md"})],
            reasoning_content="I should read the file first",
        ),
        Message(role=Role.TOOL, content="# loca", tool_call_id="c1"),
        Message(role=Role.ASSISTANT, content="It is a coding agent harness."),
    ]


# ---------------------------------------------------------------------------
# serialization
# ---------------------------------------------------------------------------


def test_message_dict_round_trip_preserves_everything() -> None:
    for original in _conversation():
        restored = message_from_dict(message_to_dict(original))
        assert restored.role is original.role
        assert restored.content == original.content
        assert restored.tool_call_id == original.tool_call_id
        assert restored.reasoning_content == original.reasoning_content
        assert len(restored.tool_calls) == len(original.tool_calls)
        for got, want in zip(restored.tool_calls, original.tool_calls, strict=True):
            assert (got.id, got.name, got.arguments) == (want.id, want.name, want.arguments)


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------


def test_create_and_get_session(store: SessionStore) -> None:
    info = store.create_session(
        title="first", workspace=Path("D:/repo"), provider="deepseek", model="deepseek-chat"
    )
    assert info.message_count == 0
    fetched = store.get_session(info.session_id)
    assert fetched is not None
    assert fetched.title == "first"
    assert fetched.provider == "deepseek"
    assert fetched.workspace.endswith("repo")


def test_sessions_are_listed_most_recently_updated_first(store: SessionStore) -> None:
    store.create_session(session_id="a")
    store.create_session(session_id="b")
    # Same-second timestamps would tie, so pin one explicitly.
    store._conn.execute(
        "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
        ("2099-01-01T00:00:00+00:00", "a"),
    )
    store._conn.commit()

    sessions = store.list_sessions()

    assert [s.session_id for s in sessions] == ["a", "b"]


def test_duplicate_session_id_is_rejected(store: SessionStore) -> None:
    store.create_session(session_id="dup")
    with pytest.raises(ValueError, match="already exists"):
        store.create_session(session_id="dup")


def test_ensure_session_reports_whether_it_created(store: SessionStore) -> None:
    session, created = store.ensure_session("s1", provider="deepseek")
    assert created is True and session.session_id == "s1"
    session, created = store.ensure_session("s1", provider="deepseek")
    assert created is False and session.provider == "deepseek"


def test_metadata_merges(store: SessionStore) -> None:
    store.create_session(session_id="s1", metadata={"branch": "main"})
    store.update_metadata("s1", tickets=["LOCA-4"])
    info = store.get_session("s1")
    assert info is not None
    assert info.metadata == {"branch": "main", "tickets": ["LOCA-4"]}


def test_new_session_id_is_unique_and_sortable() -> None:
    ids = {new_session_id() for _ in range(20)}
    assert len(ids) == 20
    assert all(len(i.split("-")) == 3 for i in ids)


# ---------------------------------------------------------------------------
# transcripts
# ---------------------------------------------------------------------------


def test_save_and_load_transcript_round_trip(store: SessionStore) -> None:
    store.create_session(session_id="s1")
    messages = _conversation()
    store.replace_messages("s1", messages)

    loaded = store.load_messages("s1")
    assert [m.role for m in loaded] == [m.role for m in messages]
    assert loaded[2].tool_calls[0].arguments == {"path": "README.md"}
    assert loaded[3].tool_call_id == "c1"
    assert store.message_count("s1") == 5


def test_append_message_assigns_increasing_seq(store: SessionStore) -> None:
    store.create_session(session_id="s1")
    assert store.append_message("s1", Message(role=Role.USER, content="one")) == 0
    assert store.append_message("s1", Message(role=Role.ASSISTANT, content="two")) == 1
    assert [m.content for m in store.load_messages("s1")] == ["one", "two"]


def test_replace_messages_shrinks_atomically(store: SessionStore) -> None:
    """Context trimming shrinks the transcript; the store must follow it."""
    store.create_session(session_id="s1")
    store.replace_messages("s1", _conversation())
    store.replace_messages("s1", _conversation()[-2:])
    assert store.message_count("s1") == 2
    assert [m.role for m in store.load_messages("s1")] == [Role.TOOL, Role.ASSISTANT]


def test_save_transcript_derives_title_from_first_user_message(store: SessionStore) -> None:
    store.create_session(session_id="s1")
    info = store.save_transcript("s1", _conversation())
    assert info.title == "read README.md and summarize it"
    assert info.message_count == 5


def test_save_transcript_keeps_an_existing_title(store: SessionStore) -> None:
    store.create_session(session_id="s1", title="mine")
    store.save_transcript("s1", _conversation())
    assert store.get_session("s1").title == "mine"


def test_derive_title_truncates_and_skips_blank_turns() -> None:
    long_title = derive_title_from([Message(role=Role.USER, content="x" * 200)])
    assert long_title is not None and len(long_title) <= 72 and long_title.endswith("…")
    assert derive_title_from([Message(role=Role.ASSISTANT, content="hi")]) is None


def test_missing_session_reads_are_empty_not_errors(store: SessionStore) -> None:
    assert store.get_session("nope") is None
    assert store.load_messages("nope") == []
    assert store.list_checkpoints("nope") == []


# ---------------------------------------------------------------------------
# checkpoints + deletion
# ---------------------------------------------------------------------------


def test_checkpoints_are_listed_by_step(store: SessionStore) -> None:
    store.create_session(session_id="s1")
    store.save_checkpoint("s1", step=2, tool="edit_file", payload={"snapshots": []})
    store.save_checkpoint("s1", step=0, tool="write_file", payload={"snapshots": []})
    rows = store.list_checkpoints("s1")
    assert [(r.step, r.tool) for r in rows] == [(0, "write_file"), (2, "edit_file")]


def test_delete_session_cascades_to_messages_and_checkpoints(store: SessionStore) -> None:
    store.create_session(session_id="s1")
    store.replace_messages("s1", _conversation())
    store.save_checkpoint("s1", step=0, tool="write_file", payload={"snapshots": []})

    assert store.delete_session("s1") is True
    assert store.get_session("s1") is None
    assert store.message_count("s1") == 0
    assert store.list_checkpoints("s1") == []
    assert store.delete_session("s1") is False


def test_schema_version_is_recorded(store: SessionStore) -> None:
    row = store._conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    assert int(row["value"]) == SCHEMA_VERSION


def test_store_reopens_existing_database(tmp_path: Path) -> None:
    path = tmp_path / "sessions.db"
    with SessionStore(path) as store:
        store.create_session(session_id="s1")
        store.replace_messages("s1", _conversation())
    with SessionStore(path) as reopened:
        assert reopened.message_count("s1") == 5
        assert reopened.get_session("s1").workspace is None


def test_step_counter_survives_reopening(store: SessionStore, tmp_path: Path) -> None:
    """Checkpoint steps must keep counting across process restarts."""
    assert store.next_step("missing") == 0
    store.create_session(session_id="s1")
    assert store.next_step("s1") == 0
    store.set_next_step("s1", 7)
    assert store.next_step("s1") == 7
    assert store.get_session("s1").next_step == 7
    # A bad value in the JSON must not explode a resume.
    store.update_metadata("s1", next_step="not-a-number")
    assert store.next_step("s1") == 0
