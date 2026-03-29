"""Configuration file loader."""

import tomllib
from pathlib import Path

from fin_assist.config.schema import (
    Config,
    ContextSettings,
    GeneralSettings,
    ProviderConfig,
    ServerSettings,
)

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "fin" / "config.toml"


def load_config(path: Path | None = None) -> Config:
    """Load configuration from a TOML file.

    Args:
        path: Path to config file. Defaults to ~/.config/fin/config.toml.

    Returns:
        Config object with loaded settings or defaults if file missing/empty.
    """
    config_path = path or DEFAULT_CONFIG_PATH

    if not config_path.exists():
        return Config()

    content = config_path.read_text()
    if not content.strip():
        return Config()

    data = tomllib.loads(content)
    return _parse_config(data)


def _parse_config(data: dict) -> Config:
    """Parse TOML data into a Config object."""
    general_data = data.get("general", {})
    context_data = data.get("context", {})
    server_data = data.get("server", {})
    providers_data = data.get("providers", {})

    general = GeneralSettings(**general_data)
    context = ContextSettings(**context_data)
    server = ServerSettings(**server_data)

    providers = {
        name: ProviderConfig(**provider_data) for name, provider_data in providers_data.items()
    }

    return Config(general=general, context=context, server=server, providers=providers)
