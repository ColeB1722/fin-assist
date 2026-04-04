"""Tests for AgentFactory — BaseAgent → fasta2a ASGI sub-app."""

from __future__ import annotations

import json

from fasta2a.applications import FastA2A

from fin_assist.hub.factory import AgentFactory
from fin_assist.hub.storage import SQLiteStorage


def _make_factory() -> AgentFactory:
    storage = SQLiteStorage(db_path=":memory:")
    return AgentFactory(storage=storage)


class TestAgentFactoryCreation:
    def test_can_be_instantiated(self) -> None:
        assert _make_factory() is not None


class TestCreateA2AApp:
    def test_returns_fasta2a_instance(self, mock_config, mock_credentials) -> None:
        from fin_assist.agents.shell import ShellAgent

        app = _make_factory().create_a2a_app(ShellAgent(mock_config, mock_credentials))
        assert isinstance(app, FastA2A)

    def test_app_name_matches_agent(self, mock_config, mock_credentials) -> None:
        from fin_assist.agents.shell import ShellAgent

        agent = ShellAgent(mock_config, mock_credentials)
        app = _make_factory().create_a2a_app(agent)
        assert app.name == agent.name

    def test_app_description_matches_agent(self, mock_config, mock_credentials) -> None:
        from fin_assist.agents.shell import ShellAgent

        agent = ShellAgent(mock_config, mock_credentials)
        app = _make_factory().create_a2a_app(agent)
        assert app.description == agent.description

    def test_meta_skill_is_injected(self, mock_config, mock_credentials) -> None:
        """AgentCardMeta is encoded as a reserved skill with id 'fin_assist:meta'."""
        from fin_assist.agents.shell import ShellAgent

        agent = ShellAgent(mock_config, mock_credentials)
        app = _make_factory().create_a2a_app(agent)

        meta_skill = next((s for s in app.skills if s["id"] == "fin_assist:meta"), None)
        assert meta_skill is not None

    def test_meta_skill_encodes_multi_turn_false_for_shell(
        self, mock_config, mock_credentials
    ) -> None:
        from fin_assist.agents.shell import ShellAgent

        agent = ShellAgent(mock_config, mock_credentials)
        app = _make_factory().create_a2a_app(agent)

        meta_skill = next(s for s in app.skills if s["id"] == "fin_assist:meta")
        meta = json.loads(meta_skill["description"])
        assert meta["multi_turn"] is False
        assert meta["supports_thinking"] is False

    def test_meta_skill_encodes_multi_turn_true_for_default(
        self, mock_config, mock_credentials
    ) -> None:
        from fin_assist.agents.default import DefaultAgent

        agent = DefaultAgent(mock_config, mock_credentials)
        app = _make_factory().create_a2a_app(agent)

        meta_skill = next(s for s in app.skills if s["id"] == "fin_assist:meta")
        meta = json.loads(meta_skill["description"])
        assert meta["multi_turn"] is True

    def test_agent_tags_appear_in_skill_tags(self, mock_config, mock_credentials) -> None:
        from fin_assist.agents.shell import ShellAgent

        agent = ShellAgent(mock_config, mock_credentials)
        app = _make_factory().create_a2a_app(agent)

        meta_skill = next(s for s in app.skills if s["id"] == "fin_assist:meta")
        assert "shell" in meta_skill["tags"]

    def test_different_agents_produce_different_apps(self, mock_config, mock_credentials) -> None:
        from fin_assist.agents.default import DefaultAgent
        from fin_assist.agents.shell import ShellAgent

        factory = _make_factory()
        shell_app = factory.create_a2a_app(ShellAgent(mock_config, mock_credentials))
        default_app = factory.create_a2a_app(DefaultAgent(mock_config, mock_credentials))
        assert shell_app is not default_app
        assert shell_app.name != default_app.name
