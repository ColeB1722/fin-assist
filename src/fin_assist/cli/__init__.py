"""CLI client package.

This package intentionally exposes no symbols at the top level.  Import
directly from submodules (``fin_assist.cli.client``,
``fin_assist.cli.server``, etc.) so that ``from fin_assist.cli import …``
cannot transitively trigger the ``fin_assist.agents.backend`` →
``pydantic_ai`` import chain (~1s) when the caller only needs a
lightweight type.
"""
