"""Tests for ContextStore — SQLite-backed conversation history."""

from __future__ import annotations

import pytest
from pydantic_ai import ModelRequest, UserPromptPart

from fin_assist.hub.context_store import ContextStore


@pytest.fixture
def store(tmp_path) -> ContextStore:
    return ContextStore(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def in_memory_store() -> ContextStore:
    return ContextStore(db_path=":memory:")


class TestLoad:
    @pytest.mark.asyncio
    async def test_returns_none_when_absent(self, in_memory_store) -> None:
        result = await in_memory_store.load("new-context-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_saved_messages(self, in_memory_store) -> None:
        context = [ModelRequest(parts=[UserPromptPart(content="hello")])]
        await in_memory_store.save("ctx-1", context)
        loaded = await in_memory_store.load("ctx-1")
        assert loaded is not None
        assert len(loaded) == 1
        assert isinstance(loaded[0], ModelRequest)


class TestSave:
    @pytest.mark.asyncio
    async def test_overwrites_previous(self, in_memory_store) -> None:
        first = [ModelRequest(parts=[UserPromptPart(content="first")])]
        second = [ModelRequest(parts=[UserPromptPart(content="second")])]
        await in_memory_store.save("ctx-1", first)
        await in_memory_store.save("ctx-1", second)
        loaded = await in_memory_store.load("ctx-1")
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0].parts[0].content == "second"

    @pytest.mark.asyncio
    async def test_separate_context_ids_are_isolated(self, in_memory_store) -> None:
        ctx_a = [ModelRequest(parts=[UserPromptPart(content="for a")])]
        ctx_b = [ModelRequest(parts=[UserPromptPart(content="for b")])]
        await in_memory_store.save("ctx-a", ctx_a)
        await in_memory_store.save("ctx-b", ctx_b)
        loaded_a = await in_memory_store.load("ctx-a")
        loaded_b = await in_memory_store.load("ctx-b")
        assert loaded_a is not None
        assert loaded_a[0].parts[0].content == "for a"
        assert loaded_b is not None
        assert loaded_b[0].parts[0].content == "for b"


class TestPersistence:
    @pytest.mark.asyncio
    async def test_data_persists_across_instances(self, tmp_path) -> None:
        db = str(tmp_path / "persist.db")
        store1 = ContextStore(db_path=db)
        context = [ModelRequest(parts=[UserPromptPart(content="persisted")])]
        await store1.save("ctx-x", context)

        store2 = ContextStore(db_path=db)
        loaded = await store2.load("ctx-x")
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0].parts[0].content == "persisted"
