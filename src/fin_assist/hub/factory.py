"""AgentFactory: translates a ConfigAgent into a fasta2a ASGI sub-application.

Constructs ``FastA2A`` directly with a ``FinAssistWorker``, eliminating the
wasted default ``AgentWorker`` that ``pydantic_agent.to_a2a()`` creates.

AgentCardMeta transport — why a Skill, not an AgentCapabilities extension
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The A2A spec (protocol version 0.3.0) defines ``AgentCapabilities.extensions`` as
the correct place to publish structured per-agent metadata.  Extensions support
is implemented in pydantic/fasta2a PR #44 (not merged as of fasta2a 0.6.0).

Until that PR lands, we encode ``AgentCardMeta`` inside a reserved ``Skill``
entry (id ``"fin_assist:meta"``).  Clients discover it by filtering
``agent_card["skills"]`` on that id and JSON-parsing the ``description`` field.

Migration path once fasta2a >= 0.7 (or whatever ships extensions):
1. Replace the ``meta_skill`` block with an ``AgentExtension`` dict.
2. Pass it via ``FastA2A(capabilities=AgentCapabilities(extensions=[...]))``.
3. Update ``cli/client.py`` to read from ``capabilities.extensions`` instead.
4. Bump ``fasta2a>=0.7`` in ``pyproject.toml``.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fasta2a.applications import FastA2A
    from fasta2a.schema import Skill
    from fasta2a.storage import Storage

    from fin_assist.agents.agent import ConfigAgent


@asynccontextmanager
async def _worker_lifespan(
    app: FastA2A,
    *,
    worker,
) -> AsyncIterator[None]:
    """Custom lifespan that starts ``FinAssistWorker`` and the task manager."""
    async with app.task_manager, worker.run():
        yield


class AgentFactory:
    """Converts ``ConfigAgent`` instances into mountable fasta2a sub-apps.

    Args:
        storage: Shared ``Storage`` instance (SQLite or in-memory).
    """

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def create_a2a_app(self, agent: ConfigAgent) -> FastA2A:
        """Build a fasta2a ASGI sub-app for a single agent.

        Constructs ``FastA2A`` directly with a ``FinAssistWorker`` — no
        ``pydantic_agent.to_a2a()`` is called, so there's no wasted default
        ``AgentWorker`` construction.

        Each agent gets its own ``InMemoryBroker`` so its worker only receives
        tasks routed to that specific agent endpoint.  Storage is shared
        (tasks are keyed by unique ID).
        """
        from fasta2a.applications import FastA2A
        from fasta2a.broker import InMemoryBroker

        from fin_assist.hub.worker import FinAssistWorker

        meta = agent.agent_card_metadata
        meta_skill: Skill = {
            "id": "fin_assist:meta",
            "name": "fin_assist metadata",
            "description": json.dumps(meta.model_dump()),
            "tags": list(meta.tags),
            "input_modes": ["application/json"],
            "output_modes": ["application/json"],
        }

        broker = InMemoryBroker()
        worker = FinAssistWorker(
            agent=agent,
            broker=broker,
            storage=self._storage,
        )

        app = FastA2A(
            storage=self._storage,
            broker=broker,
            name=agent.name,
            description=agent.description,
            skills=[meta_skill],
            lifespan=lambda app: _worker_lifespan(app, worker=worker),
        )
        return app
