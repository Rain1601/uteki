"""SQLModel table for persisted runs.

Stored as one row per Run. Events are kept as a JSON-serialized list on
the row itself — for our scale (5000 events / run max) JSON-in-column is
faster than a join table and avoids 5000 INSERTs per run on append_event.

Events are *buffered in memory* during the run; only flushed to this row
at ``finish()``. That means a cross-process read of an in-flight run
shows ``events=[]`` until finish — acceptable for the MCP polling use
case (CC polls ``get_run`` for ``status`` change, doesn't need raw events).

In-flight crash recovery: ``status='running'`` rows from a previous
process that crashed are left as-is — they'll show as perpetually
running. Future work: a boot-time sweep that marks them as ``error``.
"""

from __future__ import annotations

from sqlmodel import Field, SQLModel


class RunRow(SQLModel, table=True):
    """Persisted Run record. Keep field names aligned with ``Run`` for
    straightforward round-tripping."""

    __tablename__ = "run"

    id: str = Field(primary_key=True)
    # M4: required. ``"system"`` is reserved for platform-level runs.
    user_id: str = Field(index=True)
    skill: str = Field(index=True)
    skill_version: str | None = None
    triggered_by: str  # RunStatus literal value, kept loose for forward-compat
    trigger_reason: str = ""
    started_at: float = Field(index=True)
    ended_at: float | None = None
    status: str = "running"  # "running" | "ok" | "error" | "timeout"
    user_input: str = ""
    summary: str = ""
    # JSON-encoded blobs; deserialized by SqliteRunStore.
    events_json: str = "[]"
    tags_json: str = "[]"
    usage_summary_json: str = "{}"
