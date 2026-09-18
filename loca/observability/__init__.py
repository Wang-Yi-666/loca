"""Observability and durability: session storage, checkpoints, traces.

Week 4 delivered the durable part of a session — the transcript, and the file
snapshots needed to resume work and to undo it. Week 5 adds the read side:
:mod:`~loca.observability.trace` records what each model step cost and did, and
:mod:`~loca.observability.reporter` turns those records into ``loca report``.
"""

from loca.observability.checkpoint import (
    Checkpoint,
    CheckpointManager,
    FileSnapshot,
    RollbackReport,
)
from loca.observability.reporter import (
    ReportData,
    ToolStat,
    TraceSummary,
    gather,
    render,
    render_json,
    summarize,
    to_dict,
)
from loca.observability.storage import (
    CheckpointRow,
    SessionInfo,
    SessionStore,
    TraceRow,
    default_db_path,
    new_session_id,
)
from loca.observability.trace import (
    StepTrace,
    ToolCallRecord,
    ToolResultRecord,
    TraceRecorder,
    default_trace_dir,
    load_steps,
    read_jsonl,
    trace_jsonl_path,
)

__all__ = [
    "Checkpoint",
    "CheckpointManager",
    "CheckpointRow",
    "FileSnapshot",
    "ReportData",
    "RollbackReport",
    "SessionInfo",
    "SessionStore",
    "StepTrace",
    "ToolCallRecord",
    "ToolResultRecord",
    "ToolStat",
    "TraceRecorder",
    "TraceRow",
    "TraceSummary",
    "default_db_path",
    "default_trace_dir",
    "gather",
    "load_steps",
    "new_session_id",
    "read_jsonl",
    "render",
    "render_json",
    "summarize",
    "to_dict",
    "trace_jsonl_path",
]
