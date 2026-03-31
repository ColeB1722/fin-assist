"""AgentFactory: translates a BaseAgent into a fasta2a ASGI sub-application.

Responsibilities:
- Build a pydantic-ai ``Agent`` from the agent's ``system_prompt`` and ``output_type``.
- Call ``pydantic_agent.to_a2a()`` with the shared storage and broker.
- Inject ``AgentCardMeta`` as a reserved ``Skill`` (id ``"fin_assist:meta"``) so
  clients can read capabilities without fetching the agent card separately.

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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fasta2a.applications import FastA2A
    from fasta2a.broker import Broker
    from fasta2a.schema import Skill
    from fasta2a.storage import Storage

    from fin_assist.agents.base import BaseAgent


class AgentFactory:
    """Converts ``BaseAgent`` instances into mountable fasta2a sub-apps.

    Args:
        storage: Shared ``Storage`` instance (SQLite or in-memory).
        broker:  Shared ``Broker`` instance (``InMemoryBroker`` for local use).
    """

    def __init__(self, storage: Storage, broker: Broker) -> None:
        self._storage = storage
        self._broker = broker

    def create_a2a_app(self, agent: BaseAgent) -> FastA2A:
        """Build a fasta2a ASGI sub-app for a single agent.

        Steps:
        1. Build a pydantic-ai ``Agent`` from ``agent.system_prompt`` and
           ``agent.output_type``.
        2. Call ``.to_a2a()`` with shared storage/broker, agent name and
           description.
        3. Append a ``"fin_assist:meta"`` skill encoding ``AgentCardMeta`` so
           clients can read static UI capability hints.
        """
        from pydantic_ai import Agent as PydanticAgent

        pydantic_agent = PydanticAgent(
            "test",  # model placeholder — real model injected at runtime via credentials
            output_type=agent.output_type,
            instructions=agent.system_prompt,
        )

        meta = agent.agent_card_metadata
        meta_skill: Skill = {
            "id": "fin_assist:meta",
            "name": "fin_assist metadata",
            "description": json.dumps(meta.model_dump()),
            "tags": list(meta.tags),
            "input_modes": ["application/json"],
            "output_modes": ["application/json"],
        }

        app = pydantic_agent.to_a2a(
            storage=self._storage,
            broker=self._broker,
            name=agent.name,
            description=agent.description,
            skills=[meta_skill],
        )
        return app
