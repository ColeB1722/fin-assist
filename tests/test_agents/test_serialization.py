"""Tests for the serialization-envelope helpers."""

from __future__ import annotations

import struct

import pytest

from fin_assist.agents.serialization import (
    CONTEXT_STORE_VERSION,
    unwrap_payload,
    wrap_payload,
)

_VERSION_PACK = struct.Struct("!B")


class TestWrapPayload:
    def test_prepends_version_byte(self) -> None:
        payload = b'{"data": true}'
        wrapped = wrap_payload(payload)
        version = _VERSION_PACK.unpack(wrapped[: _VERSION_PACK.size])[0]
        assert version == CONTEXT_STORE_VERSION

    def test_preserves_original_payload(self) -> None:
        payload = b'{"data": true}'
        wrapped = wrap_payload(payload)
        assert wrapped[_VERSION_PACK.size :] == payload

    def test_empty_payload(self) -> None:
        wrapped = wrap_payload(b"")
        assert wrapped == _VERSION_PACK.pack(CONTEXT_STORE_VERSION)


class TestUnwrapPayload:
    def test_strips_version_byte(self) -> None:
        payload = b"hello"
        wrapped = wrap_payload(payload)
        assert unwrap_payload(wrapped) == payload

    def test_rejects_wrong_version(self) -> None:
        bad_version = _VERSION_PACK.pack(255) + b"payload"
        with pytest.raises(ValueError, match="Unsupported context store version 255"):
            unwrap_payload(bad_version)

    def test_rejects_too_short(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            unwrap_payload(b"")


class TestRoundtrip:
    def test_binary_data_survives_roundtrip(self) -> None:
        payload = b"some binary data \x00\xff"
        assert unwrap_payload(wrap_payload(payload)) == payload

    def test_json_data_survives_roundtrip(self) -> None:
        payload = b'[{"role": "user", "content": "hi"}]'
        assert unwrap_payload(wrap_payload(payload)) == payload
