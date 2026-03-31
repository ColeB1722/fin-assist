"""A2A HTTP client for communicating with the agent hub."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from fasta2a.client import get_task_response_ta
from fasta2a.schema import (
    Task,
    send_message_response_ta,
)

from fin_assist.agents.base import AgentCardMeta


@dataclass
class DiscoveredAgent:
    """An agent discovered from the hub's /agents endpoint."""

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


class A2AClient:
    """HTTP client for A2A agent communication."""

    DEFAULT_POLL_INTERVAL = 0.5
    DEFAULT_TIMEOUT = 60.0

    def __init__(
        self,
        base_url: str,
        timeout: float = DEFAULT_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def discover_agents(self) -> list[DiscoveredAgent]:
        """Fetch the list of available agents from the hub."""
        client = await self._get_client()
        response = await client.get(f"{self.base_url}/agents")
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

    async def _send_jsonrpc(
        self,
        agent_name: str,
        method: str,
        params: dict[str, Any],
    ) -> bytes:
        """Send a JSON-RPC 2.0 request to an agent sub-app, return raw response bytes."""
        client = await self._get_client()
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        response = await client.post(
            f"{self.base_url}/agents/{agent_name}/",
            content=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        return response.content

    async def _poll_task(self, agent_name: str, task_id: str) -> Task:
        """Poll a task until it reaches a terminal state.

        This is a fallback for non-blocking ``message/send`` (``blocking: false``
        in ``MessageSendConfiguration``), where the hub acknowledges immediately
        with a Message and the client must poll ``tasks/get`` separately.

        The current fasta2a hub uses blocking mode by default, so this path is
        not exercised in normal operation — it exists as correct protocol
        implementation for future non-blocking or async agent use cases.
        """
        client = await self._get_client()

        try:
            async with asyncio.timeout(self.timeout):
                while True:
                    await asyncio.sleep(self.poll_interval)

                    payload = {
                        "jsonrpc": "2.0",
                        "id": str(uuid.uuid4()),
                        "method": "tasks/get",
                        "params": {"id": task_id},
                    }
                    response = await client.post(
                        f"{self.base_url}/agents/{agent_name}/",
                        content=json.dumps(payload).encode(),
                        headers={"Content-Type": "application/json"},
                    )
                    response.raise_for_status()

                    rpc_response = get_task_response_ta.validate_json(response.content)
                    task = rpc_response.get("result")
                    if task and task["status"]["state"] in (
                        "completed",
                        "failed",
                        "canceled",
                        "rejected",
                        "auth-required",
                    ):
                        return task
        except TimeoutError:
            raise TimeoutError(f"Task {task_id} did not complete within {self.timeout}s") from None

    def _extract_result(self, task: Task) -> AgentResult:
        """Extract AgentResult from a completed task."""
        success = task["status"]["state"] == "completed"
        context_id = task["context_id"]

        output = ""
        warnings: list[str] = []
        metadata: dict[str, Any] = {}

        items = [*(task.get("artifacts") or []), *(task.get("history") or [])]
        for item in reversed(items):
            for part in item.get("parts", []):
                match part:
                    case {"kind": "data", "data": data}:
                        if not output:
                            output = data.get("command", "")
                        if data.get("warnings"):
                            warnings = data["warnings"]
                        if data.get("metadata"):
                            metadata = data["metadata"]
                    case {"kind": "text", "text": text}:
                        if not output:
                            output = text

        return AgentResult(
            success=success,
            output=output,
            warnings=warnings,
            metadata=metadata,
            context_id=context_id,
        )

    async def run_agent(
        self,
        agent_name: str,
        prompt: str,
    ) -> AgentResult:
        """Send a one-shot message to an agent and wait for the result."""
        message = {
            "role": "user",
            "kind": "message",
            "messageId": str(uuid.uuid4()),
            "parts": [{"kind": "text", "text": prompt}],
        }

        raw = await self._send_jsonrpc(agent_name, "message/send", {"message": message})
        rpc_response = send_message_response_ta.validate_json(raw)

        result = rpc_response.get("result")
        match result:
            case {"kind": "task"}:
                task = result
            case _:
                # Response was a Message or absent — poll for the task by RPC id
                task_id = rpc_response.get("id", "")
                task = await self._poll_task(agent_name, str(task_id))

        return self._extract_result(task)  # type: ignore[arg-type]

    async def send_message(
        self,
        agent_name: str,
        prompt: str,
        context_id: str | None = None,
    ) -> AgentResult:
        """Send a message to an agent (multi-turn) and wait for the result."""
        message: dict[str, Any] = {
            "role": "user",
            "kind": "message",
            "messageId": str(uuid.uuid4()),
            "parts": [{"kind": "text", "text": prompt}],
        }
        if context_id:
            message["contextId"] = context_id

        params: dict[str, Any] = {"message": message}

        raw = await self._send_jsonrpc(agent_name, "message/send", params)
        rpc_response = send_message_response_ta.validate_json(raw)

        result = rpc_response.get("result")
        match result:
            case {"kind": "task"}:
                task = result
            case _:
                task_id = rpc_response.get("id", "")
                task = await self._poll_task(agent_name, str(task_id))

        return self._extract_result(task)  # type: ignore[arg-type]
