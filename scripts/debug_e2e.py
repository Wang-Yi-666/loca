"""One-off debug: run the agent loop against real DeepSeek and dump events."""

from __future__ import annotations

import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Imports come after load_dotenv on purpose: the registry reads the key from
# the environment at call time, and this keeps the script runnable anywhere.
from loca.core.loop import AgentLoop  # noqa: E402
from loca.providers.registry import get_provider  # noqa: E402
from loca.tools import register_default_tools  # noqa: E402
from loca.tools.base import ToolContext  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="loca-debug-"))
(tmp / "secret.txt").write_text("loca-rocks-2026", encoding="utf-8")

register_default_tools()
provider = get_provider("deepseek")
loop = AgentLoop(provider=provider, max_steps=5)
ctx = ToolContext(workspace=tmp, session_id="debug", step_index=0)

print(f"workspace={tmp}")
for e in loop.run(
    ctx,
    user_message=(
        "Use the read_file tool to read secret.txt and tell me its "
        "contents in one short sentence."
    ),
):
    print(f"--- {e.type.value} ---")
    if e.type.value == "text_delta":
        print(e.data["content"], end="")
    else:
        print(repr(e.data))
print()
