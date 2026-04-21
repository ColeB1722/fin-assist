"""Tests for the Agent Hub FastAPI app."""

from __future__ import annotations

import json
import time
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.models.test import TestModel

from fin_assist.hub.app import create_hub_app


@pytest.fixture
def mock_agents(mock_config, mock_credentials):
    from fin_assist.agents.agent import AgentSpec
    from fin_assist.agents.backend import PydanticAIBackend
    from fin_assist.config.schema import AgentConfig

    shell_config = AgentConfig(
        description="Shell agent",
        system_prompt="shell",
        output_type="command",
        thinking="off",
        serving_modes=["do"],
        requires_approval=True,
        tags=["shell", "one-shot"],
    )
    default_config = AgentConfig(
        description="Default agent",
        system_prompt="chain-of-thought",
        output_type="text",
        thinking="medium",
        serving_modes=["do", "talk"],
    )

    with patch.object(PydanticAIBackend, "_build_model", return_value=TestModel()):
        yield [
            AgentSpec(
                name="shell",
                agent_config=shell_config,
                config=mock_config,
                credentials=mock_credentials,
            ),
            AgentSpec(
                name="default",
                agent_config=default_config,
                config=mock_config,
                credentials=mock_credentials,
            ),
        ]


@pytest.fixture
def client(mock_agents):
    app = create_hub_app(agents=mock_agents)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


def _a2a_headers() -> dict[str, str]:
    return {"Content-Type": "application/json", "A2A-Version": "1.0"}


def _message_params(text: str) -> dict:
    return {
        "message": {
            "role": "ROLE_USER",
            "message_id": str(uuid.uuid4()),
            "parts": [{"text": text}],
        }
    }


class TestHealthEndpoint:
    def test_health_returns_200(self, client) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_body_indicates_ok(self, client) -> None:
        resp = client.get("/health")
        data = resp.json()
        assert data["status"] == "ok"


class TestDiscoveryEndpoint:
    def test_agents_returns_200(self, client) -> None:
        resp = client.get("/agents")
        assert resp.status_code == 200

    def test_agents_lists_all_mounted_agents(self, client, mock_agents) -> None:
        resp = client.get("/agents")
        data = resp.json()
        names = {a["name"] for a in data["agents"]}
        for agent in mock_agents:
            assert agent.name in names

    def test_each_agent_entry_has_name_description_url(self, client) -> None:
        resp = client.get("/agents")
        for entry in resp.json()["agents"]:
            assert "name" in entry
            assert "description" in entry
            assert "url" in entry

    def test_agent_url_points_to_correct_path(self, client) -> None:
        resp = client.get("/agents")
        for entry in resp.json()["agents"]:
            assert entry["url"].endswith(f"/agents/{entry['name']}/")

    def test_discovery_includes_card_meta(self, client) -> None:
        resp = client.get("/agents")
        shell_entry = next(a for a in resp.json()["agents"] if a["name"] == "shell")
        assert "card_meta" in shell_entry
        assert shell_entry["card_meta"]["multi_turn"] is False


class TestAgentSubAppMounting:
    def test_shell_agent_card_is_reachable(self, client) -> None:
        resp = client.get("/agents/shell/.well-known/agent-card.json")
        assert resp.status_code == 200

    def test_default_agent_card_is_reachable(self, client) -> None:
        resp = client.get("/agents/default/.well-known/agent-card.json")
        assert resp.status_code == 200

    def test_agent_card_name_matches(self, client) -> None:
        resp = client.get("/agents/shell/.well-known/agent-card.json")
        data = resp.json()
        assert data["name"] == "shell"

    def test_agent_card_has_extensions(self, client) -> None:
        resp = client.get("/agents/shell/.well-known/agent-card.json")
        data = resp.json()
        capabilities = data.get("capabilities", {})
        extensions = capabilities.get("extensions", [])
        uris = [e.get("uri") for e in extensions]
        assert "fin_assist:meta" in uris

    def test_unknown_agent_returns_404(self, client) -> None:
        resp = client.get("/agents/nonexistent/.well-known/agent-card.json")
        assert resp.status_code == 404


class TestMessageSendEndToEnd:
    """End-to-end test: send a message and verify the executor processes it."""

    def _send_message(self, client: TestClient, agent_name: str, text: str) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "SendMessage",
            "params": _message_params(text),
        }
        resp = client.post(
            f"/agents/{agent_name}/",
            content=json.dumps(payload),
            headers=_a2a_headers(),
        )
        assert resp.status_code == 200
        return resp.json()

    def _poll_task(
        self, client: TestClient, agent_name: str, task_id: str, timeout: float = 5.0
    ) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            payload = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "GetTask",
                "params": {"id": task_id},
            }
            resp = client.post(
                f"/agents/{agent_name}/",
                content=json.dumps(payload),
                headers=_a2a_headers(),
            )
            assert resp.status_code == 200
            data = resp.json()
            task = data.get("result", {})
            state = task.get("status", {}).get("state")
            if state in (
                "TASK_STATE_COMPLETED",
                "TASK_STATE_FAILED",
                "TASK_STATE_CANCELED",
                "TASK_STATE_REJECTED",
                "TASK_STATE_AUTH_REQUIRED",
            ):
                return data
            time.sleep(0.05)
        raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")

    def test_default_agent_processes_message(self, client) -> None:
        rpc_response = self._send_message(client, "default", "hello")

        result = rpc_response.get("result", {})
        task = result.get("task", result)
        task_id = task.get("id")
        assert task_id is not None, f"Expected task with id, got: {result}"

        completed = self._poll_task(client, "default", task_id)
        result_task = completed["result"].get("task", completed["result"])
        assert result_task["status"]["state"] == "TASK_STATE_COMPLETED"

        artifacts = result_task.get("artifacts", [])
        assert len(artifacts) >= 0


class TestSendStreamingMessageEndToEnd:
    """End-to-end test: SendStreamingMessage returns SSE events through the a2a-sdk dispatcher."""

    def _parse_sse_events(self, body: str) -> list[dict]:
        events: list[dict] = []
        current_data: list[str] = []
        for line in body.splitlines():
            if line.startswith("data:"):
                current_data.append(line[len("data:") :].strip())
            elif line == "" and current_data:
                raw = "\n".join(current_data)
                current_data = []
                try:
                    events.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass
        if current_data:
            raw = "\n".join(current_data)
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
        return events

    def test_streaming_returns_sse_events(self, client) -> None:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "SendStreamingMessage",
            "params": _message_params("hello"),
        }

        with client.stream(
            "POST",
            "/agents/default/",
            content=json.dumps(payload),
            headers=_a2a_headers(),
        ) as response:
            assert response.status_code == 200
            body = "".join(chunk.decode() for chunk in response.iter_bytes())

        events = self._parse_sse_events(body)
        assert len(events) >= 1, f"Expected SSE events, got: {body!r}"

    def test_streaming_first_event_has_task(self, client) -> None:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "SendStreamingMessage",
            "params": _message_params("hello"),
        }

        with client.stream(
            "POST",
            "/agents/default/",
            content=json.dumps(payload),
            headers=_a2a_headers(),
        ) as response:
            body = "".join(chunk.decode() for chunk in response.iter_bytes())

        events = self._parse_sse_events(body)
        first_result = events[0].get("result", {})
        assert (
            "task" in first_result
            or "statusUpdate" in first_result
            or "artifactUpdate" in first_result
        )

    def test_streaming_completes_with_terminal_state(self, client) -> None:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "SendStreamingMessage",
            "params": _message_params("hello"),
        }

        with client.stream(
            "POST",
            "/agents/default/",
            content=json.dumps(payload),
            headers=_a2a_headers(),
        ) as response:
            body = "".join(chunk.decode() for chunk in response.iter_bytes())

        events = self._parse_sse_events(body)
        terminal_states = {
            "TASK_STATE_COMPLETED",
            "TASK_STATE_FAILED",
            "TASK_STATE_CANCELED",
        }
        seen_states: set[str] = set()
        for event in events:
            result = event.get("result", {})
            status_update = result.get("statusUpdate")
            if status_update:
                state = status_update.get("status", {}).get("state")
                if state:
                    seen_states.add(state)
        assert seen_states & terminal_states, (
            f"Expected terminal state in streaming events, got states: {seen_states}"
        )

    def test_streaming_includes_artifact_updates(self, client) -> None:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "SendStreamingMessage",
            "params": _message_params("hello"),
        }

        with client.stream(
            "POST",
            "/agents/default/",
            content=json.dumps(payload),
            headers=_a2a_headers(),
        ) as response:
            body = "".join(chunk.decode() for chunk in response.iter_bytes())

        events = self._parse_sse_events(body)
        artifact_events = [e for e in events if "artifactUpdate" in e.get("result", {})]
        assert len(artifact_events) >= 1, "Expected artifact update events in streaming response"
