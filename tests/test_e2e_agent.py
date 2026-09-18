"""End-to-end test: real DeepSeek call that uses a real tool through the
streaming AgentLoop.

Skipped unless ``LOCA_DEEPSEEK_API_KEY`` is set. Asks DeepSeek to read a
file via the ``read_file`` tool and verifies the agent's reply contains the
expected text.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from loca.core.events import EventType
from loca.core.loop import AgentLoop
from loca.providers.registry import get_provider
from loca.tools import register_default_tools
from loca.tools.base import ToolContext

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("LOCA_DEEPSEEK_API_KEY"),
        reason="LOCA_DEEPSEEK_API_KEY not set; skipping live agent e2e",
    ),
]


def test_deepseek_uses_read_file_through_loop(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("loca-rocks-2026", encoding="utf-8")
    ctx = ToolContext(workspace=tmp_path, session_id="e2e", step_index=0)

    register_default_tools()
    provider = get_provider("deepseek")
    loop = AgentLoop(provider=provider, max_steps=5)

    events = list(
        loop.run(
            ctx,
            user_message=(
                "Use the read_file tool to read secret.txt and tell me its "
                "contents in one short sentence."
            ),
        )
    )

    types = [e.type for e in events]
    assert EventType.DONE in types, "loop should reach DONE"
    assert EventType.TOOL_CALL in types, "model should call a tool"
    assert EventType.TOOL_RESULT in types

    tool_calls = [e for e in events if e.type == EventType.TOOL_CALL]
    tool_results = [e for e in events if e.type == EventType.TOOL_RESULT]
    called_read_file = [c for c in tool_calls if c.data["name"] == "read_file"]
    assert called_read_file, f"expected read_file call, got {[c.data['name'] for c in tool_calls]}"

    read_results = [r for r in tool_results if r.data["name"] == "read_file"]
    assert read_results
    assert not read_results[0].data["is_error"]
    assert "loca-rocks-2026" in read_results[0].data["content"]

    # Final reply should contain the secret.
    text = "".join(
        e.data["content"] for e in events if e.type == EventType.TEXT_DELTA
    )
    assert "loca-rocks-2026" in text


def test_deepseek_uses_shell_through_loop(tmp_path: Path) -> None:
    """Week-2 acceptance: DeepSeek calls ``shell`` and sees ``echo hello``."""
    ctx = ToolContext(workspace=tmp_path, session_id="e2e-shell", step_index=0)

    register_default_tools()
    provider = get_provider("deepseek")
    loop = AgentLoop(provider=provider, max_steps=5)

    events = list(
        loop.run(
            ctx,
            user_message=(
                'Use the shell tool to run: echo hello. Then quote the exact '
                'command output in your reply.'
            ),
        )
    )

    types = [e.type for e in events]
    assert EventType.DONE in types, "loop should reach DONE"

    tool_calls = [e for e in events if e.type == EventType.TOOL_CALL]
    shell_calls = [c for c in tool_calls if c.data["name"] == "shell"]
    assert shell_calls, f"expected shell call, got {[c.data['name'] for c in tool_calls]}"
    # The assembled arguments must actually carry the command (regression:
    # the stream assembler used to flush calls before argument fragments
    # arrived, so every call reached the loop as ``{}``).
    assert "echo" in shell_calls[0].data["arguments"].get("command", "")

    shell_results = [
        r for r in events if r.type == EventType.TOOL_RESULT and r.data["name"] == "shell"
    ]
    assert shell_results
    assert not shell_results[0].data["is_error"]
    assert "hello" in shell_results[0].data["content"]
    assert "exit_code=0" in shell_results[0].data["content"]

    # Final reply should reflect the command output.
    text = "".join(
        e.data["content"] for e in events if e.type == EventType.TEXT_DELTA
    )
    assert "hello" in text.lower()


def test_deepseek_writes_and_runs_a_script(tmp_path: Path) -> None:
    """Week-3 acceptance: a real multi-step task.

    The model has to (1) author a file with ``write_file`` and (2) execute it
    with ``shell``. Step two only makes sense if step one actually landed on
    disk, so this exercises the whole tool loop rather than a single call.
    """
    ctx = ToolContext(workspace=tmp_path, session_id="e2e-script", step_index=0)

    register_default_tools()
    provider = get_provider("deepseek")
    loop = AgentLoop(provider=provider, max_steps=6)

    events = list(
        loop.run(
            ctx,
            user_message=(
                "Do these two steps in order. "
                "1) Use the write_file tool to create a file named greet.py "
                "whose contents are exactly: print('loca-week3')  "
                "2) Use the shell tool to run: python greet.py  "
                "Then quote the exact stdout in one short sentence."
            ),
        )
    )

    done = [e for e in events if e.type == EventType.DONE]
    assert done, "loop should reach DONE"
    assert done[-1].data["reason"] != "max_steps", "task needs more steps than allowed"
    assert done[-1].data["steps"] >= 3, "expected write -> run -> answer"

    tool_calls = [e for e in events if e.type == EventType.TOOL_CALL]
    names = [c.data["name"] for c in tool_calls]
    assert "write_file" in names, f"expected a write_file call, got {names}"
    assert "shell" in names, f"expected a shell call, got {names}"

    # Step 1 really wrote the file the model claimed to write.
    script = tmp_path / "greet.py"
    assert script.exists(), "write_file did not create greet.py"
    assert "loca-week3" in script.read_text(encoding="utf-8")

    write_results = [
        r
        for r in events
        if r.type == EventType.TOOL_RESULT and r.data["name"] == "write_file"
    ]
    assert write_results and not write_results[0].data["is_error"]

    # Step 2 executed it, cwd defaulting to the workspace.
    shell_calls = [c for c in tool_calls if c.data["name"] == "shell"]
    command = shell_calls[-1].data["arguments"].get("command", "")
    assert "greet.py" in command, f"shell should run the script, got {command!r}"

    shell_results = [
        r for r in events if r.type == EventType.TOOL_RESULT and r.data["name"] == "shell"
    ]
    assert shell_results, "shell produced no result"
    assert not shell_results[-1].data["is_error"], shell_results[-1].data["content"]
    assert "loca-week3" in shell_results[-1].data["content"]
    assert "exit_code=0" in shell_results[-1].data["content"]

    text = "".join(e.data["content"] for e in events if e.type == EventType.TEXT_DELTA)
    assert "loca-week3" in text
