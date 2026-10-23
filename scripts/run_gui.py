"""Launch the Loca Web GUI with automatic browser opening.

Starts the FastAPI + SSE backend on http://127.0.0.1:8765 and opens the
default browser as soon as the healthcheck endpoint is ready.
"""

from __future__ import annotations

import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

# Make ``loca`` importable when this file is run directly.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from loca.cli import main  # noqa: E402


def _open_when_ready(url: str = "http://127.0.0.1:8765", max_wait_s: float = 15.0) -> None:
    health_url = f"{url.rstrip('/')}/api/health"
    deadline = time.time() + max_wait_s
    open_url = f"{url.rstrip('/')}/?t={int(time.time())}"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=1.0) as resp:
                if resp.status == 200:
                    webbrowser.open(open_url)
                    return
        except Exception:
            time.sleep(0.3)
    # Fallback: try opening anyway if healthcheck probe timed out
    webbrowser.open(open_url)


if __name__ == "__main__":
    port = 8765
    host = "127.0.0.1"

    # Inspect arguments for custom host/port if provided
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg in ("--port", "-p") and i + 1 < len(args):
            try:
                port = int(args[i + 1])
            except ValueError:
                pass
        elif arg == "--host" and i + 1 < len(args):
            host = args[i + 1]

    target_url = f"http://{host}:{port}"
    threading.Thread(target=_open_when_ready, args=(target_url,), daemon=True).start()

    raise SystemExit(main(["serve", *args]))
