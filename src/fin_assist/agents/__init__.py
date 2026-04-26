"""Agent protocol, registry, and implementations.

This package intentionally exposes no symbols at the top level.  Import
directly from submodules (``fin_assist.agents.metadata``,
``fin_assist.agents.spec``, ``fin_assist.agents.backend``, etc.) so that
callers who only need lightweight metadata types do not transitively
pay the cost of importing ``pydantic_ai`` / ``fastmcp`` / ``mcp`` /
``beartype`` via ``backend``.  That chain takes ~1s at import time on a
warm cache and is only needed when actually constructing/using a
backend.
"""
