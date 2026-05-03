"""Tests for AgentSpec — the single config-driven agent specification class."""

from __future__ import annotations

from unittest.mock import MagicMock

from fin_assist.agents.spec import AgentSpec, _CONTEXT_TYPE_HINTS
from fin_assist.agents.metadata import AgentCardMeta, AgentResult, MissingCredentialsError
from fin_assist.agents.results import CommandResult
from fin_assist.config.schema import AgentConfig, SkillConfig

_MAP = _CONTEXT_TYPE_HINTS


def _skills(*tool_lists: list[str]) -> dict[str, SkillConfig]:
    result: dict[str, SkillConfig] = {}
    for i, tools in enumerate(tool_lists):
        result[f"skill_{i}"] = SkillConfig(tools=tools)
    return result


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
        assert meta.supports_thinking is True
        assert meta.supports_model_selection is True
        assert meta.supported_providers is None
        assert meta.color_scheme is None
        assert meta.tags == []

    def test_equality(self) -> None:
        assert AgentCardMeta() == AgentCardMeta()
        assert AgentCardMeta(serving_modes=["do"]) != AgentCardMeta()

    def test_one_shot_meta(self) -> None:
        meta = AgentCardMeta(serving_modes=["do"], supports_thinking=False)
        assert meta.serving_modes == ["do"]
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


# -- AgentSpec property tests -----------------------------------------------


class TestAgentSpecProperties:
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
        agent = AgentSpec(
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
        agent = AgentSpec(
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


# -- AgentSpec agent_card_metadata tests -------------------------------------


class TestAgentSpecCardMetadata:
    def test_default_serving_modes(self, mock_config, mock_credentials) -> None:
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.agent_card_metadata.serving_modes == ["do", "talk"]

    def test_shell_serving_modes(self, mock_config, mock_credentials) -> None:
        agent = _make_shell_agent(mock_config, mock_credentials)
        assert agent.agent_card_metadata.serving_modes == ["do"]

    def test_supported_context_types_from_tools(self, mock_config, mock_credentials) -> None:
        agent = AgentSpec(
            name="test",
            agent_config=AgentConfig(skills=_skills(["read_file", "git", "gh"])),
            config=mock_config,
            credentials=mock_credentials,
        )
        meta = agent.agent_card_metadata
        assert _MAP["read_file"] in meta.supported_context_types
        assert _MAP["git"] in meta.supported_context_types
        assert _MAP["gh"] in meta.supported_context_types
        assert "env" not in meta.supported_context_types

    def test_no_context_types_when_no_tools(self, mock_config, mock_credentials) -> None:
        agent = AgentSpec(
            name="test",
            agent_config=AgentConfig(skills={}),
            config=mock_config,
            credentials=mock_credentials,
        )
        assert agent.agent_card_metadata.supported_context_types == []

    def test_thinking_on(self, mock_config, mock_credentials) -> None:
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.agent_card_metadata.supports_thinking is True

    def test_thinking_off(self, mock_config, mock_credentials) -> None:
        agent = _make_shell_agent(mock_config, mock_credentials)
        assert agent.agent_card_metadata.supports_thinking is False

    def test_shell_tags(self, mock_config, mock_credentials) -> None:
        agent = _make_shell_agent(mock_config, mock_credentials)
        assert agent.agent_card_metadata.tags == ["shell", "one-shot"]


# -- AgentSpec supports_context tests ----------------------------------------


class TestAgentSpecSupportsContext:
    def test_supports_context_types_from_tools(self, mock_config, mock_credentials) -> None:
        agent = AgentSpec(
            name="test",
            agent_config=AgentConfig(skills=_skills(["read_file", "git"])),
            config=mock_config,
            credentials=mock_credentials,
        )
        assert agent.supports_context(_MAP["read_file"]) is True
        assert agent.supports_context(_MAP["git"]) is True
        assert agent.supports_context(_MAP["gh"]) is False
        assert agent.supports_context("env") is False

    def test_supports_no_context_when_no_tools(self, mock_config, mock_credentials) -> None:
        agent = AgentSpec(
            name="test",
            agent_config=AgentConfig(skills={}),
            config=mock_config,
            credentials=mock_credentials,
        )
        assert agent.supports_context("file") is False
        assert agent.supports_context("git") is False

    def test_rejects_unknown_context_type(self, mock_config, mock_credentials) -> None:
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.supports_context("unknown_type") is False


# -- AgentSpec credential check tests ----------------------------------------


class TestAgentSpecCheckCredentials:
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


# -- AgentSpec get_enabled_providers tests ------------------------------------


class TestAgentSpecGetEnabledProviders:
    def test_returns_default_provider_when_no_others_configured(
        self, mock_config, mock_credentials
    ) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.providers = {}
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.get_enabled_providers() == ["anthropic"]

    def test_includes_enabled_additional_providers(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        extra = MagicMock()
        extra.enabled = True
        mock_config.providers = {"openrouter": extra}
        agent = _make_default_agent(mock_config, mock_credentials)
        providers = agent.get_enabled_providers()
        assert "anthropic" in providers
        assert "openrouter" in providers

    def test_excludes_disabled_providers(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        extra = MagicMock()
        extra.enabled = False
        mock_config.providers = {"openrouter": extra}
        agent = _make_default_agent(mock_config, mock_credentials)
        assert "openrouter" not in agent.get_enabled_providers()

    def test_default_provider_not_duplicated(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        anthropic_cfg = MagicMock()
        anthropic_cfg.enabled = True
        mock_config.providers = {"anthropic": anthropic_cfg}
        agent = _make_default_agent(mock_config, mock_credentials)
        providers = agent.get_enabled_providers()
        assert providers.count("anthropic") == 1


# -- AgentSpec get_model_name tests ------------------------------------------


class TestAgentSpecGetModelName:
    def test_returns_provider_specific_model_when_set(self, mock_config, mock_credentials) -> None:
        provider_cfg = MagicMock()
        provider_cfg.default_model = "claude-opus-4"
        mock_config.providers = {"anthropic": provider_cfg}
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.get_model_name("anthropic", "default-model") == "claude-opus-4"

    def test_falls_back_to_default_model(self, mock_config, mock_credentials) -> None:
        provider_cfg = MagicMock()
        provider_cfg.default_model = None
        mock_config.providers = {"anthropic": provider_cfg}
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.get_model_name("anthropic", "fallback-model") == "fallback-model"

    def test_falls_back_when_provider_not_in_config(self, mock_config, mock_credentials) -> None:
        mock_config.providers = {}
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.get_model_name("openai", "gpt-4o") == "gpt-4o"


# -- AgentSpec get_base_url tests ---------------------------------------------


class TestAgentSpecGetBaseUrl:
    def test_returns_base_url_when_set(self, mock_config, mock_credentials) -> None:
        provider_cfg = MagicMock()
        provider_cfg.base_url = "https://my-proxy.example.com/v1"
        mock_config.providers = {"anthropic": provider_cfg}
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.get_base_url("anthropic") == "https://my-proxy.example.com/v1"

    def test_returns_none_when_base_url_not_set(self, mock_config, mock_credentials) -> None:
        provider_cfg = MagicMock()
        provider_cfg.base_url = None
        mock_config.providers = {"anthropic": provider_cfg}
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.get_base_url("anthropic") is None

    def test_returns_none_when_provider_not_in_config(self, mock_config, mock_credentials) -> None:
        mock_config.providers = {}
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.get_base_url("openai") is None


# -- AgentSpec get_api_key tests ---------------------------------------------


class TestAgentSpecGetApiKey:
    def test_delegates_to_credential_store(self, mock_config, mock_credentials) -> None:
        mock_credentials.get_api_key.return_value = "sk-test-key"
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.get_api_key("anthropic") == "sk-test-key"

    def test_returns_none_when_missing(self, mock_config, mock_credentials) -> None:
        mock_credentials.get_api_key.return_value = None
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.get_api_key("anthropic") is None


# -- AgentSpec thinking / default_model properties ---------------------------


class TestAgentSpecConfigProperties:
    def test_tools_from_skills(self, mock_config, mock_credentials) -> None:
        agent = AgentSpec(
            name="test",
            agent_config=AgentConfig(skills=_skills(["read_file", "git"])),
            config=mock_config,
            credentials=mock_credentials,
        )
        assert agent.tools == ["read_file", "git"]

    def test_tools_from_multiple_skills(self, mock_config, mock_credentials) -> None:
        agent = AgentSpec(
            name="test",
            agent_config=AgentConfig(skills=_skills(["read_file"], ["git"])),
            config=mock_config,
            credentials=mock_credentials,
        )
        assert agent.tools == ["read_file", "git"]

    def test_tools_default_empty(self, mock_config, mock_credentials) -> None:
        agent = AgentSpec(
            name="test",
            agent_config=AgentConfig(skills={}),
            config=mock_config,
            credentials=mock_credentials,
        )
        assert agent.tools == []

    def test_thinking_from_config(self, mock_config, mock_credentials) -> None:
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.thinking == "medium"

    def test_thinking_off(self, mock_config, mock_credentials) -> None:
        agent = _make_shell_agent(mock_config, mock_credentials)
        assert agent.thinking == "off"

    def test_thinking_none(self, mock_config, mock_credentials) -> None:
        agent = AgentSpec(
            name="test",
            agent_config=AgentConfig(thinking=None),
            config=mock_config,
            credentials=mock_credentials,
        )
        assert agent.thinking is None

    def test_default_model_from_config(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_model = "claude-opus-4"
        agent = _make_default_agent(mock_config, mock_credentials)
        assert agent.default_model == "claude-opus-4"
