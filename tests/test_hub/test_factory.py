"""Tests for AgentFactory — AgentSpec → FastAPI sub-app via a2a-sdk."""

from __future__ import annotations

from fastapi import FastAPI

from fin_assist.agents.spec import AgentSpec
from fin_assist.config.schema import AgentConfig
from fin_assist.hub.context_store import ContextStore
from fin_assist.hub.factory import AgentFactory


def _make_factory() -> AgentFactory:
    context_store = ContextStore(db_path=":memory:")
    return AgentFactory(context_store=context_store)


def _make_default_agent(mock_config, mock_credentials) -> AgentSpec:
    return AgentSpec(
        name="default",
        agent_config=AgentConfig(
            description="Default agent",
            system_prompt="chain-of-thought",
            output_type="text",
        ),
        config=mock_config,
        credentials=mock_credentials,
    )


def _make_shell_agent(mock_config, mock_credentials) -> AgentSpec:
    return AgentSpec(
        name="shell",
        agent_config=AgentConfig(
            description="Shell agent",
            system_prompt="shell",
            output_type="command",
            thinking="off",
            serving_modes=["do"],
            requires_approval=True,
            tags=["shell", "one-shot"],
        ),
        config=mock_config,
        credentials=mock_credentials,
    )


class TestAgentFactoryCreation:
    def test_can_be_instantiated(self) -> None:
        assert _make_factory() is not None


class TestCreateA2AApp:
    def test_returns_fastapi_instance(self, mock_config, mock_credentials) -> None:
        app = _make_factory().create_a2a_app(_make_shell_agent(mock_config, mock_credentials))
        assert isinstance(app, FastAPI)

    def test_app_state_has_agent_card(self, mock_config, mock_credentials) -> None:
        app = _make_factory().create_a2a_app(_make_shell_agent(mock_config, mock_credentials))
        assert app.state.agent_card is not None

    def test_agent_card_name_matches(self, mock_config, mock_credentials) -> None:
        agent = _make_shell_agent(mock_config, mock_credentials)
        app = _make_factory().create_a2a_app(agent)
        assert app.state.agent_card.name == agent.name

    def test_agent_card_description_matches(self, mock_config, mock_credentials) -> None:
        agent = _make_shell_agent(mock_config, mock_credentials)
        app = _make_factory().create_a2a_app(agent)
        assert app.state.agent_card.description == agent.description

    def test_agent_card_has_extensions(self, mock_config, mock_credentials) -> None:
        agent = _make_shell_agent(mock_config, mock_credentials)
        app = _make_factory().create_a2a_app(agent)
        card = app.state.agent_card
        ext_uris = [e.uri for e in card.capabilities.extensions]
        assert "fin_assist:meta" in ext_uris

    def test_extension_encodes_serving_modes_for_shell(self, mock_config, mock_credentials) -> None:
        agent = _make_shell_agent(mock_config, mock_credentials)
        app = _make_factory().create_a2a_app(agent)
        card = app.state.agent_card
        meta_ext = next(e for e in card.capabilities.extensions if e.uri == "fin_assist:meta")
        params = dict(meta_ext.params)
        assert params.get("serving_modes") == ["do"]
        assert params.get("requires_approval") is True

    def test_extension_encodes_serving_modes_for_default(
        self, mock_config, mock_credentials
    ) -> None:
        agent = _make_default_agent(mock_config, mock_credentials)
        app = _make_factory().create_a2a_app(agent)
        card = app.state.agent_card
        meta_ext = next(e for e in card.capabilities.extensions if e.uri == "fin_assist:meta")
        params = dict(meta_ext.params)
        assert params.get("serving_modes") == ["do", "talk"]

    def test_agent_card_has_streaming_capability(self, mock_config, mock_credentials) -> None:
        agent = _make_shell_agent(mock_config, mock_credentials)
        app = _make_factory().create_a2a_app(agent)
        assert app.state.agent_card.capabilities.streaming is True

    def test_different_agents_produce_different_apps(self, mock_config, mock_credentials) -> None:
        factory = _make_factory()
        shell_app = factory.create_a2a_app(_make_shell_agent(mock_config, mock_credentials))
        default_app = factory.create_a2a_app(_make_default_agent(mock_config, mock_credentials))
        assert shell_app is not default_app
        assert shell_app.state.agent_card.name != default_app.state.agent_card.name
