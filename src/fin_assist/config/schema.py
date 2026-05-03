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

TracingProvider = Literal["phoenix", "none"]


class GeneralSettings(BaseModel):
    """General application settings."""

    default_provider: str = "anthropic"
    default_model: str = "claude-sonnet-4-6"
    default_agent: str | None = None
    thinking_effort: ThinkingEffort = "medium"


class ContextSettings(BaseModel):
    """Context gathering settings."""

    max_file_size: int = 100_000
    max_history_items: int = 50
    include_env_vars: list[str] = ["PATH", "HOME", "USER", "PWD"]


class ProviderConfig(BaseModel):
    """Provider-specific configuration (non-secret settings)."""

    enabled: bool = True
    base_url: str | None = None
    default_model: str | None = None


class TracingSettings(BaseModel):
    """OpenTelemetry tracing configuration.

    The non-obvious knobs:

    * ``provider`` — human-readable preset that replaces raw OTel env
      vars for the common case.  ``"phoenix"`` exports to Phoenix at the
      default OTLP/HTTP endpoint (both OTLP and file sinks active).
      Connection failures are handled gracefully: a one-time info log
      on first failure, then silent — spans continue to the JSONL
      file sink regardless.  ``"none"`` is file-only mode (no OTLP
      exporter constructed).  ``None`` (unset) falls back to manual
      mode where ``otlp_enabled`` and explicit endpoint/OTel env vars
      control the decision.  Set via ``FIN_TRACING__PROVIDER=phoenix``.
    * ``otlp_enabled`` — whether to build the OTLP exporter at all.
      Defaults to ``True`` so both sinks are active by default.  Set to
      ``False`` for file-only mode when you don't want TCP connect
      attempts to the endpoint on every batch flush.
      ``provider="none"`` overrides this (always off).
    * ``sampling_ratio`` — ``1.0`` in dev so every trace lands;
      production can dial it down (``0.1`` = 10% sampled) without code
      changes.
    * ``headers`` — injected into the OTLP exporter for auth on hosted
      backends (Logfire ``authorization: Bearer ...``, Honeycomb
      ``x-honeycomb-team: ...``).  Resolution precedence is
      config-headers > ``OTEL_EXPORTER_OTLP_HEADERS`` > empty.
    * ``event_mode`` — pydantic-ai can emit LLM messages either inline
      as span attributes or as OTel log events.  ``"attributes"`` is the
      default for OTLP backends that render them; native-OTel backends
      can flip to ``logs``.
    * ``include_content`` — whether to record full message bodies.  On
      by default; turn off for shared or regulated deployments and the
      bridge will emit only counts/roles.

    When tracing is enabled, a JSONL file sink always writes to
    ``paths.TRACES_PATH`` (``$FIN_DATA_DIR/traces.jsonl``).  This is
    not configurable — toggling is via ``enabled``, not via a separate
    path knob.
    """

    enabled: bool = False
    provider: TracingProvider | None = None
    endpoint: str = "http://localhost:6006/v1/traces"
    exporter_protocol: Literal["grpc", "http"] = "http"
    project_name: str = "fin-assist"
    sampling_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    headers: dict[str, str] = Field(default_factory=dict)
    event_mode: Literal["attributes", "logs"] = "attributes"
    include_content: bool = True
    otlp_enabled: bool = True


class ServerSettings(BaseModel):
    """Agent Hub server settings."""

    host: str = "127.0.0.1"
    port: int = 4096
    db_path: str = str(DATA_DIR / "hub.db")
    log_path: str = str(DATA_DIR / "hub.log")


class ApprovalRuleConfig(BaseModel):
    """A single fnmatch-based approval rule in config.

    Maps to ``ApprovalRule`` in ``agents/tools.py``.  The ``pattern``
    field is matched against the tool's args string using fnmatch.
    """

    pattern: str
    mode: Literal["never", "always"]
    reason: str | None = None


class ApprovalConfig(BaseModel):
    """Per-skill approval configuration.

    When present on a ``SkillConfig``, overrides the tool's default
    ``ApprovalPolicy`` for tools within that skill.  ``default`` sets the
    fallback mode when no rule matches; ``rules`` are checked in order
    with first-match semantics.
    """

    default: Literal["never", "always"] = "always"
    rules: list[ApprovalRuleConfig] = []


class SkillConfig(BaseModel):
    """Per-skill configuration within an agent.

    A skill is a named collection of tools, approval rules, context
    injection text, and prompt steering.  Skills are loaded additively
    — once loaded, a skill's tools stay active for the session.

    Skills can be defined inline in ``config.toml`` or as SKILL.md files
    in ``.fin/skills/<name>/SKILL.md`` or
    ``~/.config/fin/skills/<name>/SKILL.md``.  SKILL.md takes precedence
    for same-name skills.
    """

    description: str = ""
    tools: list[str] = []
    approval: ApprovalConfig | None = None
    prompt_template: str = ""
    entry_prompt: str = ""
    context: str = ""
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
    skills: dict[str, SkillConfig] = Field(default_factory=dict)


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
