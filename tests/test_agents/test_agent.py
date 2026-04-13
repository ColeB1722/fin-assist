"""Tests for ConfigAgent — the single config-driven agent class."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai import Agent as PydanticAgent

from fin_assist.agents.agent import ConfigAgent
from fin_assist.agents.metadata import AgentCardMeta, AgentResult, MissingCredentialsError
from fin_assist.agents.results import CommandResult
from fin_assist.config.schema import AgentConfig
from fin_assist.context.base import ContextType


def _make_default_agent(mock_config, mock_credentials) -> ConfigAgent:
    return ConfigAgent(
        name="default",
        agent_config=AgentConfig(
            description="Default agent",
            system_prompt="chain-of-thought",
            output_type="text",
        ),
        config=mock_config,
        credentials=mock_credentials,
    )


def _make_shell_agent(mock_config, mock_credentials) -> ConfigAgent:
    return ConfigAgent(
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


# -- AgentResult tests --------------------------------------------------------


class TestAgentResult:
    def test_creation(self) -> None:
        result = AgentResult(success=True, output="ls -la", warnings=[], metadata={})
        assert result.success is True
        assert result.output == "ls -la"
        assert result.warnings == []
        assert result.metadata == {}

    def test_with_warnings(self) -> None:
        result = AgentResult(
            success=True,
            output="rm -rf /",
            warnings=["Destructive operation"],
            metadata={},
        )
        assert result.warnings == ["Destructive operation"]

    def test_with_metadata(self) -> None:
        result = AgentResult(
            success=True,
            output="echo hello",
            warnings=[],
            metadata={"provider": "anthropic", "model": "claude-sonnet-4-6"},
        )
        assert result.metadata["provider"] == "anthropic"

    def test_default_values(self) -> None:
        result = AgentResult(success=True, output="test")
        assert result.warnings == []
        assert result.metadata == {}

    def test_output_is_str(self) -> None:
        result = AgentResult(success=True, output="ls")
        assert isinstance(result.output, str)


# -- AgentCardMeta tests -----------------------------------------------------


class TestAgentCardMeta:
    def test_defaults(self) -> None:
        meta = AgentCardMeta()
        assert meta.serving_modes == ["do", "talk"]
        assert meta.multi_turn is True
        assert meta.supports_thinking is True
        assert meta.supports_model_selection is True
        assert meta.supported_providers is None
        assert meta.color_scheme is None
        assert meta.tags == []

    def test_equality(self) -> None:
        assert AgentCardMeta() == AgentCardMeta()
        assert AgentCardMeta(multi_turn=False) != AgentCardMeta()

    def test_one_shot_meta(self) -> None:
        meta = AgentCardMeta(multi_turn=False, supports_thinking=False)
        assert meta.multi_turn is False
        assert meta.supports_thinking is False
        assert meta.supports_model_selection is True


# -- MissingCredentialsError tests --------------------------------------------


class TestMissingCredentialsError:
    def test_is_exception(self) -> None:
        assert issubclass(MissingCredentialsError, Exception)

    def test_carries_provider_list(self) -> None:
        err = MissingCredentialsError(providers=["anthropic", "openrouter"])
        assert err.providers == ["anthropic", "openrouter"]

    def test_str_includes_provider_names(self) -> None:
        err = MissingCredentialsError(providers=["anthropic"])
        msg = str(err)
        assert "anthropic" in msg

    def test_str_includes_env_var_hint(self) -> None:
        err = MissingCredentialsError(providers=["anthropic"])
        msg = str(err)
        assert "ANTHROPIC_API_KEY" in msg


# -- ConfigAgent property tests -----------------------------------------------


class TestConfigAgentProperties:
    def test_default_name(self, mock_config, mock_credentials) -> None:
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.name == "default"

    def test_shell_name(self, mock_config, mock_credentials) -> None:
        agent = _make_shell_agent(mock_config, mock_credentials)
        assert agent.name == "shell"

    def test_description_from_config(self, mock_config, mock_credentials) -> None:
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.description == "Default agent"

    def test_description_fallback_when_empty(self, mock_config, mock_credentials) -> None:
        agent = ConfigAgent(
            name="test",
            agent_config=AgentConfig(description=""),
            config=mock_config,
            credentials=mock_credentials,
        )
        assert "test" in agent.description

    def test_system_prompt_resolves_from_registry(self, mock_config, mock_credentials) -> None:
        agent = _make_default_agent(mock_config, mock_credentials)
        assert "step-by-step" in agent.system_prompt.lower()

    def test_system_prompt_shell_resolves(self, mock_config, mock_credentials) -> None:
        agent = _make_shell_agent(mock_config, mock_credentials)
        assert "shell" in agent.system_prompt.lower()

    def test_system_prompt_passthrough_for_unknown(self, mock_config, mock_credentials) -> None:
        agent = ConfigAgent(
            name="custom",
            agent_config=AgentConfig(system_prompt="You are a custom agent."),
            config=mock_config,
            credentials=mock_credentials,
        )
        assert agent.system_prompt == "You are a custom agent."

    def test_output_type_text(self, mock_config, mock_credentials) -> None:
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.output_type is str

    def test_output_type_command(self, mock_config, mock_credentials) -> None:
        agent = _make_shell_agent(mock_config, mock_credentials)
        assert agent.output_type is CommandResult


# -- ConfigAgent agent_card_metadata tests -------------------------------------


class TestConfigAgentCardMetadata:
    def test_default_serving_modes(self, mock_config, mock_credentials) -> None:
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.agent_card_metadata.serving_modes == ["do", "talk"]
        assert agent.agent_card_metadata.multi_turn is True

    def test_shell_serving_modes(self, mock_config, mock_credentials) -> None:
        agent = _make_shell_agent(mock_config, mock_credentials)
        assert agent.agent_card_metadata.serving_modes == ["do"]
        assert agent.agent_card_metadata.multi_turn is False

    def test_shell_requires_approval(self, mock_config, mock_credentials) -> None:
        agent = _make_shell_agent(mock_config, mock_credentials)
        assert agent.agent_card_metadata.requires_approval is True

    def test_default_no_approval(self, mock_config, mock_credentials) -> None:
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.agent_card_metadata.requires_approval is False

    def test_thinking_on(self, mock_config, mock_credentials) -> None:
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.agent_card_metadata.supports_thinking is True

    def test_thinking_off(self, mock_config, mock_credentials) -> None:
        agent = _make_shell_agent(mock_config, mock_credentials)
        assert agent.agent_card_metadata.supports_thinking is False

    def test_shell_tags(self, mock_config, mock_credentials) -> None:
        agent = _make_shell_agent(mock_config, mock_credentials)
        assert agent.agent_card_metadata.tags == ["shell", "one-shot"]


# -- ConfigAgent supports_context tests ----------------------------------------


class TestConfigAgentSupportsContext:
    def test_supports_all_context_types_by_default(
        self, mock_config, mock_credentials, expected_context_types
    ) -> None:
        agent = _make_default_agent(mock_config, mock_credentials)
        for ct in expected_context_types:
            assert agent.supports_context(ct) is True

    def test_rejects_unknown_context_type(self, mock_config, mock_credentials) -> None:
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.supports_context("unknown_type") is False


# -- ConfigAgent build_pydantic_agent tests ------------------------------------


class TestConfigAgentBuildPydanticAgent:
    def test_returns_pydantic_agent(self, mock_config, mock_credentials) -> None:
        agent = _make_default_agent(mock_config, mock_credentials)
        built = agent.build_pydantic_agent()
        assert isinstance(built, PydanticAgent)

    def test_with_thinking(self, mock_config, mock_credentials) -> None:
        from pydantic_ai.capabilities import Thinking

        agent = _make_default_agent(mock_config, mock_credentials)
        built = agent.build_pydantic_agent()
        caps = built._root_capability.capabilities
        assert len(caps) == 1
        assert isinstance(caps[0], Thinking)

    def test_no_thinking_when_off(self, mock_config, mock_credentials) -> None:
        agent = _make_shell_agent(mock_config, mock_credentials)
        built = agent.build_pydantic_agent()
        assert not built._root_capability.capabilities

    @pytest.mark.parametrize("effort", ["off", None])
    def test_thinking_off_means_no_capabilities(
        self, mock_config, mock_credentials, effort
    ) -> None:
        agent = ConfigAgent(
            name="test",
            agent_config=AgentConfig(thinking=effort),
            config=mock_config,
            credentials=mock_credentials,
        )
        built = agent.build_pydantic_agent()
        assert not built._root_capability.capabilities


# -- ConfigAgent credential check tests ----------------------------------------


class TestConfigAgentCheckCredentials:
    def test_returns_empty_when_all_keys_present(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = "sk-test"

        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.check_credentials() == []

    def test_returns_missing_provider_when_key_absent(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = None

        agent = _make_default_agent(mock_config, mock_credentials)
        missing = agent.check_credentials()
        assert "anthropic" in missing

    def test_skips_providers_that_dont_require_keys(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "ollama"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = None

        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.check_credentials() == []

    def test_checks_all_enabled_providers(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        extra = MagicMock()
        extra.enabled = True
        mock_config.providers = {"openrouter": extra}
        mock_credentials.get_api_key.return_value = None

        agent = _make_default_agent(mock_config, mock_credentials)
        missing = agent.check_credentials()
        assert "anthropic" in missing
        assert "openrouter" in missing

    def test_partial_credentials_returns_only_missing(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        extra = MagicMock()
        extra.enabled = True
        mock_config.providers = {"openrouter": extra}
        mock_credentials.get_api_key.side_effect = lambda p: "sk-test" if p == "anthropic" else None

        agent = _make_default_agent(mock_config, mock_credentials)
        missing = agent.check_credentials()
        assert "anthropic" not in missing
        assert "openrouter" in missing

    def test_unknown_provider_treated_as_not_requiring_key(
        self, mock_config, mock_credentials
    ) -> None:
        mock_config.general.default_provider = "some_unknown"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = None

        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.check_credentials() == []


# -- ConfigAgent build_model tests ---------------------------------------------


class TestConfigAgentBuildModel:
    def test_uses_single_model_when_no_fallback(self, mock_config, mock_credentials) -> None:
        mock_model = MagicMock()

        with patch(
            "fin_assist.llm.model_registry.ProviderRegistry.create_model", return_value=mock_model
        ):
            agent = _make_default_agent(mock_config, mock_credentials)
            result = agent.build_model()
            assert result is mock_model

    def test_uses_fallback_when_multiple_providers_enabled(
        self, mock_config, mock_credentials
    ) -> None:
        mock_config.providers = {"openai": MagicMock(enabled=True)}
        mock_credentials.get_api_key.side_effect = lambda p: {
            "anthropic": "key1",
            "openai": "key2",
        }.get(p)

        mock_model1 = MagicMock()
        mock_model2 = MagicMock()

        with patch("fin_assist.llm.model_registry.ProviderRegistry.create_model") as mock_create:
            mock_create.side_effect = [mock_model1, mock_model2]

            with patch("pydantic_ai.models.fallback.FallbackModel") as mock_fallback_class:
                mock_fallback_instance = MagicMock()
                mock_fallback_class.return_value = mock_fallback_instance

                agent = _make_default_agent(mock_config, mock_credentials)
                result = agent.build_model()

                assert result is mock_fallback_instance
                mock_fallback_class.assert_called_once_with(mock_model1, mock_model2)

    def test_raises_when_credentials_missing(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.general.default_model = "claude-sonnet-4-6"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = None

        agent = _make_default_agent(mock_config, mock_credentials)
        with pytest.raises(MissingCredentialsError) as exc_info:
            agent.build_model()
        assert "anthropic" in exc_info.value.providers

    def test_does_not_raise_when_credentials_present(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.general.default_model = "claude-sonnet-4-6"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = "sk-test"

        agent = _make_default_agent(mock_config, mock_credentials)
        mock_registry = MagicMock()
        mock_registry.create_model.return_value = MagicMock()

        with patch.object(agent, "_get_registry", return_value=mock_registry):
            model = agent.build_model()
        assert model is not None


# -- _get_registry tests ------------------------------------------------------


class TestGetRegistry:
    def test_returns_provider_registry_instance(self, mock_config, mock_credentials) -> None:
        from fin_assist.llm.model_registry import ProviderRegistry

        agent = _make_default_agent(mock_config, mock_credentials)
        registry = agent._get_registry()
        assert isinstance(registry, ProviderRegistry)

    def test_returns_same_instance_on_repeated_calls(self, mock_config, mock_credentials) -> None:
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent._get_registry() is agent._get_registry()


# -- _get_enabled_providers tests ---------------------------------------------


class TestGetEnabledProviders:
    def test_returns_default_provider_when_no_others_configured(
        self, mock_config, mock_credentials
    ) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.providers = {}
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent._get_enabled_providers() == ["anthropic"]

    def test_includes_enabled_additional_providers(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        extra = MagicMock()
        extra.enabled = True
        mock_config.providers = {"openrouter": extra}
        agent = _make_default_agent(mock_config, mock_credentials)
        providers = agent._get_enabled_providers()
        assert "anthropic" in providers
        assert "openrouter" in providers

    def test_excludes_disabled_providers(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        extra = MagicMock()
        extra.enabled = False
        mock_config.providers = {"openrouter": extra}
        agent = _make_default_agent(mock_config, mock_credentials)
        assert "openrouter" not in agent._get_enabled_providers()

    def test_default_provider_not_duplicated(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        anthropic_cfg = MagicMock()
        anthropic_cfg.enabled = True
        mock_config.providers = {"anthropic": anthropic_cfg}
        agent = _make_default_agent(mock_config, mock_credentials)
        providers = agent._get_enabled_providers()
        assert providers.count("anthropic") == 1


# -- _get_model_name tests ----------------------------------------------------


class TestGetModelName:
    def test_returns_provider_specific_model_when_set(self, mock_config, mock_credentials) -> None:
        provider_cfg = MagicMock()
        provider_cfg.default_model = "claude-opus-4"
        mock_config.providers = {"anthropic": provider_cfg}
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent._get_model_name("anthropic", "default-model") == "claude-opus-4"

    def test_falls_back_to_default_model(self, mock_config, mock_credentials) -> None:
        provider_cfg = MagicMock()
        provider_cfg.default_model = None
        mock_config.providers = {"anthropic": provider_cfg}
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent._get_model_name("anthropic", "fallback-model") == "fallback-model"

    def test_falls_back_when_provider_not_in_config(self, mock_config, mock_credentials) -> None:
        mock_config.providers = {}
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent._get_model_name("openai", "gpt-4o") == "gpt-4o"
