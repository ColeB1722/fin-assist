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


class TestPauseStatePersistence:
    """The pause state (trace_id + span_id + flags + user_input) of a
    paused task must outlive the process so that the resume task can
    link its new trace back to the ``approval_request`` span.
    """

    @pytest.mark.asyncio
    async def test_load_pause_state_returns_none_when_absent(self, in_memory_store) -> None:
        result = await in_memory_store.load_pause_state("never-saved")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_and_load_pause_state_roundtrip(self, in_memory_store) -> None:
        trace_id = 0x1234567890ABCDEF1234567890ABCDEF
        span_id = 0xFEDCBA0987654321
        flags = 0x01
        await in_memory_store.save_pause_state(
            context_id="ctx-1",
            trace_id=trace_id,
            span_id=span_id,
            trace_flags=flags,
            user_input="list files",
        )

        state = await in_memory_store.load_pause_state("ctx-1")
        assert state is not None
        assert state.trace_id == trace_id
        assert state.span_id == span_id
        assert state.trace_flags == flags
        assert state.user_input == "list files"

    @pytest.mark.asyncio
    async def test_save_pause_state_overwrites(self, in_memory_store) -> None:
        await in_memory_store.save_pause_state(
            context_id="ctx-1", trace_id=0xAA, span_id=0xBB, trace_flags=0x01, user_input="first"
        )
        await in_memory_store.save_pause_state(
            context_id="ctx-1", trace_id=0xCC, span_id=0xDD, trace_flags=0x00, user_input="second"
        )
        state = await in_memory_store.load_pause_state("ctx-1")
        assert state is not None
        assert state.trace_id == 0xCC
        assert state.span_id == 0xDD
        assert state.trace_flags == 0x00
        assert state.user_input == "second"

    @pytest.mark.asyncio
    async def test_pause_state_persists_across_instances(self, tmp_path) -> None:
        db = str(tmp_path / "pause_persist.db")
        store1 = ContextStore(db_path=db)
        await store1.save_pause_state(
            context_id="ctx-x", trace_id=0x1111, span_id=0x2222, trace_flags=0x01, user_input="test"
        )

        store2 = ContextStore(db_path=db)
        state = await store2.load_pause_state("ctx-x")
        assert state is not None
        assert state.trace_id == 0x1111
        assert state.span_id == 0x2222
        assert state.trace_flags == 0x01
        assert state.user_input == "test"

    @pytest.mark.asyncio
    async def test_pause_state_independent_of_history(self, in_memory_store) -> None:
        await in_memory_store.save("ctx-1", b"history-blob")
        await in_memory_store.save_pause_state(
            context_id="ctx-1", trace_id=0x1, span_id=0x2, trace_flags=0x01, user_input="prompt"
        )

        assert await in_memory_store.load("ctx-1") == b"history-blob"
        state = await in_memory_store.load_pause_state("ctx-1")
        assert state is not None
        assert state.trace_id == 0x1
        assert state.span_id == 0x2
        assert state.trace_flags == 0x01
