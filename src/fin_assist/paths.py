"""Canonical filesystem paths for fin-assist runtime data.

All paths live under ``~/.local/share/fin/`` and are expanded at import time.
Import from here instead of hardcoding paths in individual modules.
"""

from __future__ import annotations

from pathlib import Path

#: Root data directory for all fin-assist runtime state.
DATA_DIR = Path("~/.local/share/fin").expanduser()

#: Directory for saved chat sessions (``<agent>/<slug>.json``).
SESSIONS_DIR = DATA_DIR / "sessions"

#: File for persistent REPL input history.
HISTORY_PATH = DATA_DIR / "history"

#: PID file for the background hub server.
PID_FILE = DATA_DIR / "hub.pid"

#: Credentials file for API keys.
CREDENTIALS_FILE = DATA_DIR / "credentials.json"
