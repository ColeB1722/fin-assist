"""AgentFactory: translates a BaseAgent into a fasta2a ASGI sub-application.

Responsibilities:
- Build a pydantic-ai ``Agent`` from the agent's ``system_prompt`` and ``output_type``.
- Call ``pydantic_agent.to_a2a()`` with the shared storage and broker.
- Inject ``AgentCardMeta`` as a reserved ``Skill`` (id ``"fin_assist:meta"``) so
  clients can read capabilities without fetching the agent card separately.
- Use ``FinAssistWorker`` (via a custom lifespan) instead of fasta2a's default
  ``AgentWorker``, so that ``MissingCredentialsError`` maps to the A2A
  ``auth-required`` task state rather than a generic ``failed``.

AgentCardMeta transport — why a Skill, not an AgentCapabilities extension
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The A2A spec (protocol version 0.3.0) defines ``AgentCapabilities.extensions`` as
the correct place to publish structured per-agent metadata:

    AgentCapabilities(extensions=[
        AgentExtension(
            uri="https://fin-assist.local/ext/agent-meta/v1",
            params=meta.model_dump(),
        )
    ])

``AgentExtension`` is already defined in ``fasta2a.schema``, but
``AgentCapabilities`` does not yet expose an ``extensions`` field, and
``FastA2A.__init__`` does not accept one.  Extensions support is implemented in
pydantic/fasta2a PR #44 (opened 2026-03-07, not merged as of fasta2a 0.6.0) —
deliberately held back, bundled with the streaming feature.

Until that PR lands and a new fasta2a release ships, we encode ``AgentCardMeta``
inside a reserved ``Skill`` entry (id ``"fin_assist:meta"``).  Clients discover
it by filtering ``agent_card["skills"]`` on that id and JSON-parsing the
``description`` field.

Migration path once fasta2a >= 0.7 (or whatever ships extensions):
1. Replace the ``meta_skill`` block below with an ``AgentExtension`` dict.
2. Pass it via ``FastA2A(capabilities=AgentCapabilities(extensions=[...]))``.
3. Update ``cli/client.py`` to read from ``capabilities.extensions`` instead.
4. Bump ``fasta2a>=0.7`` in ``pyproject.toml``.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from functools import partial
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fasta2a.applications import FastA2A
    from fasta2a.schema import Skill
    from fasta2a.storage import Storage

    from fin_assist.agents.base import BaseAgent


@asynccontextmanager
async def _worker_lifespan(
    app: FastA2A,
    *,
    worker,
    pydantic_agent,
) -> AsyncIterator[None]:
    """Custom lifespan that starts ``FinAssistWorker`` instead of fasta2a's default.

    Mirrors ``pydantic_ai._a2a.worker_lifespan`` but injects our worker subclass
    which maps ``MissingCredentialsError`` to ``auth-required`` task state.
    """
    async with app.task_manager, pydantic_agent, worker.run():
        yield


class AgentFactory:
    """Converts ``BaseAgent`` instances into mountable fasta2a sub-apps.

    Args:
        storage: Shared ``Storage`` instance (SQLite or in-memory).
    """

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def create_a2a_app(self, agent: BaseAgent) -> FastA2A:
        """Build a fasta2a ASGI sub-app for a single agent.

        Steps:
        1. Build a pydantic-ai ``Agent`` via ``agent.build_pydantic_agent()``.
        2. Call ``.to_a2a()`` with shared storage, a per-agent broker, and a
           **custom lifespan** that starts ``FinAssistWorker``.
        3. Append a ``"fin_assist:meta"`` skill encoding ``AgentCardMeta`` so
           clients can read static UI capability hints.

        Each agent gets its own ``InMemoryBroker`` so its worker only receives
        tasks routed to that specific agent endpoint.  Storage is shared
        (tasks are keyed by unique ID).

        ``FinAssistWorker`` replaces fasta2a's default ``AgentWorker`` so that
        ``MissingCredentialsError`` (raised when API keys are absent) produces
        ``auth-required`` task state with a helpful message, rather than a
        generic ``failed``.
        """
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

        pydantic_agent = agent.build_pydantic_agent()
        broker = InMemoryBroker()
        worker = FinAssistWorker(
            pydantic_agent=pydantic_agent,
            broker=broker,
            storage=self._storage,
            agent_def=agent,
        )

        app = pydantic_agent.to_a2a(
            storage=self._storage,
            broker=broker,
            name=agent.name,
            description=agent.description,
            skills=[meta_skill],
            lifespan=partial(
                _worker_lifespan,
                worker=worker,
                pydantic_agent=pydantic_agent,
            ),
        )
        return app
