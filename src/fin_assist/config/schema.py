"""Configuration schema definitions using pydantic-settings."""

from typing import Literal

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

ThinkingEffort = Literal["off", "low", "medium", "high"] | None


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


class Config(BaseSettings):
    """Root configuration model."""

    model_config = SettingsConfigDict(
        env_prefix="FIN_",
        env_nested_delimiter="__",
    )

    general: GeneralSettings = GeneralSettings()
    context: ContextSettings = ContextSettings()
    server: ServerSettings = ServerSettings()
    providers: dict[str, ProviderConfig] = {}
