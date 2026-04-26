"""Shared protobuf helpers.

Thin wrappers around ``google.protobuf`` for converting A2A transport
types (``Struct``, ``Part`` metadata) to plain Python dicts.  Used by
both the hub (executor) and CLI (client).
"""

from __future__ import annotations

from typing import Any

from google.protobuf.json_format import MessageToDict


def struct_to_dict(struct) -> dict[str, Any]:
    """Convert a protobuf ``Struct`` to a plain Python dict.

    Returns an empty dict if *struct* is falsy or has no fields.
    """
    if not struct or not struct.fields:
        return {}
    return MessageToDict(struct, preserving_proto_field_name=True)
