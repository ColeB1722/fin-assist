"""Custom Worker with progressive output via ``agent.iter()``.

Implements ``fasta2a.Worker`` directly (public API) rather than subclassing
``AgentWorker`` from the private ``pydantic_ai._a2a`` module. This resolves
issue #68 and eliminates the tech debt around private imports.

The worker owns its own message conversion logic using public types from
``pydantic_ai.messages`` and ``fasta2a.schema`` — no implicit behavior
inherited from ``AgentWorker``.

Progressive output
~~~~~~~~~~~~~~~~~~
Instead of calling ``pydantic_agent.run()`` (which blocks until the full
response is ready), the worker uses ``agent.iter()`` to iterate over the
agent's execution graph node-by-node.  For ``ModelRequestNode`` nodes, it
calls ``node.stream()`` to receive token-level deltas (thinking and text).

Intermediate progress is written to the task via ``storage.update_task()``
with ``state="working"`` — appending messages tagged with metadata so the
polling client can detect new content while the task is still in progress.

This is a middle-ground approach: it doesn't require fasta2a SSE streaming
(blocked on v0.7+), but ~70% of the work (``agent.iter()`` usage, message
tagging, display layer) carries forward when SSE lands.

Why not subclass AgentWorker?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. ``AgentWorker`` lives in ``pydantic_ai._a2a`` — a private module that can
   change without notice. Subclassing it couples us to unstable internals.
2. ``AgentWorker.run_task()`` is a blocking call with no hooks for custom
   task states (``auth-required``, ``input-required``). We override the
   entire method anyway, so inheritance buys nothing.
3. ``pydantic_agent.to_a2a()`` creates a default ``AgentWorker`` that is
   immediately discarded. Constructing ``FastA2A`` directly avoids this waste.
4. The "two agents" pattern (``agent_def`` + inherited ``agent``) is
   confusing. This worker takes an explicit ``agent`` parameter — a single
   ``ConfigAgent`` that carries all domain logic.
"""

from __future__ import annotations

import base64
import uuid
from typing import TYPE_CHECKING, Any, cast

from fasta2a.schema import Artifact, DataPart, Message, Part, TaskIdParams, TaskSendParams, TextPart
from fasta2a.worker import Worker
from pydantic import TypeAdapter
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai import (
    FinalResultEvent,
    PartDeltaEvent,
    TextPartDelta,
    ThinkingPartDelta,
)
from pydantic_ai.messages import (
    ModelRequest,
    ModelRequestPart,
    ModelResponse,
    ModelResponsePart,
    ThinkingPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.messages import TextPart as PydanticTextPart

from fin_assist.agents.metadata import MissingCredentialsError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fasta2a.broker import Broker
    from fasta2a.storage import Storage

    from fin_assist.agents.agent import ConfigAgent

Context = list[Any]

# SSE-REPLACE: This batching heuristic exists because each flush is a full
# SQLite read-modify-write via storage.update_task().  With fasta2a v0.7+ SSE,
# events are emitted directly to broker.event_bus (no storage round-trip),
# so per-token delivery becomes cheap and this constant can be removed.
_THINKING_FLUSH_INTERVAL = 64


class FinAssistWorker(Worker[Context]):
    """Worker with progressive output and graceful credential handling.

    Takes a ``ConfigAgent`` (our domain agent) alongside the shared storage and
    per-agent broker. On each task:

    1. Calls ``agent.build_model()`` to lazily construct the LLM model.
    2. Uses ``agent.iter()`` + ``node.stream()`` for token-level iteration.
    3. Emits intermediate ``update_task(state="working")`` calls with tagged
       messages so the polling client can render progress incrementally.
    4. On completion, writes final artifacts and messages as before.

    If ``build_model()`` raises ``MissingCredentialsError``, the task is set
    to ``auth-required`` with a helpful message instead of crashing the hub.

    Intermediate message tagging:
        - ``metadata.type = "thinking_delta"`` — accumulated thinking tokens
        - ``metadata.type = "text_delta"`` — accumulated output text tokens
        - ``metadata.partial = True`` — marks the message as an intermediate
          snapshot (the client uses this to distinguish from final messages)
    """

    def __init__(
        self,
        *,
        agent: ConfigAgent,
        broker: Broker,
        storage: Storage[Context],
    ) -> None:
        super().__init__(broker=broker, storage=storage)
        self._agent = agent

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
            model = self._agent.build_model()
        except MissingCredentialsError as exc:
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
            return

        pydantic_agent = self._agent.build_pydantic_agent()

        try:
            result = await self._run_with_streaming(
                pydantic_agent, model, message_history, task["id"]
            )
        except Exception:
            await self.storage.update_task(task["id"], state="failed")
            raise

        await self.storage.update_context(task["context_id"], result.all_messages())

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

    async def _run_with_streaming(
        self,
        pydantic_agent: PydanticAgent[Any, Any],
        model: Any,
        message_history: list[Any],
        task_id: str,
    ) -> Any:
        """Run the agent with ``iter()`` + ``stream()``, emitting progress.

        Iterates over the agent's execution graph.  For ``ModelRequestNode``
        nodes, streams token deltas and flushes intermediate updates to
        storage so the polling client can render progress.

        Returns the ``AgentRunResult`` (same type as ``agent.run()``).
        """
        thinking_buffer = ""
        thinking_tokens_since_flush = 0
        text_buffer = ""
        producing_result = False

        async with (
            pydantic_agent,
            pydantic_agent.iter(model=model, message_history=message_history) as agent_run,
        ):
            async for node in agent_run:
                if PydanticAgent.is_model_request_node(node):
                    async with node.stream(agent_run.ctx) as request_stream:
                        async for event in request_stream:
                            if isinstance(event, FinalResultEvent):
                                # Flush any remaining thinking before
                                # switching to output collection.
                                if thinking_buffer:
                                    await self._flush_thinking(task_id, thinking_buffer)
                                    thinking_buffer = ""
                                    thinking_tokens_since_flush = 0
                                producing_result = True
                                continue

                            if isinstance(event, PartDeltaEvent):
                                delta = event.delta
                                if isinstance(delta, ThinkingPartDelta):
                                    if delta.content_delta:
                                        thinking_buffer += delta.content_delta
                                        thinking_tokens_since_flush += 1
                                        # SSE-REPLACE: Batching exists to
                                        # limit storage round-trips.  With
                                        # SSE, flush every delta directly
                                        # to event_bus (no interval needed).
                                        if thinking_tokens_since_flush >= _THINKING_FLUSH_INTERVAL:
                                            await self._flush_thinking(task_id, thinking_buffer)
                                            thinking_tokens_since_flush = 0
                                elif isinstance(delta, TextPartDelta):
                                    text_buffer += delta.content_delta
                                    if producing_result:
                                        await self._flush_text(task_id, text_buffer)

        # Flush any remaining thinking that didn't hit the interval threshold
        if thinking_buffer and not producing_result:
            await self._flush_thinking(task_id, thinking_buffer)

        return agent_run.result

    # ------------------------------------------------------------------
    # SSE-REPLACE: Both _flush_thinking and _flush_text construct full A2A
    # Message dicts and persist them via storage.update_task() — a SQLite
    # read-modify-write per call.  This is the polling transport's main
    # overhead.
    #
    # With fasta2a v0.7+ SSE, these two methods collapse to ~3 lines each:
    #
    #     await self.broker.event_bus.emit(task_id, StreamResponse(
    #         status_update=TaskStatusUpdateEvent(task_id=task_id, ...)
    #     ))
    #
    # The Message construction, uuid generation, and storage round-trip
    # all go away.  The tagging protocol (metadata.type, metadata.partial)
    # is replaced by the StreamResponse event type discriminator.
    # ------------------------------------------------------------------

    async def _flush_thinking(self, task_id: str, thinking_content: str) -> None:
        """Write an intermediate thinking snapshot to the task."""
        msg: Message = {
            "role": "agent",
            "parts": [
                {
                    "kind": "text",
                    "text": thinking_content,
                    "metadata": {
                        "type": "thinking_delta",
                        "partial": True,
                    },
                }
            ],
            "kind": "message",
            "message_id": str(uuid.uuid4()),
        }
        await self.storage.update_task(task_id, state="working", new_messages=[msg])

    async def _flush_text(self, task_id: str, text_content: str) -> None:
        """Write an intermediate text snapshot to the task."""
        msg: Message = {
            "role": "agent",
            "parts": [
                {
                    "kind": "text",
                    "text": text_content,
                    "metadata": {
                        "type": "text_delta",
                        "partial": True,
                    },
                }
            ],
            "kind": "message",
            "message_id": str(uuid.uuid4()),
        }
        await self.storage.update_task(task_id, state="working", new_messages=[msg])

    async def cancel_task(self, params: TaskIdParams) -> None:
        task = await self.storage.load_task(params["id"])
        if task and task["status"]["state"] not in ("completed", "failed", "canceled"):
            await self.storage.update_task(params["id"], state="canceled")

    def build_message_history(self, history: list[Message]) -> list[Any]:
        model_messages: list[Any] = []
        for message in history:
            if message["role"] == "user":
                model_messages.append(
                    ModelRequest(parts=self._request_parts_from_a2a(message["parts"]))
                )
            else:
                model_messages.append(
                    ModelResponse(parts=self._response_parts_from_a2a(message["parts"]))
                )
        return model_messages

    def build_artifacts(self, result: Any) -> list[Artifact]:
        artifact_id = str(uuid.uuid4())
        part = self._convert_result_to_part(result)
        return [Artifact(artifact_id=artifact_id, name="result", parts=[part])]

    def _convert_result_to_part(self, result: Any) -> Part:
        if isinstance(result, str):
            return TextPart(kind="text", text=result)
        output_type = type(result)
        type_adapter = TypeAdapter(output_type)
        data = type_adapter.dump_python(result, mode="json")
        json_schema = type_adapter.json_schema(mode="serialization")
        return DataPart(kind="data", data={"result": data}, metadata={"json_schema": json_schema})

    def _request_parts_from_a2a(self, parts: list[Part]) -> list[ModelRequestPart]:
        model_parts: list[ModelRequestPart] = []
        for part in parts:
            if part["kind"] == "text":
                model_parts.append(UserPromptPart(content=part["text"]))
            elif part["kind"] == "file":
                file_content = cast("dict[str, Any]", part["file"])
                if "bytes" in file_content:
                    from pydantic_ai.messages import BinaryContent

                    data = base64.b64decode(file_content["bytes"])
                    mime_type = file_content.get("mime_type", "application/octet-stream")
                    content = BinaryContent(data=data, media_type=mime_type)
                    model_parts.append(UserPromptPart(content=[content]))
                else:
                    url = file_content["uri"]
                    from pydantic_ai.messages import DocumentUrl, ImageUrl

                    matched = False
                    for url_cls in (DocumentUrl, ImageUrl):
                        try:
                            content = url_cls(url=url)
                            _ = content.media_type
                            model_parts.append(UserPromptPart(content=[content]))
                            matched = True
                            break
                        except ValueError:
                            continue
                    if not matched:
                        model_parts.append(UserPromptPart(content=url))
            elif part["kind"] == "data":
                raise NotImplementedError("Data parts in requests are not supported yet.")
        return model_parts

    def _response_parts_from_a2a(self, parts: list[Part]) -> list[ModelResponsePart]:
        model_parts: list[ModelResponsePart] = []
        for part in parts:
            if part["kind"] == "text":
                model_parts.append(PydanticTextPart(content=part["text"]))
            elif part["kind"] == "data":
                raise NotImplementedError("Data parts in responses are not supported yet.")
        return model_parts

    def _response_parts_to_a2a(self, parts: Sequence[ModelResponsePart]) -> list[Part]:
        a2a_parts: list[Part] = []
        for part in parts:
            if isinstance(part, PydanticTextPart):
                a2a_parts.append(TextPart(kind="text", text=part.content))
            elif isinstance(part, ThinkingPart):
                a2a_parts.append(
                    TextPart(
                        kind="text",
                        text=part.content,
                        metadata={
                            "type": "thinking",
                            "thinking_id": part.id,
                            "signature": part.signature,
                        },
                    )
                )
            elif isinstance(part, ToolCallPart):
                # Tool calls are internal pydantic-ai mechanics; not surfaced to A2A
                pass
        return a2a_parts
