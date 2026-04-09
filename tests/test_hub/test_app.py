"""Tests for the Agent Hub Starlette app."""

from __future__ import annotations

import json
import time
import uuid
from unittest.mock import patch

import pytest
from pydantic_ai.models.test import TestModel
from starlette.testclient import TestClient

from fin_assist.hub.app import create_hub_app


@pytest.fixture
def mock_agents(mock_config, mock_credentials):
    from fin_assist.agents.default import DefaultAgent
    from fin_assist.agents.shell import ShellAgent

    with patch.object(DefaultAgent, "build_model", return_value=TestModel()):
        with patch.object(ShellAgent, "build_model", return_value=TestModel()):
            yield [
                ShellAgent(mock_config, mock_credentials),
                DefaultAgent(mock_config, mock_credentials),
            ]


@pytest.fixture
def client(mock_agents):
    app = create_hub_app(agents=mock_agents)
    # Use context manager so sub-app lifespans (worker + broker) are initialised
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


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

    def test_unknown_agent_returns_404(self, client) -> None:
        resp = client.get("/agents/nonexistent/.well-known/agent-card.json")
        assert resp.status_code == 404


class TestMessageSendEndToEnd:
    """End-to-end test: send a message and verify the worker processes it."""

    def _send_message(self, client: TestClient, agent_name: str, text: str) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "kind": "message",
                    "messageId": str(uuid.uuid4()),
                    "parts": [{"kind": "text", "text": text}],
                }
            },
        }
        resp = client.post(
            f"/agents/{agent_name}/",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
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
                "method": "tasks/get",
                "params": {"id": task_id},
            }
            resp = client.post(
                f"/agents/{agent_name}/",
                content=json.dumps(payload),
                headers={"Content-Type": "application/json"},
            )
            assert resp.status_code == 200
            data = resp.json()
            task = data.get("result", {})
            state = task.get("status", {}).get("state")
            if state in ("completed", "failed", "canceled", "rejected", "auth-required"):
                return data
            time.sleep(0.05)
        raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")

    def test_default_agent_processes_message(self, client) -> None:
        """Send a message to the default agent and verify it completes."""
        rpc_response = self._send_message(client, "default", "hello")

        # message/send returns the task in 'submitted' state
        task = rpc_response.get("result", {})
        assert task.get("kind") == "task"
        task_id = task["id"]

        # Poll until the worker processes it
        completed = self._poll_task(client, "default", task_id)
        result_task = completed["result"]
        assert result_task["status"]["state"] == "completed"

        # The TestModel returns text — verify artifacts contain output
        artifacts = result_task.get("artifacts", [])
        assert len(artifacts) > 0
        parts = artifacts[0].get("parts", [])
        assert any(p.get("kind") == "text" for p in parts)
