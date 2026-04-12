"""Custom AgentWorker that maps MissingCredentialsError to ``auth-required``.

fasta2a's default ``AgentWorker`` catches all exceptions from the pydantic-ai
agent and sets the task state to ``"failed"``.  This subclass intercepts
``MissingCredentialsError`` — raised by ``BaseAgent.build_model()`` when
required API keys are missing — and sets ``"auth-required"`` instead, with an
agent message explaining which providers need credentials.

The model is built lazily at request time (not at hub startup) so the hub
can start and serve discovery/health endpoints even when credentials are not
yet configured.

All other exceptions propagate normally and result in ``"failed"`` via the
parent's exception handling.

Why two "agent" objects?
~~~~~~~~~~~~~~~~~~~~~~~~
This worker holds two references that both relate to the concept of "agent":

- ``agent_def`` (a ``BaseAgent``) — the **domain definition**: config,
  credentials, provider registry, metadata, model building.  This is *our*
  abstraction.
- ``pydantic_agent`` (a pydantic-ai ``Agent``) — the **framework executor**:
  runs the LLM conversation loop, manages tools and message history.  This is
  pydantic-ai's abstraction.

The split exists because fasta2a's ``AgentWorker`` has no dependency-injection
seam (``agent_to_a2a()`` doesn't accept ``deps`` or ``deps_factory`` — see
pydantic/pydantic-ai#4101 and #2910).  Once upstream ships ``deps_factory``
support, ``agent_def`` can become the pydantic-ai ``deps`` type and this
worker can collapse into configuration rather than a subclass.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

# TECH DEBT: importing from a private module. See #68 for context
# and migration plan. Pin pydantic-ai to prevent silent breakage.
from pydantic_ai._a2a import AgentWorker

from fin_assist.agents.base import MissingCredentialsError

if TYPE_CHECKING:
    from fasta2a.broker import Broker
    from fasta2a.schema import Message, TaskSendParams
    from fasta2a.storage import Storage

    from fin_assist.agents.base import BaseAgent


class FinAssistWorker(AgentWorker[Any, Any]):
    """Worker that gracefully handles missing credentials.

    Accepts an ``agent_def`` (the domain-level ``BaseAgent``) alongside the
    pydantic-ai ``Agent`` (the LLM executor).  On each task, calls
    ``agent_def.build_model()`` to construct the LLM model lazily, then passes
    it to ``pydantic_agent.run(model=...)``.  This defers credential
    validation to request time so the hub can start without API keys.

    If ``build_model()`` raises ``MissingCredentialsError``, the task is set
    to ``auth-required`` with a helpful message instead of crashing the hub.
    """

    def __init__(
        self,
        *,
        pydantic_agent: Any,
        broker: Broker,
        storage: Storage,
        agent_def: BaseAgent,
    ) -> None:
        super().__init__(agent=pydantic_agent, broker=broker, storage=storage)
        self._agent_def = agent_def

    async def run_task(self, params: TaskSendParams) -> None:
        task = await self.storage.load_task(params["id"])
        if task is None:
            raise ValueError(f"Task {params['id']} not found")

        if task["status"]["state"] != "submitted":
            raise ValueError(
                f"Task {params['id']} has already been processed (state: {task['status']['state']})"
            )

        await self.storage.update_task(task["id"], state="working")

        message_history = await self.storage.load_context(task["context_id"]) or []
        message_history.extend(self.build_message_history(task.get("history", [])))

        try:
            model = self._agent_def.build_model()
        except MissingCredentialsError as exc:
            # Graceful auth failure — not a crash, just missing config.
            agent_msg: Message = {
                "role": "agent",
                "parts": [{"kind": "text", "text": str(exc)}],
                "kind": "message",
                "message_id": str(uuid.uuid4()),
            }
            await self.storage.update_task(
                task["id"],
                state="auth-required",
                new_messages=[agent_msg],
            )
            return  # Handled — don't re-raise

        try:
            result = await self.agent.run(model=model, message_history=message_history)  # type: ignore[arg-type]
        except Exception:
            await self.storage.update_task(task["id"], state="failed")
            raise

        # Success path — mirrors AgentWorker.run_task() logic
        await self.storage.update_context(task["context_id"], result.all_messages())

        from pydantic_ai.messages import ModelRequest

        a2a_messages: list[Message] = []
        for message in result.new_messages():
            if isinstance(message, ModelRequest):
                continue
            a2a_parts = self._response_parts_to_a2a(message.parts)
            if a2a_parts:
                a2a_messages.append(
                    {
                        "role": "agent",
                        "parts": a2a_parts,
                        "kind": "message",
                        "message_id": str(uuid.uuid4()),
                    }
                )

        artifacts = self.build_artifacts(result.output)
        await self.storage.update_task(
            task["id"],
            state="completed",
            new_artifacts=artifacts,
            new_messages=a2a_messages,
        )
