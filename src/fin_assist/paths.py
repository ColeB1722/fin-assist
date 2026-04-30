"""Canonical filesystem paths for fin-assist runtime data.

All paths live under ``DATA_DIR`` (default ``~/.local/share/fin/``) and are
expanded at import time.  Set ``FIN_DATA_DIR`` to relocate all runtime state
to a different directory — e.g. ``FIN_DATA_DIR=./.fin`` for local dev.
Import from here instead of hardcoding paths in individual modules.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Root data directory for all fin-assist runtime state.
#: Override with the ``FIN_DATA_DIR`` environment variable.
DATA_DIR = Path(os.environ.get("FIN_DATA_DIR", "~/.local/share/fin")).expanduser()

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
