"""Configuration schema definitions using pydantic-settings.

Source precedence (highest wins):
    init args > env vars (FIN_*) > TOML file > schema defaults

Env vars use the ``FIN_`` prefix with ``__`` as nested delimiter:
    FIN_GENERAL__DEFAULT_PROVIDER=openrouter
    FIN_SERVER__LOG_PATH=./hub.log
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

ThinkingEffort = Literal["off", "low", "medium", "high"] | None

ServingMode = Literal["do", "talk"]


class GeneralSettings(BaseModel):
    """General application settings."""

    default_provider: str = "anthropic"
    default_model: str = "claude-sonnet-4-6"
    thinking_effort: ThinkingEffort = "medium"
    keybinding: str = "ctrl-enter"


class ContextSettings(BaseModel):
    """Context gathering settings."""

    max_file_size: int = 100_000
    max_history_items: int = 50
    include_git_status: bool = True
    include_env_vars: list[str] = ["PATH", "HOME", "USER", "PWD"]


class ProviderConfig(BaseModel):
    """Provider-specific configuration (non-secret settings)."""

    enabled: bool = True
    base_url: str | None = None
    default_model: str | None = None


class ServerSettings(BaseModel):
    """Agent Hub server settings."""

    host: str = "127.0.0.1"
    port: int = 4096
    db_path: str = "~/.local/share/fin/hub.db"
    log_path: str = "~/.local/share/fin/hub.log"


class AgentConfig(BaseModel):
    """Per-agent configuration.

    Each key in ``Config.agents`` maps to an agent name (e.g. ``default``,
    ``shell``).  The values control that agent's behavior at the hub level.
    """

    enabled: bool = True
    description: str = ""
    system_prompt: str = "chain-of-thought"
    output_type: str = "text"
    thinking: ThinkingEffort = "medium"
    serving_modes: list[ServingMode] = Field(default_factory=lambda: ["do", "talk"])
    requires_approval: bool = False
    tags: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)


_DEFAULT_AGENTS: dict[str, AgentConfig] = {
    "default": AgentConfig(
        description=(
            "General-purpose assistant. Helps with questions, "
            "shell commands, brainstorming, and more."
        ),
        system_prompt="chain-of-thought",
        output_type="text",
        thinking="medium",
        serving_modes=["do", "talk"],
        tools=["read_file", "git_diff", "git_log", "shell_history"],
    ),
    "shell": AgentConfig(
        description=(
            "One-shot shell command generator. Give it a natural-language "
            "request and get back a ready-to-run command."
        ),
        system_prompt="shell",
        output_type="command",
        thinking="off",
        serving_modes=["do"],
        requires_approval=True,
        tags=["shell", "one-shot"],
    ),
}


class Config(BaseSettings):
    """Root configuration model.

    Uses pydantic-settings to layer multiple sources.  The TOML file path
    is set dynamically by ``load_config()`` via the ``_toml_file`` init
    kwarg — callers should not set ``toml_file`` in ``model_config``
    directly.
    """

    model_config = SettingsConfigDict(
        env_prefix="FIN_",
        env_nested_delimiter="__",
        toml_file=None,
    )

    general: GeneralSettings = GeneralSettings()
    context: ContextSettings = ContextSettings()
    server: ServerSettings = ServerSettings()
    providers: dict[str, ProviderConfig] = {}
    agents: dict[str, AgentConfig] = Field(default_factory=lambda: _DEFAULT_AGENTS)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Define source precedence: init > env > TOML > defaults."""
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls),
        )
