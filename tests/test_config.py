"""Tests for configuration schema and loader."""

import os
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from fin_assist.config import loader
from fin_assist.config.loader import load_config
from fin_assist.config.schema import (
    AgentConfig,
    Config,
    ContextSettings,
    GeneralSettings,
    ProviderConfig,
    ServerSettings,
)


@pytest.fixture(autouse=True)
def _clean_fin_env_vars():
    """Remove FIN_* env vars so pydantic-settings doesn't read devenv values."""
    fin_vars = {k: v for k, v in os.environ.items() if k.startswith("FIN_")}
    for k in fin_vars:
        del os.environ[k]
    yield
    os.environ.update(fin_vars)


class TestGeneralSettings:
    """Tests for GeneralSettings."""

    def test_general_settings_defaults(self) -> None:
        """Test default values for GeneralSettings."""
        settings = GeneralSettings()
        assert settings.default_provider == "anthropic"
        assert settings.default_model == "claude-sonnet-4-6"
        assert settings.thinking_effort == "medium"
        assert settings.keybinding == "ctrl-enter"

    def test_general_settings_custom_values(self) -> None:
        """Test GeneralSettings with explicit values."""
        settings = GeneralSettings(
            default_provider="ollama",
            default_model="llama3",
            thinking_effort="low",
            keybinding="ctrl-space",
        )
        assert settings.default_provider == "ollama"
        assert settings.default_model == "llama3"
        assert settings.thinking_effort == "low"
        assert settings.keybinding == "ctrl-space"


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

    def test_config_reads_general_env_vars(self) -> None:
        """Test that Config reads FIN_GENERAL__ env vars for general settings."""
        with patch.dict(
            os.environ,
            {
                "FIN_GENERAL__DEFAULT_PROVIDER": "openrouter",
                "FIN_GENERAL__DEFAULT_MODEL": "gpt-4o",
                "FIN_GENERAL__KEYBINDING": "ctrl-space",
            },
        ):
            config = Config()
            assert config.general.default_provider == "openrouter"
            assert config.general.default_model == "gpt-4o"
            assert config.general.keybinding == "ctrl-space"

    def test_config_reads_nested_server_env_vars(self) -> None:
        """Test that Config reads FIN_SERVER__ env vars for server settings."""
        with patch.dict(
            os.environ,
            {
                "FIN_SERVER__HOST": "0.0.0.0",
                "FIN_SERVER__PORT": "8080",
                "FIN_SERVER__LOG_PATH": "/var/log/fin.log",
            },
        ):
            config = Config()
            assert config.server.host == "0.0.0.0"
            assert config.server.port == 8080
            assert config.server.log_path == "/var/log/fin.log"

    def test_config_reads_nested_context_env_vars(self) -> None:
        """Test that Config reads FIN_CONTEXT__ env vars for context settings."""
        with patch.dict(
            os.environ,
            {
                "FIN_CONTEXT__MAX_FILE_SIZE": "50000",
                "FIN_CONTEXT__INCLUDE_GIT_STATUS": "false",
            },
        ):
            config = Config()
            assert config.context.max_file_size == 50_000
            assert config.context.include_git_status is False

    def test_config_explicit_values_override_env_vars(self) -> None:
        """Test that explicit values override environment variables."""
        with patch.dict(os.environ, {"FIN_GENERAL__DEFAULT_PROVIDER": "openrouter"}):
            config = Config(general=GeneralSettings(default_provider="ollama"))
            assert config.general.default_provider == "ollama"


class TestLoadConfig:
    """Tests for config loader.

    ``load_config()`` returns a ``(Config, Path | None)`` tuple.
    """

    def test_load_config_file_not_found(self, tmp_path: Path) -> None:
        """Test that missing config file returns default Config."""
        nonexistent = tmp_path / "config.toml"
        config, config_path = load_config(nonexistent)
        assert isinstance(config, Config)
        assert config.general.default_provider == "anthropic"
        assert config_path is None

    def test_load_config_empty_file(self, tmp_path: Path) -> None:
        """Test that empty config file still resolves (pydantic-settings reads it)."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("")
        config, config_path = load_config(config_file)
        assert isinstance(config, Config)
        assert config.general.default_provider == "anthropic"
        assert config_path == config_file

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
        config, _ = load_config(config_file)
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
        config, _ = load_config(config_file)
        assert config.general.default_provider == "ollama"
        assert config.general.default_model == "claude-sonnet-4-6"
        assert config.context.max_file_size == 100_000

    def test_load_config_invalid_toml(self, tmp_path: Path) -> None:
        """Test that invalid TOML raises an error."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("not valid toml [[[")
        with pytest.raises((tomllib.TOMLDecodeError, Exception)):
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
        config, _ = load_config(config_file)
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
        config, _ = load_config(config_file)
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
        config, _ = load_config(config_file)
        assert config.server.port == 9000
        assert config.server.host == "127.0.0.1"
        assert config.server.db_path == "~/.local/share/fin/hub.db"

    def test_load_config_path_default(self, tmp_path: Path) -> None:
        """Test that default path is ~/.config/fin/config.toml."""
        with patch.object(
            loader, "DEFAULT_CONFIG_PATH", tmp_path / ".config" / "fin" / "config.toml"
        ):
            config, _ = load_config()
            assert isinstance(config, Config)

    def test_load_config_path_override(self, tmp_path: Path) -> None:
        """Test that custom path can be provided."""
        config_file = tmp_path / "custom.toml"
        config_file.write_text("""
[general]
default_provider = "custom"
""")
        config, config_path = load_config(config_file)
        assert config.general.default_provider == "custom"
        assert config_path == config_file

    def test_load_config_env_path(self, tmp_path: Path) -> None:
        """Test that FIN_CONFIG_PATH environment variable is respected."""
        config_file = tmp_path / "env_config.toml"
        config_file.write_text("""
[general]
default_provider = "env_provider"
""")
        with patch.dict(os.environ, {"FIN_CONFIG_PATH": str(config_file)}):
            config, config_path = load_config()
            assert config.general.default_provider == "env_provider"
            assert config_path == config_file

    def test_load_config_cwd_fallback(self, tmp_path: Path) -> None:
        """Test that ./config.toml in cwd is used when no explicit path or env var."""
        cwd_config = tmp_path / "config.toml"
        cwd_config.write_text("""
[general]
default_provider = "cwd_provider"
""")
        with patch("fin_assist.config.loader.Path.cwd", return_value=tmp_path):
            config, _ = load_config()
            assert config.general.default_provider == "cwd_provider"

    def test_load_config_cwd_missing_falls_to_default(self, tmp_path: Path) -> None:
        """Test that missing cwd config.toml falls through to default path."""
        # tmp_path has no config.toml, so cwd lookup should miss
        with patch("fin_assist.config.loader.Path.cwd", return_value=tmp_path):
            with patch.object(
                loader, "DEFAULT_CONFIG_PATH", tmp_path / ".config" / "fin" / "config.toml"
            ):
                config, config_path = load_config()
                assert isinstance(config, Config)
                assert config_path is None

    def test_load_config_priority(self, tmp_path: Path) -> None:
        """Test config loading priority: explicit path > env var > cwd > default."""
        explicit_path = tmp_path / "explicit.toml"
        explicit_path.write_text("[general]\ndefault_provider = 'explicit'")

        env_path = tmp_path / "env.toml"
        env_path.write_text("[general]\ndefault_provider = 'env'")

        cwd_dir = tmp_path / "project"
        cwd_dir.mkdir()
        cwd_config = cwd_dir / "config.toml"
        cwd_config.write_text("[general]\ndefault_provider = 'cwd'")

        with patch.dict(os.environ, {"FIN_CONFIG_PATH": str(env_path)}):
            with patch("fin_assist.config.loader.Path.cwd", return_value=cwd_dir):
                # Explicit path wins over env var
                config, _ = load_config(explicit_path)
                assert config.general.default_provider == "explicit"

                # Env var wins over cwd when no explicit path
                config, _ = load_config()
                assert config.general.default_provider == "env"

    def test_env_vars_override_toml_values(self, tmp_path: Path) -> None:
        """Test that env vars take precedence over TOML file values."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("""
[general]
default_provider = "from-toml"

[server]
port = 9000
""")
        with patch.dict(
            os.environ,
            {"FIN_GENERAL__DEFAULT_PROVIDER": "from-env"},
        ):
            config, _ = load_config(config_file)
            # Env var wins over TOML
            assert config.general.default_provider == "from-env"
            # TOML value still used for fields without env override
            assert config.server.port == 9000

    def test_returns_config_path_tuple(self, tmp_path: Path) -> None:
        """Test that load_config returns a (Config, Path | None) tuple."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("[general]\ndefault_provider = 'test'")
        result = load_config(config_file)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], Config)
        assert isinstance(result[1], Path)

    def test_returns_none_path_when_no_file(self, tmp_path: Path) -> None:
        """Test that config_path is None when no TOML file is found."""
        nonexistent = tmp_path / "nope.toml"
        _, config_path = load_config(nonexistent)
        assert config_path is None


class TestAgentConfig:
    def test_defaults(self) -> None:
        ac = AgentConfig()
        assert ac.enabled is True
        assert ac.description == ""
        assert ac.system_prompt == "chain-of-thought"
        assert ac.output_type == "text"
        assert ac.thinking == "medium"
        assert ac.serving_modes == ["do", "talk"]
        assert ac.tags == []

    def test_shell_config(self) -> None:
        ac = AgentConfig(
            description="Shell agent",
            system_prompt="shell",
            output_type="command",
            thinking="off",
            serving_modes=["do"],
            tags=["shell", "one-shot"],
        )
        assert ac.serving_modes == ["do"]
        assert ac.output_type == "command"

    def test_config_has_default_agents(self) -> None:
        config = Config()
        assert "default" in config.agents
        assert "shell" in config.agents
        assert config.agents["default"].output_type == "text"
        assert config.agents["shell"].output_type == "command"

    def test_config_agents_from_toml(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            "[agents.default]\n"
            'system_prompt = "chain-of-thought"\n'
            'output_type = "text"\n'
            "\n"
            "[agents.shell]\n"
            'system_prompt = "shell"\n'
            'output_type = "command"\n'
            'serving_modes = ["do"]\n'
        )
        config, _ = load_config(config_file)
        assert config.agents["shell"].serving_modes == ["do"]
