"""Client for the fin-assist agent hub.

Wraps fasta2a's ``A2AClient`` for per-agent A2A calls and adds hub-level
concerns: agent discovery (custom ``/agents`` endpoint), task polling,
and result extraction.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import httpx
from fasta2a.client import A2AClient

from fin_assist.agents.metadata import AgentCardMeta

if TYPE_CHECKING:
    from fasta2a.schema import Message, Task, TaskState

# The A2A spec defines nine task states.  fasta2a exposes them as a
# ``Literal`` type alias (``TaskState``) — not an enum — so there's no
# programmatic way to ask "which are terminal?".  We define the set here,
# derived from the spec: any state from which no further transitions occur.
_TERMINAL_STATES: frozenset[TaskState] = frozenset(
    {"completed", "failed", "canceled", "rejected", "auth-required"}
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


class HubClient:
    """Client for the fin-assist agent hub.

    Combines hub-level discovery (``GET /agents``) with per-agent A2A
    communication via ``fasta2a.client.A2AClient``.

    The hub mounts each agent at ``/agents/{name}/``, so each fasta2a
    client is pointed at the agent-specific sub-app URL.
    """

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
        self._http: httpx.AsyncClient | None = None
        self._a2a_clients: dict[str, A2AClient] = {}

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.timeout)
        return self._http

    def _get_a2a(self, agent_name: str) -> A2AClient:
        """Return (or create) a fasta2a A2AClient for the given agent."""
        if agent_name not in self._a2a_clients:
            agent_url = f"{self.base_url}/agents/{agent_name}/"
            self._a2a_clients[agent_name] = A2AClient(
                base_url=agent_url,
                http_client=self._get_http(),
            )
        return self._a2a_clients[agent_name]

    async def close(self) -> None:
        """Close the shared HTTP client.  Safe to call multiple times."""
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
    # Task polling
    # ------------------------------------------------------------------

    async def _poll_task(self, agent_name: str, task_id: str) -> Task:
        """Poll ``tasks/get`` until the task reaches a terminal state.

        fasta2a's broker processes tasks asynchronously — ``message/send``
        returns the task in ``"submitted"`` state.  Neither fasta2a nor the
        official ``a2a-python`` SDK provide a send-and-wait helper, so
        polling is the client's responsibility.
        """
        a2a = self._get_a2a(agent_name)

        try:
            async with asyncio.timeout(self.timeout):
                while True:
                    await asyncio.sleep(self.poll_interval)
                    rpc = await a2a.get_task(task_id)
                    task = rpc.get("result")
                    if task and task["status"]["state"] in _TERMINAL_STATES:
                        return task
        except TimeoutError:
            raise TimeoutError(f"Task {task_id} did not complete within {self.timeout}s") from None

    async def _resolve_task(self, agent_name: str, result: Any) -> Task:
        """Return a terminal ``Task`` — polling if necessary.

        ``message/send`` may return a task that's already terminal (fast
        agent), still in-progress (async broker), or even a bare Message.
        """
        match result:
            case {"kind": "task"} if result["status"]["state"] in _TERMINAL_STATES:
                return result
            case {"kind": "task"}:
                return await self._poll_task(agent_name, result["id"])
            case _:
                raise RuntimeError(f"Unexpected message/send result: {result!r:.200}")

    # ------------------------------------------------------------------
    # Result extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_from_artifacts(task: Task) -> tuple[str, list[str], dict[str, Any]]:
        """Extract output, warnings, and metadata from task artifacts.

        pydantic-ai wraps structured ``output_type`` values in a
        ``{"result": ...}`` envelope inside data parts; we unwrap that.
        Artifacts are checked in reverse order (latest wins for output).
        """
        output = ""
        warnings: list[str] = []
        metadata: dict[str, Any] = {}

        for item in reversed(task.get("artifacts") or []):
            for part in item.get("parts", []):
                match part:
                    case {"kind": "data", "data": data}:
                        inner = data.get("result", data)
                        if not output:
                            output = inner.get("command", "")
                        if inner.get("warnings"):
                            warnings = inner["warnings"]
                        if inner.get("metadata"):
                            metadata.update(inner["metadata"])
                    case {"kind": "text", "text": text}:
                        if not output:
                            output = text

        return output, warnings, metadata

    @staticmethod
    def _extract_from_history(task: Task) -> str:
        """Extract the last agent text from task history.

        History includes the user's input message, so this is only used
        as a fallback when artifacts yield no output.
        """
        for item in reversed(task.get("history") or []):
            for part in item.get("parts", []):
                match part:
                    case {"kind": "text", "text": text}:
                        return text
        return ""

    @staticmethod
    def _extract_result(task: Task) -> AgentResult:
        """Extract ``AgentResult`` from a completed ``Task``.

        Artifacts are checked first (they contain the agent's response).
        History is the fallback — it includes the user's input message,
        so scanning it first would return the prompt instead of the reply.

        For ``auth-required`` tasks, the worker adds an agent message to
        history explaining which credentials are missing.  We flag the
        result so the display layer can render it distinctly.
        """
        state = task["status"]["state"]
        context_id = task["context_id"]

        output, warnings, metadata = HubClient._extract_from_artifacts(task)

        if not output:
            output = HubClient._extract_from_history(task)

        if state == "auth-required":
            metadata["auth_required"] = True

        return AgentResult(
            success=state == "completed",
            output=output,
            warnings=warnings,
            metadata=metadata,
            context_id=context_id,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def _build_message(prompt: str, context_id: str | None = None) -> Message:
        """Build an A2A ``Message`` TypedDict for the given prompt."""
        msg: dict[str, Any] = {
            "role": "user",
            "parts": [{"kind": "text", "text": prompt}],
            "kind": "message",
            "message_id": str(uuid.uuid4()),
        }
        if context_id:
            msg["context_id"] = context_id
        return cast("Message", msg)

    async def run_agent(self, agent_name: str, prompt: str) -> AgentResult:
        """Send a one-shot message to an agent and wait for the result."""
        a2a = self._get_a2a(agent_name)
        rpc = await a2a.send_message(self._build_message(prompt))

        result = rpc.get("result")
        task = await self._resolve_task(agent_name, result)
        return self._extract_result(task)

    async def send_message(
        self,
        agent_name: str,
        prompt: str,
        context_id: str | None = None,
    ) -> AgentResult:
        """Send a message to an agent (multi-turn) and wait for the result."""
        a2a = self._get_a2a(agent_name)
        rpc = await a2a.send_message(self._build_message(prompt, context_id))

        result = rpc.get("result")
        task = await self._resolve_task(agent_name, result)
        return self._extract_result(task)
