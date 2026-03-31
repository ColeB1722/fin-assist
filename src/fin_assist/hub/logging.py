"""Logging configuration for the fin-assist hub server.

Call ``configure_logging()`` once at server startup, before ``uvicorn.run()``.
Uvicorn is invoked with ``log_config=None`` so it inherits this configuration
rather than resetting it.

All loggers (``uvicorn.*``, ``fin_assist.*``, root) share a single
``RotatingFileHandler`` pointed at ``~/.local/share/fin/hub.log``.  This means
future ``logging.getLogger(__name__)`` calls anywhere in the hub will
automatically write to the same file without any additional setup.
"""

from __future__ import annotations

import logging
import logging.config
import logging.handlers
from pathlib import Path

LOG_FILE = Path("~/.local/share/fin/hub.log").expanduser()

_DEFAULT_MAX_BYTES = 1_000_000  # 1 MB
_DEFAULT_BACKUP_COUNT = 1  # hub.log + hub.log.1 → max 2 MB on disk


def configure_logging(
    log_file: Path = LOG_FILE,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    backup_count: int = _DEFAULT_BACKUP_COUNT,
) -> None:
    """Configure the root logger with a rotating file handler.

    Args:
        log_file: Path to the log file. Parent directory is created if needed.
        max_bytes: Maximum log file size before rotation (default 1 MB).
        backup_count: Number of backup files to keep (default 1).
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                    "datefmt": "%Y-%m-%dT%H:%M:%S",
                },
            },
            "handlers": {
                "rotating_file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "filename": str(log_file),
                    "maxBytes": max_bytes,
                    "backupCount": backup_count,
                    "formatter": "default",
                    "encoding": "utf-8",
                },
            },
            "root": {
                "level": "INFO",
                "handlers": ["rotating_file"],
            },
        }
    )
