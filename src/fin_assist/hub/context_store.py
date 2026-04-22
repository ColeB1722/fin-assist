"""SQLite-backed conversation context store.

Stores per-context-id conversation history as opaque ``bytes`` in a
local SQLite database.  Shared across all mounted agents on the hub, with
``context_id`` naturally scoping conversations per agent path.

Serialization is the backend's responsibility — the store has no framework
dependencies.  A2A task storage is handled by ``a2a-sdk``'s
``InMemoryTaskStore``; this module owns the opaque blobs that persist
across tasks within a conversation.
"""

from __future__ import annotations

import sqlite3


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
            self._conn.commit()
        return self._conn

    async def load(self, context_id: str) -> bytes | None:
        """Load serialized conversation history for the given context ID.

        Returns ``None`` if no history exists for this context.
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
