"""Allow ``python -m loca ...`` as an alias for the ``loca`` console script.

This makes the package runnable straight from a checkout, without relying on
``.venv/Scripts/loca.exe`` being on ``PATH``::

    python -m loca chat
    python -m loca serve
"""

from __future__ import annotations

from loca.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
