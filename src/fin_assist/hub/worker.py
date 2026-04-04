"""Custom AgentWorker that maps MissingCredentialsError to ``auth-required``.

fasta2a's default ``AgentWorker`` catches all exceptions from the pydantic-ai
agent and sets the task state to ``"failed"``.  This subclass intercepts
``MissingCredentialsError`` — raised by ``BaseAgent._build_model()`` when
required API keys are missing — and sets ``"auth-required"`` instead, with an
agent message explaining which providers need credentials.

All other exceptions propagate normally and result in ``"failed"`` via the
parent's exception handling.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from pydantic_ai._a2a import AgentWorker

from fin_assist.agents.base import MissingCredentialsError

if TYPE_CHECKING:
    from fasta2a.schema import Message, TaskSendParams


class FinAssistWorker(AgentWorker[Any, Any]):
    """Worker that gracefully handles missing credentials.

    Overrides ``run_task`` to catch ``MissingCredentialsError`` before the
    parent's generic ``except Exception`` handler writes ``"failed"``.
    On catch, it sets the task to ``"auth-required"`` and adds an agent
    message describing which providers need keys.
    """

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
            result = await self.agent.run(message_history=message_history)  # type: ignore[arg-type]
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
