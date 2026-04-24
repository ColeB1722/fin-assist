"""Tests for ContextStore — SQLite-backed opaque byte storage."""

from __future__ import annotations

import struct

import pytest

from fin_assist.hub.context_store import _CONTEXT_STORE_VERSION, ContextStore

_VERSION_PACK = struct.Struct("!B")


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


class TestVersionByte:
    def test_wrap_payload_prepends_version(self) -> None:
        payload = b'{"data": true}'
        wrapped = ContextStore.wrap_payload(payload)
        version = _VERSION_PACK.unpack(wrapped[:1])[0]
        assert version == _CONTEXT_STORE_VERSION
        assert wrapped[1:] == payload

    def test_unwrap_payload_strips_version(self) -> None:
        payload = b"hello"
        wrapped = ContextStore.wrap_payload(payload)
        assert ContextStore.unwrap_payload(wrapped) == payload

    def test_unwrap_payload_rejects_wrong_version(self) -> None:
        bad_version = _VERSION_PACK.pack(255) + b"payload"
        with pytest.raises(ValueError, match="Unsupported context store version 255"):
            ContextStore.unwrap_payload(bad_version)

    def test_unwrap_payload_rejects_too_short(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            ContextStore.unwrap_payload(b"")

    def test_roundtrip(self) -> None:
        payload = b"some binary data \x00\xff"
        assert ContextStore.unwrap_payload(ContextStore.wrap_payload(payload)) == payload
