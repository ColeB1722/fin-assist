"""Tests for configuration schema and loader."""

import os
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from fin_assist.config.loader import load_config
from fin_assist.config.schema import (
    Config,
    ContextSettings,
    GeneralSettings,
    ProviderConfig,
    ServerSettings,
)


class TestGeneralSettings:
    """Tests for GeneralSettings."""

    def test_general_settings_defaults(self) -> None:
        """Test default values for GeneralSettings."""
        settings = GeneralSettings()
        assert settings.default_provider == "anthropic"
        assert settings.default_model == "claude-sonnet-4-6"
        assert settings.thinking_effort == "medium"
        assert settings.keybinding == "ctrl-enter"

    def test_general_settings_from_env(self) -> None:
        """Test that GeneralSettings reads from environment variables with FIN_ prefix."""
        with patch.dict(
            os.environ,
            {
                "FIN_DEFAULT_PROVIDER": "openrouter",
                "FIN_DEFAULT_MODEL": "gpt-4o",
                "FIN_KEYBINDING": "ctrl-space",
            },
        ):
            settings = GeneralSettings()
            assert settings.default_provider == "openrouter"
            assert settings.default_model == "gpt-4o"
            assert settings.keybinding == "ctrl-space"

    def test_general_settings_explicit_override(self) -> None:
        """Test that explicit values override environment variables."""
        with patch.dict(os.environ, {"FIN_DEFAULT_PROVIDER": "openrouter"}):
            settings = GeneralSettings(default_provider="ollama")
            assert settings.default_provider == "ollama"


class TestContextSettings:
    """Tests for ContextSettings."""

    def test_context_settings_defaults(self) -> None:
        """Test default values for ContextSettings."""
        settings = ContextSettings()
        assert settings.max_file_size == 100_000
        assert settings.max_history_items == 50
        assert settings.include_git_status is True
        assert settings.include_env_vars == ["PATH", "HOME", "USER", "PWD"]

    def test_context_settings_custom_values(self) -> None:
        """Test ContextSettings with custom values."""
        settings = ContextSettings(
            max_file_size=50_000,
            max_history_items=100,
            include_git_status=False,
            include_env_vars=["PATH", "HOME"],
        )
        assert settings.max_file_size == 50_000
        assert settings.max_history_items == 100
        assert settings.include_git_status is False
        assert settings.include_env_vars == ["PATH", "HOME"]


class TestServerSettings:
    """Tests for ServerSettings."""

    def test_server_settings_defaults(self) -> None:
        settings = ServerSettings()
        assert settings.host == "127.0.0.1"
        assert settings.port == 4096
        assert settings.db_path == "~/.local/share/fin/hub.db"

    def test_server_settings_custom_values(self) -> None:
        settings = ServerSettings(host="0.0.0.0", port=8080, db_path="/tmp/test.db")
        assert settings.host == "0.0.0.0"
        assert settings.port == 8080
        assert settings.db_path == "/tmp/test.db"


class TestProviderConfig:
    """Tests for ProviderConfig."""

    def test_provider_config_defaults(self) -> None:
        """Test default values for ProviderConfig."""
        config = ProviderConfig()
        assert config.enabled is True
        assert config.base_url is None
        assert config.default_model is None

    def test_provider_config_custom_values(self) -> None:
        """Test ProviderConfig with custom values."""
        config = ProviderConfig(
            enabled=False,
            base_url="http://localhost:11434",
            default_model="llama3",
        )
        assert config.enabled is False
        assert config.base_url == "http://localhost:11434"
        assert config.default_model == "llama3"


class TestConfig:
    """Tests for Config."""

    def test_config_aggregates_subsettings(self) -> None:
        """Test that Config contains GeneralSettings, ContextSettings, and ServerSettings."""
        config = Config()
        assert isinstance(config.general, GeneralSettings)
        assert isinstance(config.context, ContextSettings)
        assert isinstance(config.server, ServerSettings)

    def test_config_providers_empty_by_default(self) -> None:
        """Test that providers dict is empty by default."""
        config = Config()
        assert config.providers == {}

    def test_config_with_providers(self) -> None:
        """Test Config with provider configurations."""
        config = Config(
            providers={
                "anthropic": ProviderConfig(),
                "ollama": ProviderConfig(
                    base_url="http://localhost:11434",
                    default_model="llama3",
                ),
            }
        )
        assert "anthropic" in config.providers
        assert "ollama" in config.providers
        assert config.providers["ollama"].base_url == "http://localhost:11434"

    def test_config_general_defaults(self) -> None:
        """Test that Config's general settings use defaults."""
        config = Config()
        assert config.general.default_provider == "anthropic"
        assert config.general.default_model == "claude-sonnet-4-6"

    def test_config_server_defaults(self) -> None:
        config = Config()
        assert config.server.host == "127.0.0.1"
        assert config.server.port == 4096


class TestLoadConfig:
    """Tests for config loader."""

    def test_load_config_file_not_found(self, tmp_path: Path) -> None:
        """Test that missing config file returns default Config."""
        nonexistent = tmp_path / "config.toml"
        config = load_config(nonexistent)
        assert isinstance(config, Config)
        assert config.general.default_provider == "anthropic"

    def test_load_config_empty_file(self, tmp_path: Path) -> None:
        """Test that empty config file returns default Config."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("")
        config = load_config(config_file)
        assert isinstance(config, Config)
        assert config.general.default_provider == "anthropic"

    def test_load_config_valid_toml(self, tmp_path: Path) -> None:
        """Test parsing a valid TOML config file."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("""
[general]
default_provider = "openrouter"
default_model = "gpt-4o"

[context]
max_file_size = 50000
""")
        config = load_config(config_file)
        assert config.general.default_provider == "openrouter"
        assert config.general.default_model == "gpt-4o"
        assert config.context.max_file_size == 50_000

    def test_load_config_partial(self, tmp_path: Path) -> None:
        """Test that missing sections get defaults."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("""
[general]
default_provider = "ollama"
""")
        config = load_config(config_file)
        assert config.general.default_provider == "ollama"
        assert config.general.default_model == "claude-sonnet-4-6"
        assert config.context.max_file_size == 100_000

    def test_load_config_invalid_toml(self, tmp_path: Path) -> None:
        """Test that invalid TOML raises TOMLDecodeError."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("not valid toml [[[")
        with pytest.raises(tomllib.TOMLDecodeError):
            load_config(config_file)

    def test_load_config_with_providers(self, tmp_path: Path) -> None:
        """Test parsing provider configurations."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("""
[providers.ollama]
enabled = true
base_url = "http://localhost:11434"
default_model = "llama3"

[providers.openrouter]
enabled = false
""")
        config = load_config(config_file)
        assert "ollama" in config.providers
        assert config.providers["ollama"].base_url == "http://localhost:11434"
        assert config.providers["ollama"].default_model == "llama3"
        assert "openrouter" in config.providers
        assert config.providers["openrouter"].enabled is False

    def test_load_config_server_section(self, tmp_path: Path) -> None:
        """Test parsing [server] section from TOML."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("""
[server]
host = "0.0.0.0"
port = 8080
db_path = "/data/fin/hub.db"
""")
        config = load_config(config_file)
        assert config.server.host == "0.0.0.0"
        assert config.server.port == 8080
        assert config.server.db_path == "/data/fin/hub.db"

    def test_load_config_server_section_partial(self, tmp_path: Path) -> None:
        """Test that partial [server] section gets defaults for missing fields."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("""
[server]
port = 9000
""")
        config = load_config(config_file)
        assert config.server.port == 9000
        assert config.server.host == "127.0.0.1"
        assert config.server.db_path == "~/.local/share/fin/hub.db"

    def test_load_config_path_default(self, tmp_path: Path) -> None:
        """Test that default path is ~/.config/fin/config.toml."""
        from fin_assist.config import loader

        with patch.object(
            loader, "DEFAULT_CONFIG_PATH", tmp_path / ".config" / "fin" / "config.toml"
        ):
            config = load_config()
            assert isinstance(config, Config)

    def test_load_config_path_override(self, tmp_path: Path) -> None:
        """Test that custom path can be provided."""
        config_file = tmp_path / "custom.toml"
        config_file.write_text("""
[general]
default_provider = "custom"
""")
        config = load_config(config_file)
        assert config.general.default_provider == "custom"
