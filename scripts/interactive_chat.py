"""Interactive chat with loca — streaming, with the four built-in tools.

Thin launcher around ``loca chat`` so there is exactly one REPL
implementation. Any argument you pass here is forwarded:

    python scripts/interactive_chat.py                      # tools enabled
    python scripts/interactive_chat.py --no-tools           # plain chat
    python scripts/interactive_chat.py --workspace D:\\x     # change workspace

or, once the package is installed, just:

    loca chat

Type ``exit`` / ``quit`` (or Ctrl-C) to leave.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make ``loca`` importable when this file is run directly from the IDE.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from loca.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["chat", *sys.argv[1:]]))
