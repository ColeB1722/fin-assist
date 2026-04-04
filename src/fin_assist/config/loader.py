"""Configuration file loader."""

import os
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

    Config is loaded from the first available location:
    1. Explicit path (path parameter)
    2. FIN_CONFIG_PATH environment variable
    3. ./config.toml (project-local override in current working directory)
    4. ~/.config/fin/config.toml (user default)

    Args:
        path: Explicit path to config file. Takes precedence over all other sources.

    Returns:
        Config object with loaded settings or defaults if file missing/empty.
    """
    if path is not None:
        config_path = path
    elif env_path := os.environ.get("FIN_CONFIG_PATH"):
        config_path = Path(env_path)
    else:
        cwd_config = Path.cwd() / "config.toml"
        config_path = cwd_config if cwd_config.exists() else DEFAULT_CONFIG_PATH

    return _load_config_file(config_path)


def _load_config_file(config_path: Path) -> Config:
    """Load and parse a config file."""
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
