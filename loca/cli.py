"""Command-line entry point.

    loca chat          interactive agent REPL (tools enabled)
    loca chat --no-tools
                       plain streaming chat, no tool use
    loca serve         run the web UI
    loca tools         list the registered tools
    loca providers     show which providers have credentials

The REPL drives the real :class:`~loca.core.loop.AgentLoop`, so tool calls,
retries, context trims and errors are all visible as they happen.
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
) -> str:
    """Consume one agent turn, render it, and return the assistant's text.

    Kept as a free function (not buried in the REPL loop) so it can be tested
    with a scripted provider and a StringIO console.
    """
    text_parts: list[str] = []
    usage: dict[str, int] | None = None
    done: dict[str, Any] | None = None

    for event in loop.run(ctx, user_message=user_message, history=history):
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

        elif kind is EventType.USAGE:
            usage = event.data

        elif kind is EventType.RECOVERY:
            console.print(
                f"\n[yellow]recovering from {event.data['reason']} — "
                "asking the model to continue[/yellow]"
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
    from loca.providers.registry import get_provider
    from loca.tools import register_default_tools

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

    tools = []
    if not args.no_tools:
        register_default_tools()
        from loca.tools.registry import all_tools

        tools = list(all_tools())

    workspace = Path(args.workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    loop = AgentLoop(
        provider=provider,
        tools=tools,
        max_steps=args.max_steps,
        context_token_budget=args.token_budget,
        system_prompt=args.system,
    )
    ctx = ToolContext(workspace=workspace, session_id="cli", step_index=0)

    console.print(
        f"[bold cyan]loca[/bold cyan] · provider [cyan]{provider.name}[/cyan] · "
        f"{len(tools)} tool(s) · workspace [dim]{workspace}[/dim]"
    )
    console.print("[dim]Type 'exit' or Ctrl-C to quit.[/dim]")

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

        console.print("[bold magenta]assistant[/bold magenta] ", end="")
        try:
            # Feed the previous transcript back so the REPL is multi-turn.
            run_turn(
                loop,
                ctx,
                text,
                console,
                history=list(loop.last_transcript) or None,
            )
        except KeyboardInterrupt:
            console.print("\n[yellow](interrupted)[/yellow]")
        ctx.step_index += 1


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
    chat.add_argument("--workspace", default=os.getcwd(), help="directory tools operate in")
    chat.add_argument("--max-steps", type=int, default=20)
    chat.add_argument("--token-budget", type=int, default=DEFAULT_TOKEN_BUDGET)
    chat.add_argument("--system", default=None, help="override the system prompt")
    chat.add_argument(
        "--no-tools",
        action="store_true",
        help="plain chat: do not expose the filesystem/shell tools",
    )
    chat.set_defaults(func=cmd_chat)

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
