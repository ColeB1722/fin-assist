"""Canonical filesystem paths for fin-assist runtime data.

All paths live under ``DATA_DIR`` and are expanded at import time.
Set ``FIN_DATA_DIR`` to relocate all runtime state — e.g.
``FIN_DATA_DIR=./.fin`` for local dev.

Platform defaults (when ``FIN_DATA_DIR`` is not set):

- Linux / macOS: ``~/.local/share/fin/``
- Windows: ``%LOCALAPPDATA%\\fin`` (e.g. ``C:\\Users\\<user>\\AppData\\Local\\fin``)

Import from here instead of hardcoding paths in individual modules.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        return Path(base) / "fin"
    return Path("~/.local/share/fin").expanduser()


#: Root data directory for all fin-assist runtime state.
#: Override with the ``FIN_DATA_DIR`` environment variable.
DATA_DIR = Path(os.environ.get("FIN_DATA_DIR", str(_default_data_dir())))

#: Directory for saved chat sessions (``<agent>/<slug>.json``).
SESSIONS_DIR = DATA_DIR / "sessions"

#: File for persistent REPL input history.
HISTORY_PATH = DATA_DIR / "history"

#: PID file for the background hub server.
PID_FILE = DATA_DIR / "hub.pid"

#: Credentials file for API keys.
CREDENTIALS_FILE = DATA_DIR / "credentials.json"

#: JSONL trace file path — always used when tracing is enabled.
TRACES_PATH = DATA_DIR / "traces.jsonl"
