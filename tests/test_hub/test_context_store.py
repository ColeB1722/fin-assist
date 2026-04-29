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


class TestTraceContextPersistence:
    """The trace context (trace_id + span_id + flags) of a paused task
    must outlive the process so that the resume task can link its new
    trace back to the ``approval_request`` span.

    Without persistence, approval pause → resume splits into two
    unrelated traces, which is exactly the Phoenix UX bug we're
    fixing.  Stored separately from the opaque ``data`` blob so the
    backend's history serialization stays framework-specific while
    trace plumbing stays platform-level.
    """

    @pytest.mark.asyncio
    async def test_load_trace_context_returns_none_when_absent(self, in_memory_store) -> None:
        result = await in_memory_store.load_trace_context("never-saved")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_and_load_trace_context_roundtrip(self, in_memory_store) -> None:
        trace_id = 0x1234567890ABCDEF1234567890ABCDEF
        span_id = 0xFEDCBA0987654321
        flags = 0x01  # sampled
        await in_memory_store.save_trace_context("ctx-1", trace_id, span_id, flags)

        loaded = await in_memory_store.load_trace_context("ctx-1")
        assert loaded == (trace_id, span_id, flags)

    @pytest.mark.asyncio
    async def test_save_trace_context_overwrites(self, in_memory_store) -> None:
        """A fresh pause on the same context replaces the prior trace
        context.  Only the most recent paused approval is relevant for
        the resume link."""
        await in_memory_store.save_trace_context("ctx-1", 0xAA, 0xBB, 0x01)
        await in_memory_store.save_trace_context("ctx-1", 0xCC, 0xDD, 0x00)
        loaded = await in_memory_store.load_trace_context("ctx-1")
        assert loaded == (0xCC, 0xDD, 0x00)

    @pytest.mark.asyncio
    async def test_trace_context_persists_across_instances(self, tmp_path) -> None:
        """The whole point of persistence: a process restart between pause
        and resume must not lose the link."""
        db = str(tmp_path / "trace_persist.db")
        store1 = ContextStore(db_path=db)
        await store1.save_trace_context("ctx-x", 0x1111, 0x2222, 0x01)

        store2 = ContextStore(db_path=db)
        loaded = await store2.load_trace_context("ctx-x")
        assert loaded == (0x1111, 0x2222, 0x01)

    @pytest.mark.asyncio
    async def test_trace_context_independent_of_history(self, in_memory_store) -> None:
        """Trace context and opaque history are independent keys on the
        same context_id: saving one doesn't erase the other."""
        await in_memory_store.save("ctx-1", b"history-blob")
        await in_memory_store.save_trace_context("ctx-1", 0x1, 0x2, 0x01)

        assert await in_memory_store.load("ctx-1") == b"history-blob"
        assert await in_memory_store.load_trace_context("ctx-1") == (0x1, 0x2, 0x01)
