"""Shared protobuf helpers.

Thin wrappers around ``google.protobuf`` for converting A2A transport
types (``Struct``, ``Part`` metadata) to plain Python dicts.  Used by
both the hub (executor) and CLI (client).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from google.protobuf.json_format import MessageToDict

if TYPE_CHECKING:
    from google.protobuf.struct_pb2 import Struct


def struct_to_dict(struct: Struct | None) -> dict[str, Any]:
    """Convert a protobuf ``Struct`` to a plain Python dict.

    Returns an empty dict if *struct* is falsy or has no fields.
    """
    if not struct or not struct.fields:
        return {}
    return MessageToDict(struct, preserving_proto_field_name=True)
