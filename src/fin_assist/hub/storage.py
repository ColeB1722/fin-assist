"""SQLite-backed implementation of fasta2a's Storage ABC.

Stores A2A tasks (state, artifacts, message history) and per-context conversation
history in a local SQLite database.  Shared across all mounted agents on the hub,
with context_id naturally scoping conversations per agent path.

Context storage
~~~~~~~~~~~~~~~
The ``ContextT`` parameter for this storage is ``list[ModelMessage]`` (pydantic-ai
message history).  These are pydantic dataclass objects, not plain dicts, so we
use pydantic's ``TypeAdapter`` for JSON serialization instead of ``json.dumps``.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import TYPE_CHECKING, Any, cast

from fasta2a.storage import Storage
from pydantic import TypeAdapter
from pydantic_ai import ModelMessage

if TYPE_CHECKING:
    from fasta2a.schema import Artifact, Message, Task, TaskState

_context_ta = TypeAdapter(list[ModelMessage])


class SQLiteStorage(Storage[list[ModelMessage]]):
    """Persistent storage backed by SQLite.

    Args:
        db_path: Path to the SQLite database file, or ``":memory:"`` for an
                 in-process database (useful for tests).  Defaults to
                 ``":memory:"``.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._create_schema()
        return self._conn

    def _create_schema(self) -> None:
        conn = self._conn
        assert conn is not None
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id          TEXT PRIMARY KEY,
                context_id  TEXT NOT NULL,
                data        TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS contexts (
                context_id  TEXT PRIMARY KEY,
                data        TEXT NOT NULL
            );
        """)
        conn.commit()

    # ------------------------------------------------------------------
    # Storage ABC — tasks
    # ------------------------------------------------------------------

    async def load_task(self, task_id: str, history_length: int | None = None) -> Task | None:
        conn = self._get_conn()
        row = conn.execute("SELECT data FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        raw: dict[str, Any] = json.loads(row["data"])
        if history_length is not None and "history" in raw:
            raw["history"] = raw["history"][-history_length:]
        return cast("Task", raw)

    async def submit_task(self, context_id: str, message: Message) -> Task:
        task_id = str(uuid.uuid4())
        # Annotate the message with task/context identifiers (mirrors InMemoryStorage)
        msg: dict[str, Any] = {**message}  # type: ignore[arg-type]
        msg["task_id"] = task_id
        msg["context_id"] = context_id

        raw: dict[str, Any] = {
            "kind": "task",
            "id": task_id,
            "context_id": context_id,
            "status": {"state": "submitted"},
            "history": [msg],
        }
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO tasks (id, context_id, data) VALUES (?, ?, ?)",
            (task_id, context_id, json.dumps(raw)),
        )
        conn.commit()
        return cast("Task", raw)

    async def update_task(
        self,
        task_id: str,
        state: TaskState,
        new_artifacts: list[Artifact] | None = None,
        new_messages: list[Message] | None = None,
    ) -> Task:
        conn = self._get_conn()
        row = conn.execute("SELECT data FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"Task {task_id!r} not found")

        raw: dict[str, Any] = json.loads(row["data"])
        raw["status"] = {"state": state}

        if new_artifacts:
            existing = raw.get("artifacts", [])
            raw["artifacts"] = existing + list(new_artifacts)

        if new_messages:
            existing_history = raw.get("history", [])
            raw["history"] = existing_history + list(new_messages)

        conn.execute(
            "UPDATE tasks SET data = ? WHERE id = ?",
            (json.dumps(raw), task_id),
        )
        conn.commit()
        return cast("Task", raw)

    # ------------------------------------------------------------------
    # Storage ABC — context (conversation history)
    # ------------------------------------------------------------------

    async def load_context(self, context_id: str) -> list[ModelMessage] | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT data FROM contexts WHERE context_id = ?", (context_id,)
        ).fetchone()
        if row is None:
            return None
        return _context_ta.validate_json(row["data"])

    async def update_context(self, context_id: str, context: list[ModelMessage]) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO contexts (context_id, data) VALUES (?, ?)
            ON CONFLICT(context_id) DO UPDATE SET data = excluded.data
            """,
            (context_id, _context_ta.dump_json(context).decode()),
        )
        conn.commit()
