"""Client for the fin-assist agent hub.

Uses a2a-sdk's ``ClientFactory`` for per-agent A2A communication, with
hub-level concerns (agent discovery, result extraction) layered on top.

The client supports two modes:
- **Blocking** (default): ``run_agent()`` / ``send_message()`` — sends a
  message and waits for the final task result.
- **Streaming** (Phase 6): ``stream_agent()`` — async iterator yielding
  progressive updates.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
from a2a.client.client import ClientConfig
from a2a.client.client_factory import ClientFactory
from a2a.types import (
    Message,
    Part,
    Role,
    SendMessageRequest,
    TaskState,
)
from google.protobuf.json_format import MessageToDict

from fin_assist.agents.metadata import AgentCardMeta

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_TERMINAL_STATES: frozenset[int] = frozenset(
    {
        TaskState.TASK_STATE_COMPLETED,
        TaskState.TASK_STATE_FAILED,
        TaskState.TASK_STATE_CANCELED,
        TaskState.TASK_STATE_REJECTED,
        TaskState.TASK_STATE_AUTH_REQUIRED,
    }
)


@dataclass
class DiscoveredAgent:
    """An agent discovered from the hub's ``/agents`` endpoint."""

    name: str
    description: str
    url: str
    card_meta: AgentCardMeta


@dataclass
class AgentResult:
    """Result from an agent run."""

    success: bool
    output: str
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    context_id: str | None = None
    thinking: list[str] = field(default_factory=list)


@dataclass
class StreamEvent:
    """A single event from a streaming agent response."""

    kind: str
    """Event type: 'text_delta', 'completed', 'failed', 'auth_required'."""

    text: str = ""
    """Text content for 'text_delta' events."""

    result: AgentResult | None = None
    """Final result for 'completed'/'failed'/'auth_required' events."""


class HubClient:
    """Client for the fin-assist agent hub.

    Combines hub-level discovery (``GET /agents``) with per-agent A2A
    communication via a2a-sdk's ``ClientFactory``.
    """

    DEFAULT_TIMEOUT = 60.0

    def __init__(
        self,
        base_url: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http: httpx.AsyncClient | None = None
        self._factory: ClientFactory | None = None
        self._a2a_clients: dict[str, Any] = {}

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.timeout)
        return self._http

    def _get_factory(self) -> ClientFactory:
        if self._factory is None:
            config = ClientConfig(httpx_client=self._get_http())
            self._factory = ClientFactory(config=config)
        return self._factory

    async def _get_a2a(self, agent_name: str):
        if agent_name not in self._a2a_clients:
            agent_url = f"{self.base_url}/agents/{agent_name}/"
            factory = self._get_factory()
            self._a2a_clients[agent_name] = await factory.create_from_url(agent_url)
        return self._a2a_clients[agent_name]

    async def close(self) -> None:
        for client in self._a2a_clients.values():
            await client.close()
        self._a2a_clients.clear()
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # Discovery (hub-specific, not part of A2A protocol)
    # ------------------------------------------------------------------

    async def discover_agents(self) -> list[DiscoveredAgent]:
        """Fetch the list of available agents from the hub."""
        http = self._get_http()
        response = await http.get(f"{self.base_url}/agents")
        response.raise_for_status()
        data = response.json()

        return [
            DiscoveredAgent(
                name=entry["name"],
                description=entry["description"],
                url=entry["url"],
                card_meta=AgentCardMeta.model_validate(entry.get("card_meta", {})),
            )
            for entry in data.get("agents", [])
        ]

    # ------------------------------------------------------------------
    # Result extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_from_artifacts(task_dict: dict) -> tuple[str, list[str], dict[str, Any]]:
        output = ""
        warnings: list[str] = []
        metadata: dict[str, Any] = {}

        for artifact in reversed(task_dict.get("artifacts", [])):
            for part in artifact.get("parts", []):
                text = part.get("text", "")
                data = part.get("data", {})
                if data:
                    inner = data.get("result", data)
                    if not output:
                        output = inner.get("command", "")
                    if inner.get("warnings"):
                        warnings = inner["warnings"]
                    if inner.get("metadata"):
                        metadata.update(inner["metadata"])
                elif text and not output:
                    output = text

        return output, warnings, metadata

    @staticmethod
    def _extract_from_history(task_dict: dict) -> str:
        for item in reversed(task_dict.get("history", [])):
            if item.get("role") != "agent":
                continue
            for part in item.get("parts", []):
                if part.get("text") and part.get("metadata", {}).get("type") != "thinking":
                    return part["text"]
        return ""

    @staticmethod
    def _extract_thinking(task_dict: dict) -> list[str]:
        thinking: list[str] = []
        for item in task_dict.get("history", []):
            if item.get("role") != "agent":
                continue
            for part in item.get("parts", []):
                if part.get("metadata", {}).get("type") == "thinking" and part.get("text"):
                    thinking.append(part["text"])
        return thinking

    @staticmethod
    def _extract_result(task_dict: dict) -> AgentResult:
        state = task_dict.get("status", {}).get("state", "")
        context_id = task_dict.get("context_id")

        output, warnings, metadata = HubClient._extract_from_artifacts(task_dict)

        if not output:
            output = HubClient._extract_from_history(task_dict)

        thinking = HubClient._extract_thinking(task_dict)

        if state == "auth-required":
            metadata["auth_required"] = True

        return AgentResult(
            success=state == "completed",
            output=output,
            warnings=warnings,
            metadata=metadata,
            context_id=context_id,
            thinking=thinking,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_agent(self, agent_name: str, prompt: str) -> AgentResult:
        """Send a one-shot message to an agent and wait for the result."""
        return await self._send_and_wait(agent_name, prompt, context_id=None)

    async def send_message(
        self,
        agent_name: str,
        prompt: str,
        context_id: str | None = None,
    ) -> AgentResult:
        """Send a message to an agent (multi-turn) and wait for the result."""
        return await self._send_and_wait(agent_name, prompt, context_id=context_id)

    async def stream_agent(
        self,
        agent_name: str,
        prompt: str,
        context_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream an agent response, yielding progressive text deltas.

        Yields ``StreamEvent`` objects — one ``text_delta`` per artifact chunk,
        then a final ``completed``, ``failed``, or ``auth_required`` event.
        """
        client = await self._get_a2a(agent_name)
        msg = Message(
            role=Role.ROLE_USER,
            message_id=str(uuid.uuid4()),
            parts=[Part(text=prompt)],
        )
        if context_id:
            msg.context_id = context_id

        request = SendMessageRequest(message=msg)

        task_dict: dict[str, Any] | None = None

        async for response in client.send_message(request):
            if response.HasField("artifact_update"):
                artifact = response.artifact_update
                for part in artifact.artifact.parts:
                    if part.text:
                        yield StreamEvent(kind="text_delta", text=part.text)

            if response.HasField("task"):
                task_dict = _task_to_dict(response.task)
                state = response.task.status.state
                if state in _TERMINAL_STATES:
                    break
            elif response.HasField("status_update"):
                state = response.status_update.status.state
                if state in _TERMINAL_STATES:
                    if task_dict:
                        task_dict["status"]["state"] = _task_state_to_str(state)
                    else:
                        task_dict = {
                            "status": {"state": _task_state_to_str(state)},
                            "artifacts": [],
                            "history": [],
                        }
                    break

        if task_dict is not None:
            result = self._extract_result(task_dict)
            if result.metadata.get("auth_required"):
                yield StreamEvent(kind="auth_required", result=result)
            elif result.success:
                yield StreamEvent(kind="completed", result=result)
            else:
                yield StreamEvent(kind="failed", result=result)
        else:
            yield StreamEvent(
                kind="failed",
                result=AgentResult(success=False, output="No response from agent"),
            )

    async def _send_and_wait(
        self,
        agent_name: str,
        prompt: str,
        context_id: str | None = None,
    ) -> AgentResult:
        client = await self._get_a2a(agent_name)
        msg = Message(
            role=Role.ROLE_USER,
            message_id=str(uuid.uuid4()),
            parts=[Part(text=prompt)],
        )
        if context_id:
            msg.context_id = context_id

        request = SendMessageRequest(message=msg)

        task_dict: dict[str, Any] | None = None
        async for response in client.send_message(request):
            if response.HasField("task"):
                task_dict = _task_to_dict(response.task)
                state = response.task.status.state
                if state in _TERMINAL_STATES:
                    break
            elif response.HasField("status_update"):
                state = response.status_update.status.state
                if state in _TERMINAL_STATES:
                    if task_dict:
                        task_dict["status"]["state"] = _task_state_to_str(state)
                    else:
                        task_dict = {
                            "status": {"state": _task_state_to_str(state)},
                            "artifacts": [],
                            "history": [],
                        }
                    break
            elif response.HasField("artifact_update"):
                if task_dict is None:
                    task_dict = {"status": {"state": "working"}, "artifacts": [], "history": []}
                artifact_dict = MessageToDict(
                    response.artifact_update.artifact, preserving_proto_field_name=True
                )
                task_dict.setdefault("artifacts", []).append(artifact_dict)

        if task_dict is None:
            return AgentResult(success=False, output="No response from agent")

        return self._extract_result(task_dict)


def _task_state_to_str(state: int) -> str:
    mapping: dict[int, str] = {
        TaskState.TASK_STATE_SUBMITTED: "submitted",
        TaskState.TASK_STATE_WORKING: "working",
        TaskState.TASK_STATE_COMPLETED: "completed",
        TaskState.TASK_STATE_FAILED: "failed",
        TaskState.TASK_STATE_CANCELED: "canceled",
        TaskState.TASK_STATE_INPUT_REQUIRED: "input-required",
        TaskState.TASK_STATE_AUTH_REQUIRED: "auth-required",
        TaskState.TASK_STATE_REJECTED: "rejected",
    }
    return mapping.get(state, "unknown")


def _task_to_dict(task) -> dict:
    d = MessageToDict(task, preserving_proto_field_name=True)
    state_int = task.status.state
    d["status"]["state"] = _task_state_to_str(state_int)
    for msg in d.get("history", []):
        role = msg.get("role", "")
        if role.startswith("ROLE_"):
            msg["role"] = role.removeprefix("ROLE_").lower()
    return d
