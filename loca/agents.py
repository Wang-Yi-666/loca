"""Named agent definitions — the composition layer the harness was missing.

``loca.core`` is a *harness*: it knows how to drive a tool-calling loop, and
nothing about who is driving. For a long time "who" was not written down
anywhere either. It lived implicitly in the same eight keyword arguments,
repeated at three call sites (``loca.cli``, ``loca.eval.benchmark``,
``web.server``), each of which had to remember the same optional subsystems.

They did not remember. The web GUI shipped without a ``CheckpointManager`` (so
its undo button had nothing to attach to), and then without a
``ContextManager`` (so a long browser conversation dropped its oldest turns
instead of summarizing them). Two bugs, one shape: a wiring decision that
existed in three places at once.

So the wiring lives here instead. :class:`AgentSpec` says *what* an agent is —
its prompt, its tools, its limits — and :func:`build_agent` turns a spec plus
a runtime half (provider, workspace, session, store) into a
:class:`AgentRuntime`. Every entry point in this project goes through it, and
``tests/test_agents.py`` fails if one of them stops doing so.

The direction of the dependencies is the point: this module may import
``core``, ``providers``, ``tools`` and ``observability``; none of them may
import this one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loca.core.context import ContextManager, provider_summarizer
from loca.core.loop import DEFAULT_TOKEN_BUDGET, AgentLoop
from loca.observability.checkpoint import CheckpointManager
from loca.providers.base import LLMProvider
from loca.tools.base import Tool, ToolContext
from loca.tools.registry import all_tools

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pathlib import Path

    from loca.observability.storage import SessionStore
    from loca.observability.trace import TraceRecorder

#: Messages kept verbatim when the context is compacted. Mirrored by the CLI's
#: ``--keep-recent`` default.
DEFAULT_KEEP_RECENT = 6


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """What distinguishes one agent from another.

    A spec is data, not behaviour. It names a prompt, a toolset and a set of
    limits; :func:`build_agent` is the only thing that knows how to turn that
    into a running loop, which is what keeps the answer to "which agent is
    this?" in exactly one place.
    """

    #: Short identifier. Shows up in error messages.
    name: str
    #: The system prompt. This is *policy* — the prompt a coding agent needs
    #: says "Windows", "cmd.exe" and "use dir instead of ls", none of which a
    #: harness has any business asserting. ``AgentLoop.DEFAULT_SYSTEM_PROMPT``
    #: is the neutral fallback for a loop built without a spec.
    system_prompt: str
    #: Tools this agent may call, by registry name and in this order. A name
    #: that is not registered raises at build time, rather than handing the
    #: model a smaller toolset than the author intended — that is the same
    #: class of silent failure this module exists to prevent.
    tool_names: tuple[str, ...] = ()
    max_steps: int = 20
    #: Estimated token ceiling per request. ``None`` or ``0`` disables context
    #: management entirely: no trimming and no summarizing.
    token_budget: int | None = DEFAULT_TOKEN_BUDGET
    #: Messages kept verbatim when the context is compacted.
    keep_recent: int = DEFAULT_KEEP_RECENT
    #: Snapshot a file before a write tool touches it, so the edit can be
    #: rolled back. Needs a session store — see :func:`build_agent`.
    track_files: bool = True

    def resolved_tools(self) -> list[Tool]:
        """The tool objects this spec names, in the order it names them.

        An empty ``tool_names`` means "whatever is registered" — that is the
        historical behaviour, and it is what a caller that wants to inject its
        own toolset relies on.
        """
        if not self.tool_names:
            return list(all_tools())

        by_name = {tool.name: tool for tool in all_tools()}
        missing = [name for name in self.tool_names if name not in by_name]
        if missing:
            # The registry is only populated by an explicit call, and the
            # spec is meant to be usable without one: registering on demand
            # keeps "which tools" a property of the agent rather than of the
            # import order of its entry point.
            from loca.tools import register_default_tools

            register_default_tools()
            by_name = {tool.name: tool for tool in all_tools()}
            missing = [name for name in self.tool_names if name not in by_name]
        if missing:
            known = ", ".join(sorted(by_name)) or "none"
            raise ValueError(
                f"agent {self.name!r} asks for tool(s) that are not registered: "
                f"{', '.join(missing)} (registered: {known})"
            )
        return [by_name[name] for name in self.tool_names]


#: The agent this project actually ships. ``loca chat``, ``loca bench`` and the
#: web UI all run *this* one; ``loca.eval`` measures it, not the harness in the
#: abstract.
CODING_AGENT = AgentSpec(
    name="coding",
    system_prompt=(
        "You are loca, a coding assistant running on Windows. You have access "
        "to filesystem and shell tools. Use them to answer the user's request. "
        "All paths are Windows paths (e.g. D:\\Projects\\repo). The shell is "
        "cmd.exe, so use Windows commands (dir, type, del, findstr) rather "
        "than POSIX ones (ls, cat, rm, grep). Be concise."
    ),
    tool_names=("read_file", "write_file", "edit_file", "shell"),
)


@dataclass(slots=True)
class AgentRuntime:
    """A built agent: the loop, the context it runs in, its trace sink.

    Returned as one object rather than a tuple so a fourth subsystem can be
    added without every call site learning a new unpacking order.
    """

    spec: AgentSpec
    loop: AgentLoop
    ctx: ToolContext
    recorder: TraceRecorder | None = None


def build_agent(
    spec: AgentSpec = CODING_AGENT,
    *,
    provider: LLMProvider,
    workspace: Path,
    session_id: str,
    store: SessionStore | None = None,
    step_index: int | None = None,
    tools: Sequence[Tool] | None = None,
    system_prompt: str | None = None,
    max_steps: int | None = None,
    token_budget: int | None = None,
    keep_recent: int | None = None,
    summarize: bool = True,
    track_files: bool | None = None,
    model: str | None = None,
    provider_name: str | None = None,
    trace: bool = False,
    retries: int = 2,
) -> AgentRuntime:
    """Assemble one agent. The only place that knows how the pieces fit.

    Everything optional defaults to the spec; a keyword argument here is an
    explicit override by an entry point (a ``--flag``, a test, a benchmark run
    that wants a different budget). Anything this function does *not* name is
    a subsystem nobody has to remember.

    Notes on the two injectable subsystems, because both have bitten:

    - **Checkpoints** need a session store — a snapshot with nowhere to live is
      not a snapshot — and a tool-less agent has nothing to snapshot. With
      either missing the manager is left off rather than attached as a no-op
      that merely looks present.
    - **Context budgeting** is owned by a single policy: when a
      :class:`ContextManager` is attached the loop's own trim path is switched
      off, so the two cannot disagree about what to drop. When the budget is
      ``None`` or ``0``, nothing trims at all.
    """
    tool_list = list(tools) if tools is not None else spec.resolved_tools()
    budget = spec.token_budget if token_budget is None else token_budget
    recent = spec.keep_recent if keep_recent is None else keep_recent
    wants_checkpoints = spec.track_files if track_files is None else track_files

    checkpoint_manager = (
        CheckpointManager(store)
        if store is not None and wants_checkpoints and tool_list
        else None
    )

    loop = AgentLoop(
        provider=provider,
        tools=tool_list,
        system_prompt=system_prompt or spec.system_prompt,
        max_steps=spec.max_steps if max_steps is None else max_steps,
        retries=retries,
        # See the docstring: the manager below is the single policy.
        context_token_budget=None,
        checkpoint_manager=checkpoint_manager,
    )

    if budget:
        loop.context_manager = ContextManager(
            budget=budget,
            keep_recent=recent,
            model=model,
            # Summarize with the loop's own provider, so a compaction call gets
            # the same retry policy as everything else.
            summarizer=provider_summarizer(loop.provider, model=model)
            if summarize
            else None,
        )

    if step_index is None:
        # Continue the session's step counter when there is one. Checkpoints
        # are keyed by step, and rollback undoes a step *and everything after
        # it* — restarting at 0 would pile every turn onto step 0 and make
        # "undo just that one turn" impossible.
        step_index = store.next_step(session_id) if store is not None else 0

    ctx = ToolContext(workspace=workspace, session_id=session_id, step_index=step_index)

    recorder: TraceRecorder | None = None
    if trace:
        from loca.observability.trace import TraceRecorder

        recorder = TraceRecorder(
            session_id,
            store=store,
            provider=provider_name or getattr(provider, "name", "") or "",
            model=model,
            prompt_source=lambda: loop.last_transcript,
        )

    return AgentRuntime(spec=spec, loop=loop, ctx=ctx, recorder=recorder)


__all__ = [
    "CODING_AGENT",
    "DEFAULT_KEEP_RECENT",
    "AgentRuntime",
    "AgentSpec",
    "build_agent",
]
