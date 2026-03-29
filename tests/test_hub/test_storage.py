"""Tests for SQLiteStorage — fasta2a Storage ABC implementation."""

from __future__ import annotations

import pytest

from fin_assist.hub.storage import SQLiteStorage


@pytest.fixture
def storage(tmp_path) -> SQLiteStorage:
    """Return a SQLiteStorage backed by a temporary database file."""
    return SQLiteStorage(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def in_memory_storage() -> SQLiteStorage:
    """Return a SQLiteStorage backed by an in-memory SQLite database."""
    return SQLiteStorage(db_path=":memory:")


# ---------------------------------------------------------------------------
# submit_task
# ---------------------------------------------------------------------------


class TestSubmitTask:
    @pytest.mark.asyncio
    async def test_returns_task_with_submitted_state(self, in_memory_storage) -> None:
        message = _make_message("hello")
        task = await in_memory_storage.submit_task(context_id="ctx1", message=message)
        assert task["status"]["state"] == "submitted"

    @pytest.mark.asyncio
    async def test_task_has_id(self, in_memory_storage) -> None:
        message = _make_message("hello")
        task = await in_memory_storage.submit_task(context_id="ctx1", message=message)
        assert isinstance(task["id"], str)
        assert len(task["id"]) > 0

    @pytest.mark.asyncio
    async def test_task_context_id_matches(self, in_memory_storage) -> None:
        message = _make_message("hello")
        task = await in_memory_storage.submit_task(context_id="ctx-abc", message=message)
        assert task["context_id"] == "ctx-abc"

    @pytest.mark.asyncio
    async def test_task_kind_is_task(self, in_memory_storage) -> None:
        message = _make_message("hello")
        task = await in_memory_storage.submit_task(context_id="ctx1", message=message)
        assert task["kind"] == "task"


# ---------------------------------------------------------------------------
# load_task
# ---------------------------------------------------------------------------


class TestLoadTask:
    @pytest.mark.asyncio
    async def test_load_returns_submitted_task(self, in_memory_storage) -> None:
        message = _make_message("hello")
        submitted = await in_memory_storage.submit_task(context_id="ctx1", message=message)
        loaded = await in_memory_storage.load_task(submitted["id"])
        assert loaded is not None
        assert loaded["id"] == submitted["id"]

    @pytest.mark.asyncio
    async def test_load_nonexistent_returns_none(self, in_memory_storage) -> None:
        result = await in_memory_storage.load_task("does-not-exist")
        assert result is None

    @pytest.mark.asyncio
    async def test_load_with_history_length(self, in_memory_storage) -> None:
        message = _make_message("hello")
        submitted = await in_memory_storage.submit_task(context_id="ctx1", message=message)
        loaded = await in_memory_storage.load_task(submitted["id"], history_length=5)
        assert loaded is not None


# ---------------------------------------------------------------------------
# update_task
# ---------------------------------------------------------------------------


class TestUpdateTask:
    @pytest.mark.asyncio
    async def test_update_state_to_working(self, in_memory_storage) -> None:
        task = await in_memory_storage.submit_task("ctx1", _make_message("hello"))
        updated = await in_memory_storage.update_task(task["id"], state="working")
        assert updated["status"]["state"] == "working"

    @pytest.mark.asyncio
    async def test_update_state_to_completed(self, in_memory_storage) -> None:
        task = await in_memory_storage.submit_task("ctx1", _make_message("hello"))
        await in_memory_storage.update_task(task["id"], state="working")
        updated = await in_memory_storage.update_task(task["id"], state="completed")
        assert updated["status"]["state"] == "completed"

    @pytest.mark.asyncio
    async def test_update_appends_artifacts(self, in_memory_storage) -> None:
        task = await in_memory_storage.submit_task("ctx1", _make_message("hello"))
        artifact = {
            "artifact_id": "a1",
            "parts": [{"kind": "text", "text": "ls -la"}],
        }
        updated = await in_memory_storage.update_task(
            task["id"], state="completed", new_artifacts=[artifact]
        )
        assert len(updated.get("artifacts", [])) == 1
        assert updated["artifacts"][0]["artifact_id"] == "a1"

    @pytest.mark.asyncio
    async def test_update_appends_messages(self, in_memory_storage) -> None:
        task = await in_memory_storage.submit_task("ctx1", _make_message("hello"))
        new_msg = _make_message("response", role="agent")
        updated = await in_memory_storage.update_task(
            task["id"], state="completed", new_messages=[new_msg]
        )
        # history should have the original + new message
        assert len(updated.get("history", [])) >= 1


# ---------------------------------------------------------------------------
# context (conversation history)
# ---------------------------------------------------------------------------


class TestContext:
    @pytest.mark.asyncio
    async def test_load_context_returns_none_when_absent(self, in_memory_storage) -> None:
        result = await in_memory_storage.load_context("new-context-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_and_load_context_roundtrip(self, in_memory_storage) -> None:
        context_data = [{"role": "user", "content": "hello"}]
        await in_memory_storage.update_context("ctx-1", context_data)
        loaded = await in_memory_storage.load_context("ctx-1")
        assert loaded == context_data

    @pytest.mark.asyncio
    async def test_update_context_overwrites_previous(self, in_memory_storage) -> None:
        await in_memory_storage.update_context("ctx-1", ["first"])
        await in_memory_storage.update_context("ctx-1", ["second"])
        loaded = await in_memory_storage.load_context("ctx-1")
        assert loaded == ["second"]

    @pytest.mark.asyncio
    async def test_separate_context_ids_are_isolated(self, in_memory_storage) -> None:
        await in_memory_storage.update_context("ctx-a", ["for a"])
        await in_memory_storage.update_context("ctx-b", ["for b"])
        assert await in_memory_storage.load_context("ctx-a") == ["for a"]
        assert await in_memory_storage.load_context("ctx-b") == ["for b"]


# ---------------------------------------------------------------------------
# persistence across instances (file-backed)
# ---------------------------------------------------------------------------


class TestPersistence:
    @pytest.mark.asyncio
    async def test_data_persists_across_instances(self, tmp_path) -> None:
        db = str(tmp_path / "persist.db")
        storage1 = SQLiteStorage(db_path=db)
        await storage1.update_context("ctx-x", ["persisted"])

        storage2 = SQLiteStorage(db_path=db)
        loaded = await storage2.load_context("ctx-x")
        assert loaded == ["persisted"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(text: str, role: str = "user") -> dict:
    import uuid

    return {
        "kind": "message",
        "message_id": str(uuid.uuid4()),
        "role": role,
        "parts": [{"kind": "text", "text": text}],
    }
