"""Tests for the agent-assembly layer (``loca/agents.py``).

Three of these are regression guards for bugs of the same shape: an entry point
assembled its own loop and forgot a subsystem the others had — the web UI twice
(no checkpoints, then no context management). So the assertions here are less
"does the dataclass hold a string" and more "can an entry point still forget
something without a test going red".
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

import loca
from loca.agents import CODING_AGENT, AgentRuntime, AgentSpec, build_agent
from loca.core.loop import DEFAULT_TOKEN_BUDGET, AgentLoop
from loca.observability import SessionStore
from loca.providers.base import LLMProvider
from loca.providers.types import ChatRequest, ChatResponse, StreamChunk

ROOT = Path(loca.__file__).resolve().parent.parent


class _StubProvider(LLMProvider):
    """Never called: these tests inspect the assembled agent, they don't run it."""

    name = "stub"

    def chat(self, request: ChatRequest) -> ChatResponse:  # pragma: no cover
        raise NotImplementedError

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamChunk]:
        raise NotImplementedError  # pragma: no cover - never called


@pytest.fixture(autouse=True)
def _isolated_session_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every default path inside tmp_path.

    ``build_agent`` can create a trace recorder, and the recorder derives its
    JSONL directory from the session database location. Without this the suite
    would write into the developer's real ``~/.loca``.
    """
    monkeypatch.setenv("LOCA_DB", str(tmp_path / "agents-sessions.db"))


def _store(tmp_path: Path, session_id: str = "s1") -> SessionStore:
    store = SessionStore(tmp_path / "agents-sessions.db")
    store.ensure_session(session_id, workspace=tmp_path, provider="stub")
    return store


def _build(tmp_path: Path, **overrides) -> AgentRuntime:
    store = overrides.pop("store", None)
    return build_agent(
        CODING_AGENT,
        provider=_StubProvider(),
        workspace=tmp_path,
        session_id="s1",
        store=store,
        **overrides,
    )


# ---- the spec ---------------------------------------------------------------


def test_coding_agent_is_a_complete_definition() -> None:
    assert CODING_AGENT.name == "coding"
    assert CODING_AGENT.tool_names == ("read_file", "write_file", "edit_file", "shell")
    assert CODING_AGENT.max_steps == 20
    assert CODING_AGENT.token_budget == DEFAULT_TOKEN_BUDGET
    assert CODING_AGENT.track_files is True
    # The Windows/cmd.exe instructions are policy. They live here now, not in
    # the harness's fallback prompt.
    assert "cmd.exe" in CODING_AGENT.system_prompt


def test_loop_fallback_prompt_is_neutral() -> None:
    """The harness must not carry a coding policy as its default."""
    fallback = AgentLoop.DEFAULT_SYSTEM_PROMPT
    assert fallback != CODING_AGENT.system_prompt
    assert "Windows" not in fallback
    assert "cmd.exe" not in fallback


def test_core_does_not_import_observability_at_runtime() -> None:
    """``core`` may name ``CheckpointManager`` in a type hint, not import it.

    A subprocess, because in-process the module is already in ``sys.modules``
    from some earlier test and the check would be meaningless.
    """
    code = (
        "import sys; import loca.core.loop; "
        "assert 'loca.observability' not in sys.modules, 'core pulled in observability'"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr


def test_resolved_tools_follows_the_spec_order() -> None:
    spec = replace(CODING_AGENT, tool_names=("shell", "read_file"))
    assert [tool.name for tool in spec.resolved_tools()] == ["shell", "read_file"]


def test_unknown_tool_name_names_the_typo_and_what_is_registered() -> None:
    spec = replace(CODING_AGENT, tool_names=("read_flie",))
    with pytest.raises(ValueError) as excinfo:
        spec.resolved_tools()
    message = str(excinfo.value)
    assert "read_flie" in message
    assert "read_file" in message  # what *is* available


def test_a_spec_without_names_takes_whatever_is_registered() -> None:
    spec = AgentSpec(name="bare", system_prompt="hi")
    assert [tool.name for tool in spec.resolved_tools()]
    assert spec.tool_names == ()


# ---- the assembly -----------------------------------------------------------


def test_build_agent_wires_every_subsystem(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        runtime = _build(tmp_path, store=store)

    loop = runtime.loop
    assert runtime.spec is CODING_AGENT
    assert loop.system_prompt == CODING_AGENT.system_prompt
    assert [tool.name for tool in loop.tools] == list(CODING_AGENT.tool_names)
    assert loop.checkpoint_manager is not None
    assert loop.context_manager is not None
    assert loop.context_manager.budget == DEFAULT_TOKEN_BUDGET
    # One policy: the manager owns the budget, the loop's own trim path is off.
    assert loop.context_token_budget is None


def test_build_agent_resumes_the_session_step_counter(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        args = {
            "provider": _StubProvider(),
            "workspace": tmp_path,
            "session_id": "s1",
            "store": store,
        }
        first = build_agent(CODING_AGENT, **args)
        assert first.ctx.step_index == 0

        store.set_next_step("s1", 9)
        second = build_agent(CODING_AGENT, **args)
        assert second.ctx.step_index == 9


def test_without_a_store_there_are_no_checkpoints_but_context_is_managed(
    tmp_path: Path,
) -> None:
    """Both halves matter: no store means no snapshot to write, but budgeting
    does not need one — and the web entry point ran without either for a while.
    """
    runtime = _build(tmp_path)
    assert runtime.loop.checkpoint_manager is None
    assert runtime.loop.context_manager is not None


def test_zero_budget_turns_off_trimming_as_well_as_summarizing(tmp_path: Path) -> None:
    runtime = _build(tmp_path, token_budget=0)
    assert runtime.loop.context_manager is None
    assert runtime.loop.context_token_budget is None


def test_explicit_tool_list_overrides_the_spec(tmp_path: Path) -> None:
    runtime = _build(tmp_path, tools=[])
    assert runtime.loop.tools == []
    # Nothing to snapshot and nothing to write: a tool-less run takes no
    # checkpoints even when a store is available.
    with _store(tmp_path) as store:
        assert _build(tmp_path, store=store, tools=[]).loop.checkpoint_manager is None


def test_track_files_false_is_honoured(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        runtime = _build(tmp_path, store=store, track_files=False)
    assert runtime.loop.checkpoint_manager is None


def test_trace_requests_a_recorder(tmp_path: Path) -> None:
    assert _build(tmp_path, trace=False).recorder is None
    runtime = _build(tmp_path, trace=True)
    assert runtime.recorder is not None
    assert runtime.recorder.session_id == "s1"


def test_system_prompt_override_wins(tmp_path: Path) -> None:
    runtime = _build(tmp_path, system_prompt="just this")
    assert runtime.loop.system_prompt == "just this"


# ---- the guard --------------------------------------------------------------

_ENTRY_POINTS = ("loca/cli.py", "loca/eval/benchmark.py", "web/server.py")


@pytest.mark.parametrize("relative", _ENTRY_POINTS)
def test_entry_points_assemble_through_the_builder(relative: str) -> None:
    """No entry point may construct ``AgentLoop`` itself.

    A source check, deliberately. The failure this guards against is
    *structural* — "this call site forgot one of eight keyword arguments" — and
    it is invisible at runtime until a user notices a missing feature. Two
    rounds of that was enough: the loop is built in ``loca/agents.py`` or not
    at all.
    """
    source = (ROOT / relative).read_text(encoding="utf-8")
    assert not re.search(r"=\s*AgentLoop\(", source), (
        f"{relative} builds an AgentLoop directly; assemble it with "
        "loca.agents.build_agent instead"
    )
    assert "build_agent(" in source, f"{relative} does not go through build_agent"
