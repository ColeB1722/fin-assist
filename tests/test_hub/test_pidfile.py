"""Tests for hub/pidfile.py — server-side PID file management."""

from __future__ import annotations

import fcntl
import os
import signal
from pathlib import Path
from unittest.mock import patch

import pytest

from fin_assist.hub import pidfile


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Ensure module globals are clean between tests."""
    pidfile._pid_fd = None
    pidfile._pid_path = None
    yield
    # Clean up after test if acquire was called
    pidfile.release()


class TestAcquire:
    def test_writes_current_pid(self, tmp_path: Path):
        pid_file = tmp_path / "hub.pid"
        pidfile.acquire(pid_file)

        content = pid_file.read_text().strip()
        assert content == str(os.getpid())

    def test_creates_parent_directories(self, tmp_path: Path):
        pid_file = tmp_path / "nested" / "dir" / "hub.pid"
        pidfile.acquire(pid_file)

        assert pid_file.exists()

    def test_holds_exclusive_lock(self, tmp_path: Path):
        pid_file = tmp_path / "hub.pid"
        pidfile.acquire(pid_file)

        # Try to acquire a non-blocking lock from the test process.
        # Since we already hold it, this should fail with OSError.
        fd = os.open(str(pid_file), os.O_RDONLY)
        try:
            with pytest.raises(OSError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)

    def test_sets_module_state(self, tmp_path: Path):
        pid_file = tmp_path / "hub.pid"
        pidfile.acquire(pid_file)

        assert pidfile._pid_fd is not None
        assert pidfile._pid_path == pid_file


class TestRelease:
    def test_removes_pid_file(self, tmp_path: Path):
        pid_file = tmp_path / "hub.pid"
        pidfile.acquire(pid_file)

        pidfile.release()

        assert not pid_file.exists()

    def test_releases_lock(self, tmp_path: Path):
        pid_file = tmp_path / "hub.pid"
        pidfile.acquire(pid_file)

        pidfile.release()

        # After release, we should be able to re-acquire
        pidfile.acquire(pid_file)

    def test_clears_module_state(self, tmp_path: Path):
        pid_file = tmp_path / "hub.pid"
        pidfile.acquire(pid_file)

        pidfile.release()

        assert pidfile._pid_fd is None
        assert pidfile._pid_path is None

    def test_idempotent(self, tmp_path: Path):
        pid_file = tmp_path / "hub.pid"
        pidfile.acquire(pid_file)

        pidfile.release()
        pidfile.release()  # should not raise


class TestIsLocked:
    def test_returns_false_when_no_file(self, tmp_path: Path):
        pid_file = tmp_path / "hub.pid"
        assert pidfile.is_locked(pid_file) is False

    def test_returns_true_when_locked(self, tmp_path: Path):
        pid_file = tmp_path / "hub.pid"
        pidfile.acquire(pid_file)

        assert pidfile.is_locked(pid_file) is True

    def test_returns_false_after_release(self, tmp_path: Path):
        pid_file = tmp_path / "hub.pid"
        pidfile.acquire(pid_file)
        pidfile.release()

        # File was removed by release, so is_locked returns False
        assert pidfile.is_locked(pid_file) is False

    def test_returns_false_for_stale_file(self, tmp_path: Path):
        """A PID file without a lock is stale (e.g. after SIGKILL)."""
        pid_file = tmp_path / "hub.pid"
        pid_file.write_text("99999\n")

        assert pidfile.is_locked(pid_file) is False
