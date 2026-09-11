"""Shared pytest fixtures for the loca test suite.

VS Code's Python extension reads this to know how to discover and run tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    from dotenv import load_dotenv

    _root = Path(__file__).resolve().parent
    load_dotenv(_root / ".env")
except ImportError:  # python-dotenv is optional
    pass


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A throwaway directory used as a tool's workspace."""
    return tmp_path


@pytest.fixture
def ctx(workspace: Path):  # type: ignore[no-untyped-def]
    """A ``ToolContext`` whose ``workspace`` is the per-test tmp_path."""
    from loca.tools.base import ToolContext

    return ToolContext(workspace=workspace, session_id="test", step_index=0)
