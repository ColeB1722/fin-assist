"""Version-envelope helpers for serialized agent state.

Backends serialize conversation history into opaque ``bytes`` that the
hub's ``ContextStore`` persists.  The envelope defined here prefixes
those bytes with a single version byte so that future schema changes
can be migrated rather than crashing inside the backend's validator.

Callers:

- Backends wrap the serialized payload before returning it from
  ``AgentBackend.serialize_history``.
- Backends unwrap the payload before handing it to their framework's
  validator in ``AgentBackend.deserialize_history``.
- ``ContextStore`` treats stored bytes as opaque and does **not** read
  the envelope — it's serialization-layer concern, not storage-layer.

Increment ``CONTEXT_STORE_VERSION`` when the underlying serialization
format changes.  Old blobs will fail ``unwrap_payload`` with a
``ValueError`` — catch that in a migration step if backwards
compatibility is needed.

This module has **zero** framework dependencies so it can be imported
from any layer (platform or transport).
"""

from __future__ import annotations

import struct

#: Current envelope version.  Increment on serialization format changes.
CONTEXT_STORE_VERSION = 1

#: Packing for the single version byte (big-endian unsigned char).
_VERSION_PACK = struct.Struct("!B")


def wrap_payload(data: bytes) -> bytes:
    """Prefix *data* with the current version byte."""
    return _VERSION_PACK.pack(CONTEXT_STORE_VERSION) + data


def unwrap_payload(data: bytes) -> bytes:
    """Strip and validate the version byte prefix from *data*.

    Raises:
        ValueError: If *data* is shorter than the envelope or the version
            byte does not match ``CONTEXT_STORE_VERSION``.
    """
    if len(data) < _VERSION_PACK.size:
        raise ValueError(f"Context store data too short ({len(data)} bytes)")
    version = _VERSION_PACK.unpack(data[: _VERSION_PACK.size])[0]
    if version != CONTEXT_STORE_VERSION:
        raise ValueError(f"Unsupported context store version {version}")
    return data[_VERSION_PACK.size :]
