"""Tests for the Agent Hub Starlette app."""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from fin_assist.hub.app import create_hub_app


@pytest.fixture
def mock_agents(mock_config, mock_credentials):
    from fin_assist.agents.default import DefaultAgent
    from fin_assist.agents.shell import ShellAgent

    return [
        ShellAgent(mock_config, mock_credentials),
        DefaultAgent(mock_config, mock_credentials),
    ]


@pytest.fixture
def client(mock_agents):
    app = create_hub_app(agents=mock_agents)
    # Use context manager so sub-app lifespans (TaskManager) are initialised
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
