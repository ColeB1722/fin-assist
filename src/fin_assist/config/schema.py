"""Configuration schema definitions using pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class GeneralSettings(BaseSettings):
    """General application settings."""

    model_config = SettingsConfigDict(env_prefix="FIN_")

    default_provider: str = "anthropic"
    default_model: str = "claude-sonnet-4-6"
    keybinding: str = "ctrl-enter"


class ContextSettings(BaseSettings):
    """Context gathering settings."""

    max_file_size: int = 100_000
    max_history_items: int = 50
    include_git_status: bool = True
    include_env_vars: list[str] = ["PATH", "HOME", "USER", "PWD"]


class ProviderConfig(BaseSettings):
    """Provider-specific configuration (non-secret settings)."""

    enabled: bool = True
    base_url: str | None = None
    default_model: str | None = None


class Config(BaseSettings):
    """Root configuration model."""

    general: GeneralSettings = GeneralSettings()
    context: ContextSettings = ContextSettings()
    providers: dict[str, ProviderConfig] = {}
