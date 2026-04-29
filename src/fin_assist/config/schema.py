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

from fin_assist.paths import DATA_DIR

ThinkingEffort = Literal["off", "low", "medium", "high"] | None

ServingMode = Literal["do", "talk"]


class GeneralSettings(BaseModel):
    """General application settings."""

    default_provider: str = "anthropic"
    default_model: str = "claude-sonnet-4-6"
    default_agent: str | None = None
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


class TracingSettings(BaseModel):
    """OpenTelemetry tracing configuration."""

    enabled: bool = False
    endpoint: str = "http://localhost:4317"
    exporter_protocol: Literal["grpc", "http"] = "grpc"
    project_name: str = "fin-assist"


class ServerSettings(BaseModel):
    """Agent Hub server settings."""

    host: str = "127.0.0.1"
    port: int = 4096
    db_path: str = str(DATA_DIR / "hub.db")
    log_path: str = str(DATA_DIR / "hub.log")


class WorkflowConfig(BaseModel):
    """Per-workflow configuration within an agent.

    Workflows are prompt-steered sub-tasks an agent can perform.  They define
    a description (for discovery), a prompt template name or inline text, an
    entry prompt sent as the initial user message, and optional serving-mode
    overrides.

    This is level 2 of the workflow spectrum (prompt steering).  Future
    extensions (level 3) may add ``tool_scope`` and ``approval_override``
    fields — see the Skills API vision in architecture.md.
    """

    description: str = ""
    prompt_template: str = ""
    entry_prompt: str = ""
    serving_modes: list[ServingMode] | None = None


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
    tags: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    workflows: dict[str, WorkflowConfig] = Field(default_factory=dict)


_DEFAULT_AGENTS: dict[str, AgentConfig] = {}


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
    tracing: TracingSettings = TracingSettings()
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
