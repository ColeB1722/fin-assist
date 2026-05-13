"""Tests for hub/pidfile.py — server-side PID file management."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from filelock import FileLock, Timeout

from fin_assist.hub import pidfile


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Ensure module globals are clean between tests."""
    pidfile._lock = None
    pidfile._pid_path = None
    yield
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

        probe = FileLock(str(pid_file), timeout=0)
        with pytest.raises(Timeout):
            probe.acquire()
        probe.release()

    def test_sets_module_state(self, tmp_path: Path):
        pid_file = tmp_path / "hub.pid"
        pidfile.acquire(pid_file)

        assert pidfile._lock is not None
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

        pidfile.acquire(pid_file)

    def test_clears_module_state(self, tmp_path: Path):
        pid_file = tmp_path / "hub.pid"
        pidfile.acquire(pid_file)

        pidfile.release()

        assert pidfile._lock is None
        assert pidfile._pid_path is None

    def test_idempotent(self, tmp_path: Path):
        pid_file = tmp_path / "hub.pid"
        pidfile.acquire(pid_file)

        pidfile.release()
        pidfile.release()


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

        assert pidfile.is_locked(pid_file) is False

    def test_returns_false_for_stale_file(self, tmp_path: Path):
        pid_file = tmp_path / "hub.pid"
        pid_file.write_text("0\n")

        assert pidfile.is_locked(pid_file) is False
