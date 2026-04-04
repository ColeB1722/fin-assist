"""Tests for credential pre-check on BaseAgent."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from fin_assist.agents.base import BaseAgent, MissingCredentialsError


# -- Fixtures -----------------------------------------------------------------


class DummyAgent(BaseAgent[str]):
    """Minimal concrete agent for testing credential checks."""

    @property
    def name(self) -> str:
        return "dummy"

    @property
    def description(self) -> str:
        return "A dummy agent"

    @property
    def system_prompt(self) -> str:
        return "You are a dummy."

    @property
    def output_type(self) -> type[str]:
        return str


# -- check_credentials tests --------------------------------------------------


class TestCheckCredentials:
    def test_returns_empty_when_all_keys_present(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = "sk-test"

        agent = DummyAgent(mock_config, mock_credentials)
        assert agent.check_credentials() == []

    def test_returns_missing_provider_when_key_absent(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = None

        agent = DummyAgent(mock_config, mock_credentials)
        missing = agent.check_credentials()
        assert "anthropic" in missing

    def test_skips_providers_that_dont_require_keys(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "ollama"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = None

        agent = DummyAgent(mock_config, mock_credentials)
        assert agent.check_credentials() == []

    def test_checks_all_enabled_providers(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        extra = MagicMock()
        extra.enabled = True
        mock_config.providers = {"openrouter": extra}
        mock_credentials.get_api_key.return_value = None

        agent = DummyAgent(mock_config, mock_credentials)
        missing = agent.check_credentials()
        assert "anthropic" in missing
        assert "openrouter" in missing

    def test_partial_credentials_returns_only_missing(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        extra = MagicMock()
        extra.enabled = True
        mock_config.providers = {"openrouter": extra}
        # anthropic has a key, openrouter does not
        mock_credentials.get_api_key.side_effect = lambda p: "sk-test" if p == "anthropic" else None

        agent = DummyAgent(mock_config, mock_credentials)
        missing = agent.check_credentials()
        assert "anthropic" not in missing
        assert "openrouter" in missing

    def test_unknown_provider_treated_as_not_requiring_key(
        self, mock_config, mock_credentials
    ) -> None:
        """Providers not in PROVIDER_META are assumed to not require a key."""
        mock_config.general.default_provider = "some_unknown"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = None

        agent = DummyAgent(mock_config, mock_credentials)
        assert agent.check_credentials() == []


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


# -- _build_model raises MissingCredentialsError ------------------------------


class TestBuildModelCredentialCheck:
    def test_raises_when_credentials_missing(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.general.default_model = "claude-sonnet-4-6"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = None

        agent = DummyAgent(mock_config, mock_credentials)
        with pytest.raises(MissingCredentialsError) as exc_info:
            agent._build_model()
        assert "anthropic" in exc_info.value.providers

    def test_does_not_raise_when_credentials_present(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.general.default_model = "claude-sonnet-4-6"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = "sk-test"

        agent = DummyAgent(mock_config, mock_credentials)
        # Should not raise — will fail deeper in provider construction, not credential check
        # We mock the registry to avoid the actual provider call
        mock_registry = MagicMock()
        mock_registry.create_model.return_value = MagicMock()

        from unittest.mock import patch

        with patch.object(agent, "_get_registry", return_value=mock_registry):
            model = agent._build_model()
        assert model is not None
