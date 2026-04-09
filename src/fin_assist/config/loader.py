"""Configuration file loader.

Resolves the TOML config file path, then delegates to pydantic-settings
for source layering.  See ``schema.py`` for precedence documentation.
"""

from __future__ import annotations

import os
from pathlib import Path

from fin_assist.config.schema import Config

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "fin" / "config.toml"


def load_config(path: Path | None = None) -> tuple[Config, Path | None]:
    """Load configuration with proper source layering.

    TOML file is resolved from the first available location:
    1. Explicit *path* parameter
    2. ``FIN_CONFIG_PATH`` environment variable
    3. ``./config.toml`` (project-local override in current working directory)
    4. ``~/.config/fin/config.toml`` (user default)

    Within a resolved file, source precedence is:
        init args > env vars (``FIN_*``) > TOML values > schema defaults

    Args:
        path: Explicit path to config file.  Takes precedence over all
              other discovery mechanisms.

    Returns:
        A ``(Config, resolved_path)`` tuple.  *resolved_path* is ``None``
        when no TOML file was found (config comes from env vars + defaults).
    """
    config_path = _resolve_config_path(path)
    config = _build_config(config_path)
    return config, config_path


def _resolve_config_path(path: Path | None) -> Path | None:
    """Walk the TOML discovery chain and return the first existing file.

    Returns ``None`` when no file is found at any location.
    """
    if path is not None:
        return path if path.exists() else None

    if env_path := os.environ.get("FIN_CONFIG_PATH"):
        p = Path(env_path)
        return p if p.exists() else None

    cwd_config = Path.cwd() / "config.toml"
    if cwd_config.exists():
        return cwd_config

    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH

    return None


def _build_config(toml_path: Path | None) -> Config:
    """Construct a ``Config`` with optional TOML source.

    Temporarily sets ``Config.model_config["toml_file"]`` so that the
    ``TomlConfigSettingsSource`` in ``settings_customise_sources`` reads the
    correct file.  Reset afterwards to avoid leaking state across calls.
    """
    try:
        Config.model_config["toml_file"] = toml_path
        return Config()
    finally:
        Config.model_config["toml_file"] = None
