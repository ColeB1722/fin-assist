"""Agent Hub — parent Starlette ASGI application.

Mounts each registered agent as a fasta2a sub-app at ``/agents/{name}/``.
Adds two top-level endpoints:

- ``GET /health``  — liveness check
- ``GET /agents``  — discovery: lists all mounted agents with their card URL and
                     decoded ``AgentCardMeta`` so clients don't need to fetch
                     every agent card separately.

Lifespan note
~~~~~~~~~~~~~
Starlette does not cascade ``lifespan`` events into mounted sub-apps.  Each
``FastA2A`` sub-app relies on its own lifespan to initialise its
``TaskManager`` (and broker connection).  We work around this by collecting all
``FastA2A`` instances and running their ``task_manager`` context managers in a
single parent lifespan.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fasta2a.broker import InMemoryBroker
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from fin_assist.hub.factory import AgentFactory
from fin_assist.hub.storage import SQLiteStorage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fasta2a.applications import FastA2A
    from starlette.requests import Request

    from fin_assist.agents.base import BaseAgent


def create_hub_app(
    agents: list[BaseAgent] | None = None,
    db_path: str = ":memory:",
    base_url: str = "http://127.0.0.1:4096",
) -> Starlette:
    """Build and return the parent Starlette hub application.

    Args:
        agents:   List of initialised ``BaseAgent`` instances to mount.
                  If ``None`` an empty hub is created.
        db_path:  SQLite database path.  Defaults to ``":memory:"`` (tests);
                  production should pass ``~/.local/share/fin/hub.db``.
        base_url: Public base URL used to construct per-agent card URLs in the
                  ``/agents`` discovery response.
    """
    agents = agents or []
    storage = SQLiteStorage(db_path=db_path)
    broker = InMemoryBroker()
    factory = AgentFactory(storage=storage, broker=broker)

    # Build per-agent sub-apps and collect metadata for discovery
    sub_apps: list[FastA2A] = []
    mounted_agents: list[dict] = []
    routes: list[Route | Mount] = [
        Route("/health", _health_endpoint, methods=["GET"]),
        Route("/agents", _make_discovery_endpoint(mounted_agents), methods=["GET"]),
    ]

    for agent in agents:
        sub_app = factory.create_a2a_app(agent)
        sub_apps.append(sub_app)
        mount_path = f"/agents/{agent.name}"
        routes.append(Mount(mount_path, app=sub_app))

        meta_skill = next((s for s in sub_app.skills if s["id"] == "fin_assist:meta"), None)
        try:
            card_meta = json.loads(meta_skill["description"]) if meta_skill else {}
        except json.JSONDecodeError:
            card_meta = {}

        mounted_agents.append(
            {
                "name": agent.name,
                "description": agent.description,
                "url": f"{base_url}/agents/{agent.name}/",
                "card_meta": card_meta,
            }
        )

    @asynccontextmanager
    async def _lifespan(app: Starlette) -> AsyncIterator[None]:
        # Manually start each sub-app's TaskManager so fasta2a is ready to serve
        async with _all_task_managers(sub_apps):
            yield

    return Starlette(routes=routes, lifespan=_lifespan)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _all_task_managers(sub_apps: list[FastA2A]) -> AsyncIterator[None]:
    """Enter all sub-app task managers in sequence."""
    if not sub_apps:
        yield
        return

    async with sub_apps[0].task_manager:
        if len(sub_apps) > 1:
            async with _all_task_managers(sub_apps[1:]):
                yield
        else:
            yield


# ---------------------------------------------------------------------------
# Endpoint handlers
# ---------------------------------------------------------------------------


async def _health_endpoint(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def _make_discovery_endpoint(mounted_agents: list[dict]):
    async def _discovery_endpoint(request: Request) -> JSONResponse:
        return JSONResponse({"agents": mounted_agents})

    return _discovery_endpoint
