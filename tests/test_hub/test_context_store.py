"""Tests for ContextStore — SQLite-backed opaque byte storage."""

from __future__ import annotations

import pytest

from fin_assist.hub.context_store import ContextStore


@pytest.fixture
def in_memory_store() -> ContextStore:
    return ContextStore(db_path=":memory:")


class TestLoad:
    @pytest.mark.asyncio
    async def test_returns_none_when_absent(self, in_memory_store) -> None:
        result = await in_memory_store.load("new-context-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_saved_bytes(self, in_memory_store) -> None:
        await in_memory_store.save("ctx-1", b'{"data": "test"}')
        loaded = await in_memory_store.load("ctx-1")
        assert loaded is not None
        assert loaded == b'{"data": "test"}'


class TestSave:
    @pytest.mark.asyncio
    async def test_overwrites_previous(self, in_memory_store) -> None:
        await in_memory_store.save("ctx-1", b"first")
        await in_memory_store.save("ctx-1", b"second")
        loaded = await in_memory_store.load("ctx-1")
        assert loaded == b"second"

    @pytest.mark.asyncio
    async def test_separate_context_ids_are_isolated(self, in_memory_store) -> None:
        await in_memory_store.save("ctx-a", b"data-a")
        await in_memory_store.save("ctx-b", b"data-b")
        loaded_a = await in_memory_store.load("ctx-a")
        loaded_b = await in_memory_store.load("ctx-b")
        assert loaded_a == b"data-a"
        assert loaded_b == b"data-b"


class TestPersistence:
    @pytest.mark.asyncio
    async def test_data_persists_across_instances(self, tmp_path) -> None:
        db = str(tmp_path / "persist.db")
        store1 = ContextStore(db_path=db)
        await store1.save("ctx-x", b"persisted")

        store2 = ContextStore(db_path=db)
        loaded = await store2.load("ctx-x")
        assert loaded == b"persisted"
