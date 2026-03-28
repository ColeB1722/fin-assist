from __future__ import annotations

from starlette.applications import Starlette


def create_hub_app() -> Starlette:
    return Starlette()
