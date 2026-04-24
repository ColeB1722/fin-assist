"""SQLite-backed conversation context store.

Stores per-context-id conversation history as opaque ``bytes`` in a
local SQLite database.  Shared across all mounted agents on the hub, with
``context_id`` naturally scoping conversations per agent path.

Serialization is the backend's responsibility — the store has no framework
dependencies.  A2A task storage is handled by ``a2a-sdk``'s
``InMemoryTaskStore``; this module owns the opaque blobs that persist
across tasks within a conversation.

Versioning
~~~~~~~~~~
Each stored blob is prefixed with a single version byte (big-endian
``unsigned char``).  When the serialization format changes, increment
``_CONTEXT_STORE_VERSION``.  The ``load`` method validates the version
and raises ``ValueError`` on mismatch.  Existing stores that lack a
version prefix are migrated automatically on first load.
"""

from __future__ import annotations

import sqlite3
import struct

_CONTEXT_STORE_VERSION = 1
_VERSION_PACK = struct.Struct("!B")


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

        Raises:
            ValueError: If the stored data has an unsupported version byte.
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

    @staticmethod
    def wrap_payload(data: bytes) -> bytes:
        """Prefix *data* with the current version byte."""
        return _VERSION_PACK.pack(_CONTEXT_STORE_VERSION) + data

    @staticmethod
    def unwrap_payload(data: bytes) -> bytes:
        """Strip and validate the version byte prefix from *data*.

        Raises:
            ValueError: If the version byte does not match
                ``_CONTEXT_STORE_VERSION``.
        """
        if len(data) < _VERSION_PACK.size:
            raise ValueError(f"Context store data too short ({len(data)} bytes)")
        version = _VERSION_PACK.unpack(data[: _VERSION_PACK.size])[0]
        if version != _CONTEXT_STORE_VERSION:
            raise ValueError(f"Unsupported context store version {version}")
        return data[_VERSION_PACK.size :]
