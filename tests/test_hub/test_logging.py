"""Tests for hub/logging.py — configure_logging() helper."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

import pytest

from fin_assist.hub.logging import (
    LOG_FILE,
    _DEFAULT_BACKUP_COUNT,
    _DEFAULT_MAX_BYTES,
    configure_logging,
)


@pytest.fixture(autouse=True)
def reset_root_logger():
    """Remove handlers added by configure_logging() after each test."""
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    yield
    root.handlers = original_handlers
    root.level = original_level


class TestConfigureLogging:
    def test_installs_rotating_file_handler(self, tmp_path):
        log_file = tmp_path / "hub.log"
        configure_logging(log_file=log_file)

        root = logging.getLogger()
        handler_types = [type(h) for h in root.handlers]
        assert logging.handlers.RotatingFileHandler in handler_types

    def test_handler_points_at_correct_file(self, tmp_path):
        log_file = tmp_path / "hub.log"
        configure_logging(log_file=log_file)

        root = logging.getLogger()
        rfh = next(h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler))
        assert Path(rfh.baseFilename) == log_file

    def test_handler_uses_correct_rotation_params(self, tmp_path):
        log_file = tmp_path / "hub.log"
        configure_logging(log_file=log_file, max_bytes=500_000, backup_count=2)

        root = logging.getLogger()
        rfh = next(h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler))
        assert rfh.maxBytes == 500_000
        assert rfh.backupCount == 2

    def test_default_rotation_params(self, tmp_path):
        log_file = tmp_path / "hub.log"
        configure_logging(log_file=log_file)

        root = logging.getLogger()
        rfh = next(h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler))
        assert rfh.maxBytes == _DEFAULT_MAX_BYTES
        assert rfh.backupCount == _DEFAULT_BACKUP_COUNT

    def test_root_logger_level_is_info(self, tmp_path):
        log_file = tmp_path / "hub.log"
        configure_logging(log_file=log_file)

        assert logging.getLogger().level == logging.INFO

    def test_does_not_disable_existing_loggers(self, tmp_path):
        log_file = tmp_path / "hub.log"
        existing = logging.getLogger("fin_assist.test_existing")
        existing.setLevel(logging.DEBUG)

        configure_logging(log_file=log_file)

        # Logger should still exist and not be disabled
        assert not existing.disabled

    def test_creates_parent_directory(self, tmp_path):
        log_file = tmp_path / "nested" / "dir" / "hub.log"
        configure_logging(log_file=log_file)

        assert log_file.parent.exists()

    def test_calling_twice_does_not_duplicate_handlers(self, tmp_path):
        log_file = tmp_path / "hub.log"
        configure_logging(log_file=log_file)
        configure_logging(log_file=log_file)

        root = logging.getLogger()
        rfh_count = sum(
            1 for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
        )
        assert rfh_count == 1

    def test_default_log_file_constant(self):
        assert LOG_FILE == Path("~/.local/share/fin/hub.log").expanduser()
