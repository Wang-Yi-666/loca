"""Offline tests for the ``loca`` command line.

The REPL rendering is exercised through ``run_turn`` with a scripted provider
and a StringIO console, so nothing here needs a terminal or a network.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from loca.cli import build_parser, main, run_turn
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
    for name in ("read_file", "write_file", "edit_file", "bash"):
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
