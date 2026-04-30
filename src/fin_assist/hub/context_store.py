"""SQLite-backed conversation context store.

Stores per-context-id conversation history as opaque ``bytes`` in a
local SQLite database.  Shared across all mounted agents on the hub, with
``context_id`` naturally scoping conversations per agent path.

Serialization (including versioning) is the backend's responsibility —
this store treats bytes opaquely.  Backends wrap payloads with the
envelope helpers in ``fin_assist.agents.serialization`` before saving
and unwrap after loading.  A2A task storage is handled separately by
``a2a-sdk``'s ``InMemoryTaskStore``; this module owns the opaque blobs
that persist across tasks within a conversation.

Pause-state persistence
~~~~~~~~~~~~~~~~~~~~~~~
When a task pauses for human approval the resume may land in a *different
process* (hub restart, multi-worker deployment).  OTel spans cannot be
reopened across processes, so the executor saves the paused
``approval_request`` span's SpanContext (``trace_id``, ``span_id``,
``trace_flags``) here at pause time, and loads it at resume to seed a
span ``Link`` on the new task span.  The pause-state row is independent
of the opaque ``data`` blob so history serialization stays backend-owned
while trace plumbing stays platform-owned.

The row also persists the original ``user_input`` (prompt) so the
resume can hydrate ``input.value`` on the new task span — the resume
message itself only carries ``approval_result`` metadata, not the
original prompt.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class PauseState:
    """Everything needed to resume a paused task without losing trace
    context continuity.

    Returned by :meth:`ContextStore.load_pause_state` and consumed by
    the executor at resume time.
    """

    trace_id: int
    """Paused ``approval_request`` span's trace id.  Used with
    ``span_id`` + ``trace_flags`` to build a Link on the resumed task
    span."""

    span_id: int
    trace_flags: int

    user_input: str
    """Original prompt that started the (now-paused) task.  Used to
    hydrate ``input.value`` on the resumed task span."""


class ContextStore:
    """Persistent conversation context store backed by SQLite.

    Args:
        db_path: Path to the SQLite database file, or ``":memory:"`` for an
                 in-process database (useful for tests).  Defaults to
                 ``":memory:"``.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS contexts (
                    context_id  TEXT PRIMARY KEY,
                    data        BLOB NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trace_contexts (
                    context_id  TEXT PRIMARY KEY,
                    trace_id    TEXT NOT NULL,
                    span_id     TEXT NOT NULL,
                    trace_flags INTEGER NOT NULL,
                    user_input  TEXT NOT NULL DEFAULT ''
                )
                """
            )
            self._conn.commit()
        return self._conn

    async def load(self, context_id: str) -> bytes | None:
        """Load serialized conversation history for the given context ID.

        Returns ``None`` if no history exists for this context.  The caller
        (typically an ``AgentBackend``) is responsible for unwrapping the
        envelope via ``fin_assist.agents.serialization.unwrap_payload``.
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT data FROM contexts WHERE context_id = ?", (context_id,)
        ).fetchone()
        if row is None:
            return None
        return bytes(row["data"])

    async def save(self, context_id: str, data: bytes) -> None:
        """Save (upsert) serialized conversation history for the given context ID."""
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO contexts (context_id, data) VALUES (?, ?)
            ON CONFLICT(context_id) DO UPDATE SET data = excluded.data
            """,
            (context_id, data),
        )
        conn.commit()

    async def save_pause_state(
        self,
        *,
        context_id: str,
        trace_id: int,
        span_id: int,
        trace_flags: int,
        user_input: str,
    ) -> None:
        """Persist everything needed to resume a paused task.

        IDs are stored as hex strings (32 chars for trace, 16 for span)
        so values round-trip through any SQLite client and are readable
        when debugging by hand.

        Upserts: a subsequent pause on the same ``context_id`` replaces
        the earlier entry.
        """
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO trace_contexts (context_id, trace_id, span_id, trace_flags, user_input)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(context_id) DO UPDATE SET
                trace_id    = excluded.trace_id,
                span_id     = excluded.span_id,
                trace_flags = excluded.trace_flags,
                user_input  = excluded.user_input
            """,
            (
                context_id,
                f"{trace_id:032x}",
                f"{span_id:016x}",
                trace_flags,
                user_input,
            ),
        )
        conn.commit()

    async def load_pause_state(self, context_id: str) -> PauseState | None:
        """Return the full pause state or ``None`` if no pause is
        recorded for this ``context_id``.
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT trace_id, span_id, trace_flags, user_input "
            "FROM trace_contexts WHERE context_id = ?",
            (context_id,),
        ).fetchone()
        if row is None:
            return None
        return PauseState(
            trace_id=int(row["trace_id"], 16),
            span_id=int(row["span_id"], 16),
            trace_flags=int(row["trace_flags"]),
            user_input=row["user_input"] or "",
        )
