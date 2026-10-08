"""Offline tests for the ``loca`` command line.

The REPL rendering is exercised through ``run_turn`` with a scripted provider
and a StringIO console, so nothing here needs a terminal or a network.
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from loca.cli import build_parser, main, resolve_workspace, run_turn
from loca.core.context import ContextManager
from loca.core.loop import AgentLoop
from loca.providers.base import LLMProvider
from loca.providers.types import (
    ChatRequest,
    ChatResponse,
    FinishReason,
    StreamChunk,
    ToolCall,
)
from loca.tools.base import Tool, ToolContext, ToolResult


class ScriptedProvider(LLMProvider):
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


class _EchoTool(Tool):
    name = "echo"
    description = "Echo the text argument back."
    input_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    }

    def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult(content=f"echo: {arguments['text']}")


def _console() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, force_terminal=False, width=120, highlight=False), buf


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace=tmp_path, session_id="cli-test", step_index=0)


def test_run_turn_streams_text_and_tool_cards(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        [
            [
                StreamChunk(
                    delta_tool_calls=[
                        ToolCall(id="c1", name="echo", arguments={"text": "hi"})
                    ],
                    finish_reason=FinishReason.TOOL_USE,
                )
            ],
            [StreamChunk(delta_content="All done.", finish_reason=FinishReason.STOP)],
        ]
    )
    loop = AgentLoop(provider=provider, tools=[_EchoTool()], system_prompt="sys")
    console, buf = _console()

    answer = run_turn(loop, _ctx(tmp_path), "please echo", console)

    out = buf.getvalue()
    assert answer == "All done."
    assert "echo(text='hi')" in out
    assert "echo: hi" in out
    assert "steps 2" in out


def test_run_turn_renders_errors_without_raising(tmp_path: Path) -> None:
    provider = ScriptedProvider([[ValueError("bad key")]])
    loop = AgentLoop(provider=provider, tools=[], system_prompt="sys", retries=0)
    console, buf = _console()

    answer = run_turn(loop, _ctx(tmp_path), "hi", console)

    assert answer == ""
    assert "error:" in buf.getvalue()
    assert "bad key" in buf.getvalue()


def test_run_turn_reports_context_trim(tmp_path: Path) -> None:
    from loca.providers.types import Message, Role

    history = [
        Message(role=Role.USER, content="old question " * 40),
        Message(role=Role.ASSISTANT, content="old answer " * 40),
        Message(role=Role.USER, content="middle"),
        Message(role=Role.ASSISTANT, content="reply"),
    ]
    provider = ScriptedProvider(
        [[StreamChunk(delta_content="ok", finish_reason=FinishReason.STOP)]]
    )
    loop = AgentLoop(
        provider=provider,
        tools=[],
        system_prompt="sys",
        context_token_budget=8,
        keep_recent_messages=1,
        retries=0,
    )
    console, buf = _console()

    run_turn(loop, _ctx(tmp_path), "next", console, history=history)

    assert "context trimmed" in buf.getvalue()


def test_repl_is_multi_turn_via_loop_transcript(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        [
            [StreamChunk(delta_content="first", finish_reason=FinishReason.STOP)],
            [StreamChunk(delta_content="second", finish_reason=FinishReason.STOP)],
        ]
    )
    loop = AgentLoop(provider=provider, tools=[], system_prompt="sys")
    ctx = _ctx(tmp_path)
    console, _ = _console()

    run_turn(loop, ctx, "one", console)
    run_turn(loop, ctx, "two", console, history=list(loop.last_transcript))

    # The second call must have replayed the first exchange.
    contents = [m.content for m in provider.requests[1].messages]
    assert contents == ["sys", "one", "first", "two"]


def test_tools_subcommand_lists_four_tools(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["tools"]) == 0
    out = capsys.readouterr().out
    for name in ("read_file", "write_file", "edit_file", "shell"):
        assert name in out


def test_providers_subcommand_reports_status(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["providers"]) == 0
    out = capsys.readouterr().out
    assert "deepseek" in out
    assert "default:" in out


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "chat" in capsys.readouterr().out


_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

_KEY_IN_ENV = (
    _ENV_FILE.exists() and "LOCA_DEEPSEEK_API_KEY=sk" in _ENV_FILE.read_text(encoding="utf-8")
)


@pytest.mark.live
@pytest.mark.skipif(not _KEY_IN_ENV, reason="needs a local .env with a DeepSeek key")
def test_providers_command_loads_dotenv(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Regression: ``loca providers`` reported 'no key' because it never
    loaded .env (the registry only reads os.environ)."""
    monkeypatch.delenv("LOCA_DEEPSEEK_API_KEY", raising=False)
    assert main(["providers"]) == 0
    out = capsys.readouterr().out
    assert "✓ deepseek" in out
    assert "key set" in out


def test_parser_defaults() -> None:
    args = build_parser().parse_args(["chat"])
    assert args.max_steps == 20
    assert args.no_tools is False
    assert args.token_budget > 0

    args = build_parser().parse_args(["chat", "--no-tools", "--max-steps", "3"])
    assert args.no_tools is True
    assert args.max_steps == 3


def test_chat_with_unusable_provider_is_a_clean_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A provider that cannot be constructed must exit(1), not raise or hang."""
    assert main(["chat", "--provider", "anthropic"]) == 1
    assert "cannot start provider" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Week 4: sessions, rollback, REPL commands
# ---------------------------------------------------------------------------


def test_parser_week4_defaults() -> None:
    args = build_parser().parse_args(["chat"])
    assert args.session is None
    assert args.db is None
    assert args.no_save is False
    assert args.summarize is True
    assert args.keep_recent == 6

    args = build_parser().parse_args(["chat", "--no-summarize", "--no-save", "--session", "x"])
    assert args.summarize is False
    assert args.no_save is True
    assert args.session == "x"


def _seed_session(db: Path, workspace: Path, session_id: str = "s1") -> None:
    from loca.observability import SessionStore
    from loca.providers.types import Message, Role

    with SessionStore(db) as store:
        store.create_session(session_id, workspace=workspace, provider="deepseek")
        store.replace_messages(
            session_id,
            [
                Message(role=Role.SYSTEM, content="sys"),
                Message(role=Role.USER, content="write hello.py"),
                Message(role=Role.ASSISTANT, content="done"),
            ],
        )
        store.set_title(session_id, "write hello.py")


def test_sessions_list_is_empty_for_a_fresh_db(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["sessions", "--db", str(tmp_path / "s.db")]) == 0
    assert "no sessions yet" in capsys.readouterr().out


def test_sessions_list_shows_title_and_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db, workspace = tmp_path / "s.db", tmp_path / "ws"
    workspace.mkdir()
    _seed_session(db, workspace)

    assert main(["sessions", "--db", str(db)]) == 0

    out = capsys.readouterr().out
    assert "s1" in out
    assert "write hello.py" in out
    assert "3" in out  # message count


def test_sessions_show_prints_the_transcript(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db, workspace = tmp_path / "s.db", tmp_path / "ws"
    workspace.mkdir()
    _seed_session(db, workspace)

    assert main(["sessions", "show", "s1", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "user" in out and "write hello.py" in out
    assert "assistant" in out
    assert "workspace" in out


def test_sessions_show_missing_session_fails_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["sessions", "show", "nope", "--db", str(tmp_path / "s.db")]) == 1
    assert "no such session" in capsys.readouterr().out


def test_sessions_rm_deletes_the_session(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db, workspace = tmp_path / "s.db", tmp_path / "ws"
    workspace.mkdir()
    _seed_session(db, workspace)

    assert main(["sessions", "rm", "s1", "--db", str(db)]) == 0
    assert "deleted s1" in capsys.readouterr().out

    from loca.observability import SessionStore

    with SessionStore(db) as store:
        assert store.get_session("s1") is None


def test_sessions_rm_reports_the_counts_it_really_removed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The checkpoint count was read *after* the cascade, so it always said 0."""
    from loca.observability import CheckpointManager, SessionStore

    db, workspace = tmp_path / "s.db", tmp_path / "ws"
    workspace.mkdir()
    _seed_session(db, workspace)
    with SessionStore(db) as store:
        CheckpointManager(store).capture(
            session_id="s1",
            step=0,
            tool="write_file",
            arguments={"path": "a.py", "content": "x"},
            workspace=workspace,
        )

    assert main(["sessions", "rm", "s1", "--db", str(db)]) == 0

    assert "1 checkpoint(s) removed" in capsys.readouterr().out


def test_sessions_rm_also_removes_the_jsonl_trace_mirror(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Otherwise ``loca report`` reads a session the CLI said it had deleted."""
    from loca.observability.trace import trace_jsonl_path

    db, workspace = tmp_path / "s.db", tmp_path / "ws"
    workspace.mkdir()
    _seed_session(db, workspace)
    mirror = trace_jsonl_path("s1", db_path=db)
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text('{"session_id": "s1", "step": 0}\n', encoding="utf-8")

    assert main(["sessions", "rm", "s1", "--db", str(db)]) == 0

    assert not mirror.exists()
    assert "jsonl mirror removed" in capsys.readouterr().out


def test_rollback_restores_files_from_a_checkpoint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from loca.observability import CheckpointManager, SessionStore

    db, workspace = tmp_path / "s.db", tmp_path / "ws"
    workspace.mkdir()
    target = workspace / "greet.py"
    target.write_text("print('before')\n", encoding="utf-8")

    with SessionStore(db) as store:
        store.create_session("s1", workspace=workspace)
        CheckpointManager(store).capture(
            session_id="s1",
            step=0,
            tool="write_file",
            arguments={"path": "greet.py", "content": "print('after')"},
            workspace=workspace,
        )
    target.write_text("print('after')\n", encoding="utf-8")

    assert main(["rollback", "s1", "0", "--db", str(db)]) == 0

    out = capsys.readouterr().out
    assert "restored greet.py" in out
    assert "1 checkpoint(s) applied" in out
    assert "1 file(s) affected" in out
    assert target.read_text(encoding="utf-8") == "print('before')\n"


def test_rollback_without_checkpoints_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db, workspace = tmp_path / "s.db", tmp_path / "ws"
    workspace.mkdir()
    _seed_session(db, workspace)

    assert main(["rollback", "s1", "0", "--db", str(db)]) == 0
    assert "nothing to undo" in capsys.readouterr().out


def test_rollback_of_missing_session_fails_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["rollback", "nope", "0", "--db", str(tmp_path / "s.db")]) == 1
    assert "no such session" in capsys.readouterr().out


def test_repl_help_and_unknown_commands(tmp_path: Path) -> None:
    from loca.cli import _handle_repl_command

    console, buf = _console()

    assert _handle_repl_command("/help", console) is True
    assert "/compact" in buf.getvalue()
    assert "/rollback" in buf.getvalue()
    assert _handle_repl_command("/nope", console) is True
    assert "unknown command" in buf.getvalue()


def _store_with_one_edit(tmp_path: Path) -> tuple[Path, Any]:
    """A session whose one checkpoint saw ``greet.py`` before a rewrite."""
    from loca.observability import CheckpointManager, SessionStore

    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / "greet.py"
    target.write_text("print('before')\n", encoding="utf-8")

    store = SessionStore(tmp_path / "s.db")
    store.create_session("s1", workspace=workspace)
    CheckpointManager(store).capture(
        session_id="s1",
        step=3,
        tool="write_file",
        arguments={"path": "greet.py", "content": "print('after')"},
        workspace=workspace,
    )
    target.write_text("print('after')\n", encoding="utf-8")
    return workspace, store


def test_repl_rollback_undoes_the_last_file_edit(tmp_path: Path) -> None:
    """Bare ``/rollback`` means "undo what you just did".

    The command is the whole point of the REPL branch: the previous way to undo
    was to leave the session, read a step number off `loca sessions show`, and
    run `loca rollback` in a second process.
    """
    from loca.cli import _handle_repl_command

    workspace, store = _store_with_one_edit(tmp_path)
    try:
        console, buf = _console()
        handled = _handle_repl_command(
            "/rollback", console, store=store, session_id="s1", workspace=workspace
        )

        assert handled is True
        out = buf.getvalue()
        assert "restored greet.py" in out
        assert "1 checkpoint(s) applied" in out
        assert "shell tool cannot be rolled back" in out
        assert (workspace / "greet.py").read_text(encoding="utf-8") == "print('before')\n"
    finally:
        store.close()


def test_repl_rollback_takes_an_explicit_step(tmp_path: Path) -> None:
    from loca.cli import _handle_repl_command

    workspace, store = _store_with_one_edit(tmp_path)
    try:
        console, buf = _console()
        _handle_repl_command(
            "/rollback 2", console, store=store, session_id="s1", workspace=workspace
        )

        # Step 3 is at or after step 2, so it is undone too.
        assert "restored greet.py" in buf.getvalue()
        assert (workspace / "greet.py").read_text(encoding="utf-8") == "print('before')\n"
    finally:
        store.close()


def test_repl_rollback_out_of_range_says_so(tmp_path: Path) -> None:
    from loca.cli import _handle_repl_command

    workspace, store = _store_with_one_edit(tmp_path)
    try:
        console, buf = _console()
        handled = _handle_repl_command(
            "/rollback 99", console, store=store, session_id="s1", workspace=workspace
        )

        assert handled is True
        assert "nothing to undo at step 99 or later" in buf.getvalue()
        # Nothing was touched.
        assert (workspace / "greet.py").read_text(encoding="utf-8") == "print('after')\n"
    finally:
        store.close()


def test_repl_rollback_rejects_a_non_number(tmp_path: Path) -> None:
    from loca.cli import _handle_repl_command

    workspace, store = _store_with_one_edit(tmp_path)
    try:
        console, buf = _console()
        handled = _handle_repl_command(
            "/rollback soon", console, store=store, session_id="s1", workspace=workspace
        )

        assert handled is True
        assert "not a step number" in buf.getvalue()
        assert (workspace / "greet.py").read_text(encoding="utf-8") == "print('after')\n"
    finally:
        store.close()


def test_repl_rollback_without_a_session_says_so(tmp_path: Path) -> None:
    """``--no-save`` means no store, so there is no undo history either."""
    from loca.cli import _handle_repl_command

    console, buf = _console()
    handled = _handle_repl_command("/rollback", console)

    assert handled is True
    assert "no session" in buf.getvalue()


def test_repl_compact_command(tmp_path: Path) -> None:
    from loca.cli import _handle_repl_command

    context_manager = ContextManager(
        budget=10_000, keep_recent=1, summarizer=lambda msgs: "rolled up"
    )
    provider = ScriptedProvider(
        [
            [StreamChunk(delta_content="one", finish_reason=FinishReason.STOP)],
            [StreamChunk(delta_content="two", finish_reason=FinishReason.STOP)],
        ]
    )
    loop = AgentLoop(provider=provider, tools=[], system_prompt="sys", retries=0)
    loop.context_manager = context_manager
    ctx = _ctx(tmp_path)
    console, _ = _console()

    run_turn(loop, ctx, "first question " * 5, console)
    run_turn(loop, ctx, "second question " * 5, console, history=list(loop.last_transcript))
    before = len(loop.last_transcript)

    handled = _handle_repl_command("/compact", console, loop=loop)

    assert handled is True
    assert len(loop.last_transcript) < before


def test_repl_compact_reports_when_nothing_to_do(tmp_path: Path) -> None:
    from loca.cli import _handle_repl_command

    provider = ScriptedProvider(
        [[StreamChunk(delta_content="x", finish_reason=FinishReason.STOP)]]
    )
    loop = AgentLoop(
        provider=provider,
        tools=[],
        system_prompt="sys",
    )
    console, buf = _console()

    _handle_repl_command("/compact", console, loop=loop)

    assert "context management is off" in buf.getvalue()


def test_repl_session_command_without_persistence() -> None:
    from loca.cli import _handle_repl_command

    console, buf = _console()
    _handle_repl_command("/session", console)
    assert "no session" in buf.getvalue()


# ---------------------------------------------------------------------------
# live: resume across two separate CLI launches (the Week 4 acceptance test)
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.skipif(not _KEY_IN_ENV, reason="needs a local .env with a DeepSeek key")
def test_session_survives_a_restart(tmp_path: Path) -> None:
    """Start a session, remember a fact, then resume in a *new* process."""
    import subprocess
    import sys

    db = tmp_path / "sessions.db"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    session_id = "resume-e2e"
    env = {**os.environ, "LOCA_DB": str(db)}

    def run_turn_via_cli(prompt: str) -> str:
        script = f"{prompt}\nexit\n"
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "loca.cli",
                "chat",
                "--session",
                session_id,
                "--workspace",
                str(workspace),
                "--db",
                str(db),
            ],
            input=script,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            cwd=str(Path(__file__).resolve().parent.parent),
            env=env,
        )
        return proc.stdout + proc.stderr

    first = run_turn_via_cli(
        "Remember this number for later: 4711. Reply with just 'ok'."
    )
    assert "4711" in first or "ok" in first.lower()

    second = run_turn_via_cli(
        "What was the number I asked you to remember? Reply with digits only."
    )
    assert "4711" in second, second[-2000:]

    from loca.observability import SessionStore

    with SessionStore(db) as store:
        info = store.get_session(session_id)
        assert info is not None
        assert info.message_count > 3



# ---------------------------------------------------------------------------
# workspace paths are Windows paths
# ---------------------------------------------------------------------------


def test_resolve_workspace_accepts_a_windows_path(tmp_path: Path) -> None:
    resolved = resolve_workspace(str(tmp_path))
    assert resolved == tmp_path.resolve()


def test_resolve_workspace_rejects_git_bash_style_path() -> None:
    r"""``/d/repo`` would silently become ``D:\d\repo`` under ntpath — refuse it."""
    with pytest.raises(ValueError) as excinfo:
        resolve_workspace("/d/repo")
    message = str(excinfo.value)
    assert "Git-Bash" in message
    assert "D:\\repo" in message


def test_resolve_workspace_rejects_bare_drive_prefix() -> None:
    with pytest.raises(ValueError):
        resolve_workspace("/c")


def test_resolve_workspace_allows_a_posix_looking_relative_name() -> None:
    """Only a drive-letter prefix is suspicious; `/dev/null` is a plain name."""
    resolved = resolve_workspace("dev/null")
    assert resolved.name == "null"
