"""AgentFactory: translates an AgentSpec into a FastAPI sub-application.

Uses the a2a-sdk's route factories (``create_jsonrpc_routes``,
``create_agent_card_routes``) to construct a per-agent ASGI sub-app.
Each sub-app is a FastAPI application that handles:

- ``GET /.well-known/agent-card.json`` — agent card with extensions
- ``POST /`` — JSON-RPC endpoint (message/send, tasks/get, etc.)

AgentCardMeta transport
~~~~~~~~~~~~~~~~~~~~~~~
``AgentCardMeta`` is published as an ``AgentExtension`` in
``AgentCapabilities.extensions``, keyed by the ``fin_assist:meta`` URI.
The extension ``params`` field carries the serialised ``AgentCardMeta``
as a protobuf Struct, which is the idiomatic a2a-sdk pattern.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentExtension,
    AgentInterface,
    AgentProvider,
    AgentSkill,
)
from fastapi import FastAPI
from google.protobuf.struct_pb2 import Struct

from fin_assist.agents.backend import PydanticAIBackend
from fin_assist.hub.executor import Executor

if TYPE_CHECKING:
    from fin_assist.agents.backend import AgentBackend
    from fin_assist.agents.spec import AgentSpec
    from fin_assist.hub.context_store import ContextStore


class AgentFactory:
    """Converts ``AgentSpec`` instances into mountable FastAPI sub-apps.

    Args:
        context_store: Shared ``ContextStore`` instance for conversation history.
    """

    def __init__(self, context_store: ContextStore) -> None:
        self._context_store = context_store

    def create_a2a_app(
        self,
        agent: AgentSpec,
        *,
        base_url: str = "http://127.0.0.1:4096",
        backend: AgentBackend | None = None,
    ) -> FastAPI:
        """Build a FastAPI sub-app for a single agent.

        Constructs an ``AgentCard`` with proper extensions, creates a
        ``Executor`` and ``InMemoryTaskStore``, wires them
        through ``DefaultRequestHandler``, and returns a FastAPI app
        with the A2A JSON-RPC and agent-card routes mounted.

        Args:
            agent: The ``AgentSpec`` to serve.
            base_url: Public base URL used in the agent card's supported
                      interfaces.
            backend: Optional pre-constructed ``AgentBackend``.  When
                     ``None`` (default) a ``PydanticAIBackend`` is created
                     from *agent*.  Inject a fake for integration tests.
        """
        meta = agent.agent_card_metadata
        meta_struct = Struct()
        meta_struct.update(meta.model_dump())

        agent_card = AgentCard(
            name=agent.name,
            description=agent.description,
            version="1.0.0",
            provider=AgentProvider(organization="fin-assist"),
            capabilities=AgentCapabilities(
                streaming=True,
                extensions=[
                    AgentExtension(
                        uri="fin_assist:meta",
                        params=meta_struct,
                    )
                ],
            ),
            default_input_modes=["text/plain"],
            default_output_modes=["text/plain", "application/json"],
            skills=[
                AgentSkill(
                    id=agent.name,
                    name=agent.name,
                    description=agent.description,
                    tags=list(meta.tags),
                )
            ],
            supported_interfaces=[
                AgentInterface(
                    url=f"{base_url}/agents/{agent.name}/",
                    protocol_binding="JSONRPC",
                ),
            ],
        )

        backend = backend or PydanticAIBackend(agent_spec=agent)
        executor = Executor(
            backend=backend,
            context_store=self._context_store,
        )
        task_store = InMemoryTaskStore()
        request_handler = DefaultRequestHandler(
            agent_executor=executor,
            task_store=task_store,
            agent_card=agent_card,
        )

        app = FastAPI(
            title=f"fin-assist: {agent.name}",
            docs_url=None,
            redoc_url=None,
        )
        app.routes.extend(create_agent_card_routes(agent_card))
        app.routes.extend(create_jsonrpc_routes(request_handler, rpc_url="/"))

        app.state.agent_card = agent_card
        return app
