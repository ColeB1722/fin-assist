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
from typing import TYPE_CHECKING, Any, Literal, NamedTuple

import httpx
from a2a.client.client import ClientConfig
from a2a.client.client_factory import ClientFactory
from a2a.types import (
    Message,
    Part,
    Role,
    SendMessageRequest,
    StreamResponse,
    Task,
    TaskState,
)
from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct
from pydantic import BaseModel, Field

from fin_assist.agents.metadata import AgentCardMeta, AgentResult

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_TERMINAL_STATES: frozenset[int] = frozenset(
    {
        TaskState.TASK_STATE_COMPLETED,
        TaskState.TASK_STATE_FAILED,
        TaskState.TASK_STATE_CANCELED,
        TaskState.TASK_STATE_REJECTED,
        TaskState.TASK_STATE_AUTH_REQUIRED,
        TaskState.TASK_STATE_INPUT_REQUIRED,
    }
)


class DiscoveredAgent(BaseModel):
    """An agent discovered from the hub's ``/agents`` endpoint."""

    name: str
    description: str
    url: str
    card_meta: AgentCardMeta = AgentCardMeta()


class StreamEvent(BaseModel):
    """A single event from a streaming agent response."""

    kind: Literal[
        "text_delta",
        "thinking_delta",
        "completed",
        "failed",
        "auth_required",
        "input_required",
    ]
    text: str = ""
    result: AgentResult | None = None
    deferred_calls: list[dict[str, Any]] = Field(default_factory=list)


def _struct_to_dict(struct) -> dict[str, Any]:
    """Convert a protobuf Struct to a plain Python dict."""
    if not struct or not struct.fields:
        return {}
    return MessageToDict(struct, preserving_proto_field_name=True)


def _part_struct_data(part) -> dict[str, Any] | None:
    """Return the struct dict from a Part's data field, or None."""
    if part.HasField("data") and part.data.HasField("struct_value"):
        return _struct_to_dict(part.data.struct_value)
    return None


def _is_thinking(part) -> bool:
    """Return whether a Part's metadata marks it as a thinking block."""
    return _struct_to_dict(part.metadata).get("type") == "thinking"


def _is_deferred(part) -> bool:
    """Return whether a Part's metadata marks it as a deferred tool call."""
    return _struct_to_dict(part.metadata).get("type") == "deferred"


def _extract_deferred_calls(task) -> list[dict[str, Any]]:
    """Extract deferred tool calls from a task's artifacts."""
    calls: list[dict[str, Any]] = []
    for artifact in reversed(task.artifacts):
        for part in artifact.parts:
            meta = _struct_to_dict(part.metadata)
            if meta.get("type") == "deferred":
                calls.append(
                    {
                        "tool_name": meta.get("tool_name", ""),
                        "tool_call_id": meta.get("tool_call_id", ""),
                        "args": meta.get("args", {}),
                        "reason": meta.get("reason", ""),
                    }
                )
    return calls


class _Extraction(NamedTuple):
    output: str
    warnings: list[str]
    metadata: dict[str, Any]


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
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http: httpx.AsyncClient | None = http_client
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
    def _extract_from_artifacts(task: Task) -> _Extraction:
        output = ""
        warnings: list[str] = []
        metadata: dict[str, Any] = {}

        for artifact in reversed(task.artifacts):
            for part in artifact.parts:
                if _is_thinking(part):
                    continue
                data = _part_struct_data(part)
                if data is not None:
                    inner = data.get("result", data)
                    if not output:
                        output = inner.get("command", "")
                    if inner.get("warnings"):
                        warnings = inner["warnings"]
                    if inner.get("metadata"):
                        metadata.update(inner["metadata"])
                elif part.text and not output:
                    output = part.text

        return _Extraction(output, warnings, metadata)

    @staticmethod
    def _extract_from_history(task: Task) -> str:
        for item in reversed(task.history):
            if item.role != Role.ROLE_AGENT:
                continue
            for part in item.parts:
                if part.text and not _is_thinking(part):
                    return part.text
        return ""

    @staticmethod
    def _extract_thinking(task: Task) -> list[str]:
        thinking: list[str] = []
        for artifact in task.artifacts:
            for part in artifact.parts:
                if _is_thinking(part) and part.text:
                    thinking.append(part.text)
        for item in task.history:
            if item.role != Role.ROLE_AGENT:
                continue
            for part in item.parts:
                if _is_thinking(part) and part.text:
                    thinking.append(part.text)
        return thinking

    @staticmethod
    def _extract_result(task: Task) -> AgentResult:
        state = task.status.state
        context_id = task.context_id or None  # protobuf defaults to ""

        extraction = HubClient._extract_from_artifacts(task)

        if not extraction.output:
            output = HubClient._extract_from_history(task)
        else:
            output = extraction.output

        thinking = HubClient._extract_thinking(task)

        return AgentResult(
            success=state == TaskState.TASK_STATE_COMPLETED,
            output=output,
            warnings=extraction.warnings,
            metadata=extraction.metadata,
            context_id=context_id,
            thinking=thinking,
            auth_required=state == TaskState.TASK_STATE_AUTH_REQUIRED,
        )

    # ------------------------------------------------------------------
    # Response dispatch
    # ------------------------------------------------------------------

    @staticmethod
    def _process_response(response: StreamResponse) -> tuple[bool, Task | None, Any | None]:
        """Process a single streaming response.

        Returns (is_terminal, task_or_none, artifact_or_none).
        """
        if response.HasField("task"):
            task = response.task
            return task.status.state in _TERMINAL_STATES, task, None
        if response.HasField("status_update"):
            state = response.status_update.status.state
            return state in _TERMINAL_STATES, None, None
        if response.HasField("artifact_update"):
            return False, None, response.artifact_update.artifact
        return False, None, None

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

    @staticmethod
    def _apply_status_update(task: Task, status_update) -> None:
        task.status.CopyFrom(status_update.status)
        if status_update.status.HasField("message"):
            task.history.append(status_update.status.message)

    async def stream_agent(
        self,
        agent_name: str,
        prompt: str,
        context_id: str | None = None,
        approval_decisions: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream an agent response, yielding progressive text deltas.

        Yields ``StreamEvent`` objects — ``text_delta`` for normal text chunks,
        ``thinking_delta`` for thinking chunks, then a final ``completed``,
        ``failed``, ``auth_required``, or ``input_required`` event.

        When ``approval_decisions`` is provided, the message includes an
        ``approval_result`` Part so the Executor can resume a deferred task.
        """
        client = await self._get_a2a(agent_name)
        parts: list[Part] = [Part(text=prompt)]
        if approval_decisions:
            meta = Struct()
            meta.update(
                {
                    "type": "approval_result",
                    "decisions": approval_decisions,
                }
            )
            parts.append(Part(text="", metadata=meta))
        msg = Message(
            role=Role.ROLE_USER,
            message_id=str(uuid.uuid4()),
            parts=parts,
        )
        if context_id:
            msg.context_id = context_id

        request = SendMessageRequest(message=msg)

        task: Task | None = None
        accumulated_thinking: list[str] = []
        collected_artifacts: list[Any] = []

        async for response in client.send_message(request):
            is_terminal, resp_task, artifact = self._process_response(response)
            if artifact is not None:
                collected_artifacts.append(artifact)
                for part in artifact.parts:
                    if not part.text:
                        continue
                    if _is_thinking(part):
                        accumulated_thinking.append(part.text)
                        yield StreamEvent(kind="thinking_delta", text=part.text)
                    elif _is_deferred(part):
                        continue
                    else:
                        yield StreamEvent(kind="text_delta", text=part.text)
            if resp_task is not None:
                task = resp_task
            if response.HasField("status_update") and task is not None:
                self._apply_status_update(task, response.status_update)
            if is_terminal:
                break

        if task is not None:
            if collected_artifacts and not task.artifacts:
                for artifact in collected_artifacts:
                    task.artifacts.append(artifact)

            state = task.status.state
            result = self._extract_result(task)
            if accumulated_thinking and not result.thinking:
                result.thinking = accumulated_thinking
            if state == TaskState.TASK_STATE_INPUT_REQUIRED:
                deferred_calls = _extract_deferred_calls(task)
                yield StreamEvent(
                    kind="input_required",
                    result=result,
                    deferred_calls=deferred_calls,
                )
            elif result.auth_required:
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

        task: Task | None = None
        artifacts: list[Any] = []

        async for response in client.send_message(request):
            is_terminal, resp_task, artifact = self._process_response(response)
            if resp_task is not None:
                task = resp_task
            if response.HasField("status_update") and task is not None:
                self._apply_status_update(task, response.status_update)
            if artifact is not None:
                artifacts.append(artifact)
            if is_terminal:
                break

        if task is None:
            return AgentResult(success=False, output="No response from agent")

        if artifacts and not task.artifacts:
            for artifact in artifacts:
                task.artifacts.append(artifact)

        return self._extract_result(task)
