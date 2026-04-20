"""Agent Hub — parent FastAPI application.

Mounts each registered agent as a FastAPI sub-app at ``/agents/{name}/``.
Adds two top-level endpoints:

- ``GET /health``  — liveness check
- ``GET /agents``  — discovery: lists all mounted agents with their card URL
                      and decoded ``AgentCardMeta`` so clients don't need to
                      fetch every agent card separately.

The parent app is FastAPI (matching the sub-apps from a2a-sdk). Each
sub-app owns its own lifecycle — no manual lifespan orchestration needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from google.protobuf.json_format import MessageToDict

from fin_assist.hub.context_store import ContextStore
from fin_assist.hub.factory import AgentFactory

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fin_assist.agents.agent import ConfigAgent


def _extract_card_meta(sub_app: FastAPI) -> dict:
    """Extract AgentCardMeta from the agent card's extensions."""
    card = getattr(sub_app.state, "agent_card", None)
    if card is None:
        return {}
    for ext in card.capabilities.extensions:
        if ext.uri == "fin_assist:meta":
            return MessageToDict(ext.params, preserving_proto_field_name=True)
    return {}


def create_hub_app(
    agents: Sequence[ConfigAgent] | None = None,
    db_path: str = ":memory:",
    base_url: str = "http://127.0.0.1:4096",
) -> FastAPI:
    """Build and return the parent FastAPI hub application.

    Args:
        agents:   List of initialised ``ConfigAgent`` instances to mount.
                  If ``None`` an empty hub is created.
        db_path:  SQLite database path for conversation context storage.
                  Defaults to ``":memory:"`` (tests); production should
                  pass ``~/.local/share/fin/hub.db``.
        base_url: Public base URL used to construct per-agent card URLs
                  in the ``/agents`` discovery response.
    """
    agents = agents or []
    context_store = ContextStore(db_path=db_path)
    factory = AgentFactory(context_store=context_store)

    app = FastAPI(
        title="fin-assist Agent Hub",
        docs_url=None,
        redoc_url=None,
    )

    mounted_agents: list[dict] = []

    @app.get("/health")
    async def health_endpoint() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/agents")
    async def discovery_endpoint() -> JSONResponse:
        return JSONResponse({"agents": mounted_agents})

    for agent in agents:
        sub_app = factory.create_a2a_app(agent, base_url=base_url)
        mount_path = f"/agents/{agent.name}"
        app.mount(mount_path, sub_app)

        card_meta = _extract_card_meta(sub_app)
        mounted_agents.append(
            {
                "name": agent.name,
                "description": agent.description,
                "url": f"{base_url}/agents/{agent.name}/",
                "card_meta": card_meta,
            }
        )

    return app
