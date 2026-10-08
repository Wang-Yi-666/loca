"""Command-line entry point.

    loca chat          interactive agent REPL (tools enabled)
    loca chat --no-tools
                       plain streaming chat, no tool use
    loca chat --session <id>
                       resume a stored session (or start one with that id)
    loca sessions      list stored sessions
    loca sessions show <id>
                       print a stored transcript
    loca sessions rm <id>
                       delete a session and its checkpoints
    loca rollback <session> <step>
                       undo file edits from <step> onwards
    loca report [<session>]
                       render a session's per-step trace (--verbose, --json)
    loca bench [list|run|verify]
                       list the eval task set / benchmark a provider /
                       check the task set against its reference answers
    loca serve         run the web UI
    loca tools         list the registered tools
    loca providers     show which providers have credentials

The REPL drives the real :class:`~loca.core.loop.AgentLoop`, so tool calls,
retries, context compaction and errors are all visible as they happen. Turns are
persisted to a SQLite session database (``~/.loca/sessions.db`` by default) and
file edits are checkpointed before they happen, which is what makes ``--session``
and ``rollback`` possible.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from loca.core.events import EventType
from loca.core.loop import DEFAULT_TOKEN_BUDGET, AgentLoop
from loca.providers.base import LLMProvider
from loca.tools.base import ToolContext
from loca.workspace import resolve_workspace

_PACKAGE_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _PACKAGE_ROOT.parent


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def load_env() -> None:
    """Load .env from the project root (and the cwd) if python-dotenv is here."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - optional dependency
        return
    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(Path.cwd() / ".env")


def _console() -> Any:
    from rich.console import Console

    return Console()


def _fmt_args(arguments: dict[str, Any], limit: int = 160) -> str:
    rendered = ", ".join(f"{k}={v!r}" for k, v in arguments.items())
    return rendered if len(rendered) <= limit else rendered[: limit - 1] + "…"


def run_turn(
    loop: AgentLoop,
    ctx: ToolContext,
    user_message: str,
    console: Any,
    *,
    history: list[Any] | None = None,
    verbose_tools: bool = True,
    recorder: Any = None,
) -> str:
    """Consume one agent turn, render it, and return the assistant's text.

    Kept as a free function (not buried in the REPL loop) so it can be tested
    with a scripted provider and a StringIO console. ``recorder`` is an optional
    :class:`~loca.observability.trace.TraceRecorder` that observes every event;
    passing ``None`` means no tracing, which is what ``--no-trace`` does.
    """
    text_parts: list[str] = []
    usage: dict[str, int] | None = None
    done: dict[str, Any] | None = None

    for event in loop.run(ctx, user_message=user_message, history=history):
        if recorder is not None:
            recorder.observe(event)
        kind = event.type

        if kind is EventType.TEXT_DELTA:
            text_parts.append(event.data["content"])
            console.print(event.data["content"], end="", highlight=False)

        elif kind is EventType.TOOL_CALL and verbose_tools:
            console.print(
                f"\n[dim]→ {event.data['name']}({_fmt_args(event.data['arguments'])})[/dim]"
            )

        elif kind is EventType.TOOL_RESULT and verbose_tools:
            name = event.data["name"]
            colour = "red" if event.data["is_error"] else "green"
            marker = "✗" if event.data["is_error"] else "✓"
            preview = _first_lines(event.data["content"], 6)
            console.print(f"[{colour}]{marker} {name}[/{colour}]")
            console.print(f"[dim]{preview}[/dim]")

        elif kind is EventType.CONTEXT_TRIMMED:
            console.print(
                f"[yellow]context trimmed: dropped {event.data['dropped']} old "
                f"message(s), ~{event.data['estimated_tokens']}/"
                f"{event.data['budget']} tokens[/yellow]"
            )

        elif kind is EventType.CONTEXT_SUMMARIZED:
            console.print(
                f"[yellow]context compacted: {event.data['summarized']} old "
                f"message(s) → summary (~{event.data['summary_tokens']} tokens), "
                f"now ~{event.data['estimated_tokens']}/{event.data['budget']}[/yellow]"
            )

        elif kind is EventType.CHECKPOINT and verbose_tools:
            files = ", ".join(event.data["files"]) or "(nothing)"
            # Naming the undo command right here is the point: a checkpoint
            # nobody notices is indistinguishable from no checkpoint at all.
            step = event.data["step"]
            console.print(
                f"[dim]⛁ checkpoint @ step {step} · {files} · /rollback {step} to undo[/dim]"
            )

        elif kind is EventType.USAGE:
            usage = event.data

        elif kind is EventType.RECOVERY:
            if event.data.get("reason") == "length":
                console.print(
                    "\n[yellow]output cap reached — asking the model to "
                    "continue[/yellow]"
                )
            else:
                console.print(
                    f"\n[yellow]transient provider failure "
                    f"({event.data.get('reason', 'unknown')}) — retrying[/yellow]"
                )

        elif kind is EventType.ERROR:
            suffix = " (transient, retries exhausted)" if event.data.get("retryable") else ""
            console.print(f"[bold red]error:[/bold red] {event.data['message']}{suffix}")

        elif kind is EventType.DONE:
            done = event.data

    console.print()
    if done is not None:
        bits = [
            f"steps {done['steps']}",
            f"tokens {done['total_tokens']}",
            f"finish {done['reason']}",
        ]
        if usage:
            bits.append(
                f"prompt {usage['prompt_tokens']} · "
                f"completion {usage['completion_tokens']}"
            )
        console.print(f"[dim]{'  ·  '.join(bits)}[/dim]")

    return "".join(text_parts)


def _first_lines(text: str, n: int) -> str:
    lines = text.splitlines()
    if len(lines) <= n:
        return text
    return "\n".join(lines[:n]) + f"\n… (+{len(lines) - n} lines)"


# ---------------------------------------------------------------------------
# subcommands
# ---------------------------------------------------------------------------


def cmd_chat(args: argparse.Namespace) -> int:
    from loca.agents import CODING_AGENT, build_agent
    from loca.observability import SessionStore, new_session_id
    from loca.providers.registry import get_provider

    console = _console()
    load_env()

    try:
        provider: LLMProvider = get_provider(args.provider)
    except Exception as exc:
        console.print(f"[bold red]cannot start provider:[/bold red] {exc}")
        console.print(
            "[dim]Put your key in .env as LOCA_DEEPSEEK_API_KEY and retry.[/dim]"
        )
        return 1

    try:
        workspace = resolve_workspace(args.workspace)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    workspace.mkdir(parents=True, exist_ok=True)

    # ---- session ----------------------------------------------------------
    store: SessionStore | None = None
    session_id = args.session
    history: list[Any] = []
    resumed = False
    if not args.no_save:
        store = SessionStore(args.db)
        session_id = session_id or new_session_id()
        _, created = store.ensure_session(
            session_id,
            workspace=workspace,
            provider=provider.name,
            model=args.model,
        )
        resumed = not created
        if resumed:
            history = store.load_messages(session_id)

    # One call assembles the whole agent — prompt, tools, context policy,
    # checkpoints and the trace sink. See loca/agents.py: assembling it here is
    # what let the web entry point drift without checkpoints, then without
    # context management.
    runtime = build_agent(
        CODING_AGENT,
        provider=provider,
        workspace=workspace,
        session_id=session_id or "cli",
        store=store,
        # An empty list, not `None`: `--no-tools` must mean no tools, not "fall
        # back to whatever the spec names".
        tools=[] if args.no_tools else None,
        system_prompt=args.system,
        max_steps=args.max_steps,
        token_budget=args.token_budget,
        keep_recent=args.keep_recent,
        summarize=args.summarize,
        model=args.model,
        # Tracing needs somewhere to live: a recorder without a store would
        # only ever write the JSONL mirror, which `loca report` never reads.
        trace=bool(args.trace and store is not None),
    )
    loop, ctx, recorder = runtime.loop, runtime.ctx, runtime.recorder

    console.print(
        f"[bold cyan]loca[/bold cyan] · provider [cyan]{provider.name}[/cyan] · "
        f"{len(loop.tools)} tool(s) · workspace [dim]{workspace}[/dim]"
    )
    if store is not None:
        counted = len(history)
        state = f"resumed, {counted} message(s)" if resumed else "new"
        console.print(f"session [cyan]{session_id}[/cyan] ({state}) · db [dim]{store.path}[/dim]")
        if recorder is not None:
            console.print(f"[dim]tracing to {recorder.jsonl_path}[/dim]")
    else:
        console.print("[dim]session persistence off (--no-save)[/dim]")
    console.print("[dim]Type 'exit' to quit · /help for commands.[/dim]")

    try:
        while True:
            try:
                console.print()
                user_input = _ask(console)
            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]bye[/dim]")
                return 0

            text = user_input.strip()
            if not text:
                continue
            if text.lower() in {"exit", "quit", ":q"}:
                console.print("[dim]bye[/dim]")
                return 0
            if text.startswith("/"):
                _handle_repl_command(
                    text,
                    console,
                    loop=loop,
                    store=store,
                    session_id=session_id,
                    # /rollback needs it: snapshots are stored relative to the
                    # workspace they were taken in, so restoring has to resolve
                    # them against the same root.
                    workspace=workspace,
                )
                continue

            console.print("[bold magenta]assistant[/bold magenta] ", end="")
            try:
                # Feed the previous transcript back so the REPL is multi-turn.
                run_turn(
                    loop,
                    ctx,
                    text,
                    console,
                    history=list(loop.last_transcript) or history or None,
                    recorder=recorder,
                )
            except KeyboardInterrupt:
                console.print("\n[yellow](interrupted)[/yellow]")

            # Persist after every turn: the session on disk always reflects what
            # the model actually saw, including any context compaction that
            # happened.
            if store is not None and session_id is not None:
                store.set_next_step(session_id, ctx.step_index)
                if loop.last_transcript:
                    store.save_transcript(session_id, loop.last_transcript)
                    history = list(loop.last_transcript)
    finally:
        # Finalize a step that was still in flight (Ctrl-C mid-stream), so the
        # trace on disk is never silently missing its last entry.
        if recorder is not None:
            recorder.close()
        _close(store)


def _close(store: Any) -> None:
    if store is not None:
        store.close()


def _handle_repl_command(
    text: str,
    console: Any,
    *,
    loop: AgentLoop | None = None,
    store: Any = None,
    session_id: str | None = None,
    workspace: Any = None,
) -> bool:
    """Handle a ``/command`` inside the REPL. Returns ``True`` if recognised."""
    command, _, rest = text.partition(" ")
    command = command.lower()

    if command in {"/help", "/?"}:
        console.print(
            "[dim]/compact[/dim]   summarize earlier turns now\n"
            "[dim]/rollback[/dim]  undo the last file edit (also: /rollback <step>)\n"
            "[dim]/session[/dim]   show the session id, db and message count\n"
            "[dim]/trace[/dim]     show how many steps have been traced so far\n"
            "[dim]/help[/dim]      this message\n"
            "[dim]exit[/dim]       quit (also: quit, :q, Ctrl-C)"
        )
        return True

    if command == "/trace":
        if store is None or session_id is None:
            console.print("[dim]no session (started with --no-save)[/dim]")
        else:
            count = store.count_traces(session_id)
            console.print(
                f"[cyan]{count}[/cyan] step(s) traced · "
                f"read it with [dim]loca report {session_id}[/dim]"
            )
        return True

    if command == "/session":
        if store is None or session_id is None:
            console.print("[dim]no session (started with --no-save)[/dim]")
        else:
            count = len(loop.last_transcript) if loop and loop.last_transcript else 0
            console.print(
                f"[cyan]{session_id}[/cyan] · {count} message(s) in this turn · "
                f"db [dim]{store.path}[/dim]"
            )
        return True

    if command == "/compact":
        if loop is None or loop.context_manager is None:
            console.print("[dim]context management is off (--token-budget 0)[/dim]")
            return True
        if not loop.last_transcript:
            console.print("[dim]nothing to compact yet[/dim]")
            return True
        if loop.compact():
            console.print("[yellow]compacted: earlier turns folded into a summary[/yellow]")
            if store is not None and session_id is not None:
                store.save_transcript(session_id, loop.last_transcript)
        else:
            console.print("[dim]nothing to compact (history is already short)[/dim]")
        return True

    if command == "/rollback":
        from rich.markup import escape as markup_escape

        from loca.observability import CheckpointManager

        if store is None or session_id is None:
            console.print("[dim]no session (started with --no-save) — nothing to undo[/dim]")
            return True

        rows = store.list_checkpoints(session_id)
        if not rows:
            console.print("[dim]no checkpoints yet — no file edit has been snapshotted[/dim]")
            return True

        wanted = rest.strip()
        if wanted:
            try:
                step = int(wanted)
            except ValueError:
                console.print(f"[red]not a step number:[/red] {markup_escape(wanted)}")
                return True
        else:
            # Bare /rollback means "undo what you just did", which for a human
            # is the most recent file edit. Anything earlier is an explicit
            # step, and the latest checkpoint is the one to undo to reach it.
            step = rows[-1].step

        report = CheckpointManager(store).rollback(session_id, step, workspace=workspace)
        if report.applied_checkpoints == 0:
            console.print(
                f"[dim]nothing to undo at step {step} or later — "
                f"/rollback takes a step from `loca sessions show {session_id}`[/dim]"
            )
            return True
        for line in _rollback_report_lines(report):
            console.print(f"[dim]{markup_escape(line)}[/dim]")
        return True

    console.print(f"[dim]unknown command {command!r} — try /help[/dim]")
    _ = rest
    return True


def cmd_sessions(args: argparse.Namespace) -> int:
    """``loca sessions [list|show|rm] [session_id]``."""
    from loca.observability import SessionStore

    action = args.action or "list"
    with SessionStore(args.db) as store:
        if action == "list":
            return _list_sessions(store, args.limit)
        if not args.session_id:
            print(f"loca sessions {action}: needs a session id")
            return 2
        if action == "show":
            return _show_session(store, args.session_id)
        if action == "rm":
            return _delete_session(store, args.session_id)
    return 0


def _list_sessions(store: Any, limit: int) -> int:
    sessions = store.list_sessions(limit=limit)
    if not sessions:
        print(f"no sessions yet in {store.path}")
        return 0
    print(f"{'session':<24} {'updated (UTC)':<20} {'msgs':>4}  title")
    for info in sessions:
        title = info.display_title
        if len(title) > 48:
            title = title[:47] + "…"
        print(
            f"{info.session_id:<24} {info.updated_at[:19]:<20} "
            f"{info.message_count:>4}  {title}"
        )
    print(f"\n{len(sessions)} session(s) · db {store.path}")
    return 0


def _show_session(store: Any, session_id: str) -> int:
    info = store.get_session(session_id)
    if info is None:
        print(f"no such session: {session_id}")
        return 1
    print(f"session   {info.session_id}")
    print(f"title     {info.display_title}")
    print(f"workspace {info.workspace or '-'}")
    print(f"provider  {info.provider or '-'} · model {info.model or '-'}")
    print(f"created   {info.created_at} · updated {info.updated_at}")
    print(f"messages  {info.message_count} · {info.next_step} model step(s) so far")
    print("-" * 72)
    for index, message in enumerate(store.load_messages(session_id)):
        body = (message.content or "").strip().replace("\n", " ")
        if len(body) > 200:
            body = body[:199] + "…"
        extra = ""
        if message.tool_calls:
            names = ", ".join(c.name for c in message.tool_calls)
            extra = f" → {names}()"
        if message.tool_call_id:
            extra = " (tool result)"
        print(f"[{index:>3}] {message.role.value:<9} {body}{extra}")

    checkpoints = store.list_checkpoints(session_id)
    if checkpoints:
        print("-" * 72)
        print("checkpoints (rollback target → files snapshotted before that step):")
        for row in checkpoints:
            print(f"  step {row.step:>3}  {row.tool or '-':<11} {row.created_at[:19]}")
    return 0


def _remove_trace_mirror(session_id: str, store: Any) -> bool:
    """Delete the session's JSONL trace mirror, if there is one.

    The recorder keeps a second copy of every step under ``<db dir>/traces/``.
    Leaving it behind meant ``loca report`` could still read a session the CLI
    had just claimed to delete — the message and the disk disagreed.
    """
    from loca.observability.trace import trace_jsonl_path

    path = trace_jsonl_path(session_id, db_path=store.path)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:  # pragma: no cover - permission or lock
        print(f"could not remove {path}: {exc}")
        return False
    return True


def _delete_session(store: Any, session_id: str) -> int:
    info = store.get_session(session_id)
    if info is None:
        print(f"no such session: {session_id}")
        return 1
    # Count before deleting. ``delete_session`` cascades to messages,
    # checkpoints and traces, so every count read afterwards was 0.
    traces = store.count_traces(session_id)
    checkpoints = len(store.list_checkpoints(session_id))
    store.delete_session(session_id)
    mirror_removed = _remove_trace_mirror(session_id, store)
    print(
        f"deleted {session_id} ({info.message_count} message(s), "
        f"{checkpoints} checkpoint(s) removed, {traces} trace(s) removed"
        + (", jsonl mirror removed" if mirror_removed else "")
        + ")"
    )
    return 0


def _rollback_report_lines(report: Any) -> list[str]:
    """Render a rollback that applied something, as plain printable lines.

    Shared by ``loca rollback`` and the REPL's ``/rollback`` so the two cannot
    drift apart. The "nothing to undo" case stays with the callers: a command
    names the step it was handed (``loca rollback demo 4``), the REPL does not
    (``/rollback`` defaults to the last checkpoint).
    """
    reasons = dict(report.skips)
    lines: list[str] = []
    touched = 0
    for path, action in report.settled().items():
        if action == "restored":
            lines.append(f"restored {path}")
            touched += 1
        elif action == "deleted":
            lines.append(f"deleted  {path} (did not exist before that step)")
            touched += 1
        else:
            reason = reasons.get(path)
            lines.append(f"skipped  {path}" + (f" ({reason})" if reason else ""))

    lines.append(
        f"\n{report.applied_checkpoints} checkpoint(s) applied · "
        f"{touched} file(s) affected"
    )
    if touched == 0:
        lines.append("(the workspace already matched the snapshots)")
    lines.append(
        "note: only file-tool edits are checkpointed — changes made by the "
        "shell tool cannot be rolled back"
    )
    return lines


def cmd_rollback(args: argparse.Namespace) -> int:
    """``loca rollback <session_id> <step>`` — undo file edits from a step on."""
    from loca.observability import CheckpointManager, SessionStore

    try:
        workspace = (
            resolve_workspace(args.workspace) if args.workspace is not None else None
        )
    except ValueError as exc:
        print(exc)
        return 2

    with SessionStore(args.db) as store:
        if store.get_session(args.session_id) is None:
            print(f"no such session: {args.session_id}")
            return 1
        manager = CheckpointManager(store)
        report = manager.rollback(args.session_id, args.step, workspace=workspace)
        if report.applied_checkpoints == 0:
            print(
                f"no checkpoints at step {args.step} or later in {args.session_id} "
                "— nothing to undo"
            )
            return 0

        for line in _rollback_report_lines(report):
            print(line)
        return 0


def cmd_report(args: argparse.Namespace) -> int:
    """``loca report [<session_id>]`` — render a session's execution trace."""
    from loca.observability import SessionStore
    from loca.observability.reporter import gather, render, render_json

    with SessionStore(args.db) as store:
        session_id = args.session_id
        if session_id is None:
            recent = store.list_sessions(limit=1)
            if not recent:
                print("no sessions recorded yet — run `loca chat` first")
                return 1
            session_id = recent[0].session_id
            # Diagnostic, not report content: keep stdout clean so
            # `loca report --json | jq` stays valid.
            print(
                f"(no session given — reporting the most recent one: {session_id})",
                file=sys.stderr,
            )

        data = gather(store, session_id)
        if data.session is None and not data.steps:
            print(f"no such session: {session_id}")
            return 1

        if args.json:
            # Plain print (not the Rich console) so `--json` stays pipeable.
            print(render_json(data))
            return 0

        render(
            data,
            _console(),
            # `--limit 0` means "everything"; that is the default because a
            # report you have to scroll is still better than a truncated one.
            limit=None if args.limit <= 0 else args.limit,
            verbose=args.verbose,
        )
        return 0


def _ask(console: Any) -> str:
    from rich.prompt import Prompt

    return Prompt.ask("\n[bold green]you[/bold green]")


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))
    load_env()
    uvicorn.run(
        "web.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )
    return 0


def cmd_tools(args: argparse.Namespace) -> int:
    from loca.tools import register_default_tools
    from loca.tools.registry import all_tools

    register_default_tools()
    for tool in all_tools():
        required = tool.input_schema.get("required", [])
        print(f"{tool.name:<12} required={required or '[]'}")
        print(f"{'':<12} {tool.description.splitlines()[0]}")
    return 0


def cmd_providers(args: argparse.Namespace) -> int:
    from loca.providers.registry import available_providers

    load_env()
    ready = set(available_providers())
    for name in ("deepseek", "openai", "anthropic"):
        mark = "✓" if name in ready else "·"
        state = "key set" if name in ready else f"no LOCA_{name.upper()}_API_KEY"
        print(f"{mark} {name:<10} {state}")
    print(f"\ndefault: {os.environ.get('LOCA_DEFAULT_PROVIDER', 'deepseek')}")
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    """``loca bench [list|run|verify]`` — the Week 6 evaluation harness."""
    import json
    import shutil
    import tempfile

    from rich.markup import escape as markup_escape
    from rich.table import Table

    from loca.eval import (
        compare,
        load_tasks,
        render,
        render_comparison,
        render_json,
        run_benchmark,
        verify_task_set,
    )
    from loca.eval.report import render_comparison_json
    from loca.providers.registry import get_provider
    from loca.tools import register_default_tools

    console = _console()
    load_env()
    register_default_tools()

    tasks = load_tasks()
    if not tasks:
        console.print("[red]no tasks found[/red] — expected them under loca/eval/tasks/")
        return 1

    action = getattr(args, "action", "list") or "list"

    if action == "list":
        selected = tasks.select(ids=args.task, difficulties=args.difficulty, limit=args.limit)
        if args.json:
            print(
                json.dumps(
                    [
                        {
                            "id": t.id,
                            "title": t.title,
                            "difficulty": t.difficulty,
                            "tags": list(t.tags),
                            "has_solution": t.has_solution,
                        }
                        for t in selected
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        table = Table(title=f"{len(selected)} task(s)", title_justify="left", header_style="bold")
        table.add_column("id")
        table.add_column("tier")
        table.add_column("title")
        table.add_column("tags")
        for task in selected:
            colour = {"simple": "green", "medium": "yellow", "hard": "red"}.get(
                task.difficulty, "white"
            )
            table.add_row(
                f"[bold]{markup_escape(task.id)}[/bold]",
                f"[{colour}]{markup_escape(task.difficulty)}[/{colour}]",
                markup_escape(task.title),
                markup_escape(", ".join(task.tags)),
            )
        console.print(table)
        counts = tasks.counts()
        console.print(
            "[dim]"
            + " · ".join(f"{name} {count}" for name, count in counts.items())
            + " · `loca bench verify` checks the task set, "
            + "`loca bench run` runs it[/dim]"
        )
        return 0

    if action == "verify":
        workdir = Path(tempfile.mkdtemp(prefix="loca-bench-verify-"))
        console.print(
            "[dim]checking every task: seed must fail, reference solution must pass[/dim]"
        )
        report = verify_task_set(tasks, workdir=workdir, keep=args.keep)
        if args.json:
            print(
                json.dumps(
                    [
                        {
                            "task_id": e.task_id,
                            "difficulty": e.difficulty,
                            "ok": e.ok,
                            "fails_on_seed": e.fails_on_seed,
                            "passes_with_solution": e.passes_with_solution,
                        }
                        for e in report
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        table = Table(title="task set integrity", title_justify="left", header_style="bold")
        table.add_column("task")
        table.add_column("tier")
        table.add_column("fails on seed")
        table.add_column("solution passes")
        for entry in report:
            table.add_row(
                markup_escape(entry.task_id),
                markup_escape(entry.difficulty),
                _tick(entry.fails_on_seed),
                (
                    "[red]missing[/red]"
                    if entry.passes_with_solution is None
                    else _tick(entry.passes_with_solution)
                ),
            )
        console.print(table)
        broken = [e for e in report if not e.ok]
        if broken:
            console.print(f"[bold red]{len(broken)} task(s) are broken[/bold red]")
            for entry in broken:
                console.print(f"  [red]{markup_escape(entry.task_id)}[/red] {entry.error}")
                if not entry.fails_on_seed:
                    detail = markup_escape(entry.seed_detail[:200])
                    console.print(f"    [dim]seed detail: {detail}[/dim]")
                if not entry.has_solution:
                    console.print(
                        "    [dim]no reference answer — nothing proves this task "
                        "can be solved[/dim]"
                    )
                elif entry.passes_with_solution is False:
                    detail = markup_escape(entry.solution_detail[:200])
                    console.print(f"    [dim]solution detail: {detail}[/dim]")
            return 1
        console.print(f"[green]all {len(report)} task(s) check out[/green]")
        return 0

    # ---- run --------------------------------------------------------------
    selected = tasks.select(ids=args.task, difficulties=args.difficulty, limit=args.limit)
    if not selected:
        console.print("[red]no tasks matched the filters[/red]")
        return 1

    provider_names = [p.strip() for p in (args.compare or "").split(",") if p.strip()]
    if not provider_names:
        provider_names = [args.provider or ""]

    workdir = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="loca-bench-"))
    workdir.mkdir(parents=True, exist_ok=True)

    reports = []
    for name in provider_names:
        label = name or os.environ.get("LOCA_DEFAULT_PROVIDER", "deepseek")

        def factory(provider_name: str = label):
            return get_provider(provider_name)

        console.print(
            f"[bold cyan]bench[/bold cyan] · provider [cyan]{label}[/cyan] · "
            f"{len(selected)} task(s) × {args.attempts} attempt(s) · "
            f"{args.workers} worker(s)"
        )
        total = len(selected) * args.attempts

        def on_progress(done: int, total_count: int, result: Any) -> None:
            mark = "✓" if result.passed else "✗"
            colour = "green" if result.passed else "red"
            console.print(
                f"  [{colour}]{mark}[/{colour}] {markup_escape(result.task_id):<34} "
                f"[dim]{markup_escape(result.outcome):<14} "
                f"{result.steps:>2} step(s) {result.tokens:>6} tok "
                f"{result.duration_s:>5.1f}s  ({done}/{total_count})[/dim]"
            )

        console.print(f"[dim]{total} attempt(s) queued[/dim]")

        report = run_benchmark(
            selected,
            provider_factory=factory,
            provider_name=label,
            model=args.model,
            attempts=args.attempts,
            workers=args.workers,
            max_steps=args.max_steps,
            timeout_s=args.timeout,
            workdir=workdir,
            store_path=args.db,
            trace=not args.no_trace,
            keep=args.keep,
            progress=on_progress,
        )
        reports.append(report)

        if args.json and len(provider_names) == 1:
            print(render_json(report))
        elif len(provider_names) == 1:
            console.print()
            render(report, console, verbose=args.verbose)
        else:
            console.print(
                f"  [dim]{report.provider}: {report.pass_at_1 * 100:.1f}% pass@1 "
                f"({report.passed_attempts}/{report.total_attempts})[/dim]"
            )

        if args.out:
            out = Path(args.out)
            payload = render_json(report)
            out.write_text(payload, encoding="utf-8")
            console.print(f"[dim]wrote {out}[/dim]")

    if len(reports) > 1:
        rows = compare(reports)
        console.print()
        if args.json:
            print(render_comparison_json(rows))
        else:
            render_comparison(rows, console)

    if args.keep:
        console.print(f"[dim]sandboxes kept in {workdir}[/dim]")
    elif args.workdir is None:
        # A temp dir we created ourselves is disposable; `run_benchmark` has
        # already removed the sandboxes, this just clears the parent.
        shutil.rmtree(workdir, ignore_errors=True)

    return 0


def _tick(ok: bool) -> str:
    return "[green]yes[/green]" if ok else "[bold red]no[/bold red]"


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="loca", description="a coding-agent harness")
    sub = parser.add_subparsers(dest="command")

    chat = sub.add_parser("chat", help="interactive agent REPL")
    chat.add_argument(
        "--provider",
        default=None,
        help="provider name (default: $LOCA_DEFAULT_PROVIDER)",
    )
    chat.add_argument(
        "--workspace",
        default=os.getcwd(),
        help="Windows path the tools operate in (default: current directory)",
    )
    chat.add_argument("--max-steps", type=int, default=20)
    chat.add_argument("--token-budget", type=int, default=DEFAULT_TOKEN_BUDGET)
    chat.add_argument("--system", default=None, help="override the system prompt")
    chat.add_argument(
        "--no-tools",
        action="store_true",
        help="plain chat: do not expose the filesystem/shell tools",
    )
    chat.add_argument(
        "--session",
        default=None,
        help="resume this session id, or start one with that id (see `loca sessions`)",
    )
    chat.add_argument(
        "--db",
        default=None,
        help="session database path (default: $LOCA_DB or ~/.loca/sessions.db)",
    )
    chat.add_argument(
        "--no-save",
        action="store_true",
        help="do not persist the session and do not take checkpoints",
    )
    chat.add_argument(
        "--model",
        default=None,
        help="model name, used for token counting and the summary call",
    )
    chat.add_argument(
        "--keep-recent",
        type=int,
        default=6,
        help="messages kept verbatim when the context is compacted",
    )
    chat.add_argument(
        "--no-summarize",
        dest="summarize",
        action="store_false",
        help="drop old turns instead of summarizing them when the context fills up",
    )
    chat.add_argument(
        "--no-trace",
        dest="trace",
        action="store_false",
        help="do not record a per-step trace (see `loca report`)",
    )
    chat.set_defaults(func=cmd_chat, summarize=True, trace=True)

    sessions = sub.add_parser("sessions", help="list, inspect or delete stored sessions")
    sessions.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=["list", "show", "rm"],
        help="what to do (default: list)",
    )
    sessions.add_argument("session_id", nargs="?", default=None, help="target session id")
    sessions.add_argument("--db", default=None, help="session database path")
    sessions.add_argument("--limit", type=int, default=50, help="max sessions to list")
    sessions.set_defaults(func=cmd_sessions)

    rollback = sub.add_parser(
        "rollback", help="restore files to their state before a given step"
    )
    rollback.add_argument("session_id", help="session to roll back")
    rollback.add_argument(
        "step",
        type=int,
        help="undo this step and everything after it (0 = undo the whole session)",
    )
    rollback.add_argument("--db", default=None, help="session database path")
    rollback.add_argument(
        "--workspace",
        default=None,
        help=(
            "Windows path to restore into (default: the one recorded "
            "in the session)"
        ),
    )
    rollback.set_defaults(func=cmd_rollback)

    report = sub.add_parser("report", help="render the execution trace of a session")
    report.add_argument(
        "session_id",
        nargs="?",
        default=None,
        help="session to report on (default: the most recently updated one)",
    )
    report.add_argument("--db", default=None, help="session database path")
    report.add_argument(
        "--limit",
        type=int,
        default=0,
        help="max steps to list (default 0 = all)",
    )
    report.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="show per-step prompts, replies and tool output previews",
    )
    report.add_argument(
        "--json",
        action="store_true",
        help="emit the report as JSON instead of a rendered table",
    )
    report.set_defaults(func=cmd_report)

    bench = sub.add_parser("bench", help="run the evaluation suite")
    bench.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=["list", "run", "verify"],
        help="list tasks (default), run a benchmark, or verify the task set",
    )
    bench.add_argument("--provider", default=None, help="provider to benchmark")
    bench.add_argument(
        "--compare",
        default=None,
        help="comma-separated providers to run and compare, e.g. deepseek,openai",
    )
    bench.add_argument("--model", default=None, help="model override")
    bench.add_argument(
        "--task",
        action="append",
        default=None,
        help="only this task id (repeatable)",
    )
    bench.add_argument(
        "--difficulty",
        action="append",
        default=None,
        choices=["simple", "medium", "hard"],
        help="only this tier (repeatable)",
    )
    bench.add_argument("--limit", type=int, default=0, help="max tasks (0 = all)")
    bench.add_argument("--attempts", type=int, default=1, help="attempts per task")
    bench.add_argument("--workers", type=int, default=4, help="parallel attempts")
    bench.add_argument("--max-steps", type=int, default=None, help="step cap per attempt")
    bench.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="wall-clock cap per attempt, in seconds",
    )
    bench.add_argument("--db", default=None, help="record each attempt into this session database")
    bench.add_argument("--workdir", default=None, help="where to create task sandboxes")
    bench.add_argument("--keep", action="store_true", help="keep the sandboxes after the run")
    bench.add_argument("--no-trace", action="store_true", help="do not record per-step traces")
    bench.add_argument("--out", default=None, help="write the report JSON to this file")
    bench.add_argument("--verbose", "-v", action="store_true", help="show per-task detail")
    bench.add_argument("--json", action="store_true", help="emit JSON")
    bench.set_defaults(func=cmd_bench)

    serve = sub.add_parser("serve", help="run the web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--reload", action="store_true")
    serve.add_argument("--log-level", default="info")
    serve.set_defaults(func=cmd_serve)

    tools = sub.add_parser("tools", help="list registered tools")
    tools.set_defaults(func=cmd_tools)

    providers = sub.add_parser("providers", help="show provider credential status")
    providers.set_defaults(func=cmd_providers)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "command", None) is None:
        parser.print_help()
        return 0
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
