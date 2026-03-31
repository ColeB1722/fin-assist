"""Tests for cli/server.py — auto-start hub server logic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from fin_assist.cli.server import (
    ServerStartupError,
    _check_health,
    _pid_is_running,
    _read_pid,
    _remove_pid,
    _wait_for_health,
    _write_pid,
    ensure_server_running,
    stop_server,
    LOG_FILE,
)


# ---------------------------------------------------------------------------
# _check_health
# ---------------------------------------------------------------------------


class TestCheckHealth:
    async def test_returns_true_when_server_healthy(self):
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("fin_assist.cli.server.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await _check_health("http://127.0.0.1:4096")

        assert result is True

    async def test_returns_false_when_server_unhealthy(self):
        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("fin_assist.cli.server.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await _check_health("http://127.0.0.1:4096")

        assert result is False

    async def test_returns_false_on_connect_error(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("fin_assist.cli.server.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await _check_health("http://127.0.0.1:4096")

        assert result is False

    async def test_returns_false_on_timeout(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with patch("fin_assist.cli.server.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await _check_health("http://127.0.0.1:4096")

        assert result is False

    async def test_uses_correct_health_endpoint(self):
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("fin_assist.cli.server.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await _check_health("http://127.0.0.1:4096")

        mock_client.get.assert_called_once_with("http://127.0.0.1:4096/health")


# ---------------------------------------------------------------------------
# _wait_for_health
# ---------------------------------------------------------------------------


class TestWaitForHealth:
    async def test_returns_immediately_when_healthy_on_first_check(self):
        with patch("fin_assist.cli.server._check_health", return_value=True) as mock_check:
            await _wait_for_health(
                "http://127.0.0.1:4096",
                timeout=1.0,
                initial_interval=0.001,
            )

        mock_check.assert_called()

    async def test_raises_timeout_error_when_server_never_starts(self):
        with patch("fin_assist.cli.server._check_health", return_value=False):
            with pytest.raises(TimeoutError):
                await _wait_for_health(
                    "http://127.0.0.1:4096",
                    timeout=0.01,
                    initial_interval=0.001,
                    max_interval=0.001,
                )

    async def test_returns_when_server_eventually_starts(self):
        call_count = 0

        async def check_after_3(url: str) -> bool:
            nonlocal call_count
            call_count += 1
            return call_count >= 3

        with patch("fin_assist.cli.server._check_health", side_effect=check_after_3):
            await _wait_for_health(
                "http://127.0.0.1:4096",
                timeout=1.0,
                initial_interval=0.001,
                max_interval=0.001,
            )

        assert call_count >= 3


# ---------------------------------------------------------------------------
# PID file helpers
# ---------------------------------------------------------------------------


class TestPidHelpers:
    def test_write_and_read_pid(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        _write_pid(12345, pid_file)
        assert _read_pid(pid_file) == 12345

    def test_read_pid_returns_none_when_missing(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        assert _read_pid(pid_file) is None

    def test_read_pid_returns_none_on_invalid_content(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        pid_file.write_text("not-a-number")
        assert _read_pid(pid_file) is None

    def test_remove_pid_deletes_file(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        pid_file.write_text("99")
        _remove_pid(pid_file)
        assert not pid_file.exists()

    def test_remove_pid_is_idempotent_when_missing(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        _remove_pid(pid_file)  # should not raise

    def test_pid_is_running_true_for_current_process(self):
        import os

        assert _pid_is_running(os.getpid()) is True

    def test_pid_is_running_false_for_nonexistent_pid(self):
        # PID 0 is always invalid for kill(); PID max is unreachable in practice
        assert _pid_is_running(99999999) is False

    def test_write_pid_creates_parent_dirs(self, tmp_path):
        pid_file = tmp_path / "nested" / "dir" / "hub.pid"
        _write_pid(42, pid_file)
        assert pid_file.exists()
        assert _read_pid(pid_file) == 42


# ---------------------------------------------------------------------------
# stop_server
# ---------------------------------------------------------------------------


class TestStopServer:
    def test_returns_false_when_no_pid_file(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        assert stop_server(pid_file) is False

    def test_returns_false_when_process_not_running(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        _write_pid(99999999, pid_file)
        result = stop_server(pid_file)
        assert result is False
        assert not pid_file.exists()

    def test_removes_pid_file_after_stop(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        import os

        _write_pid(os.getpid(), pid_file)

        with patch("fin_assist.cli.server.os.kill"):
            stop_server(pid_file)

        assert not pid_file.exists()

    def test_sends_sigterm_to_process(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        import os
        import signal

        target_pid = os.getpid()
        _write_pid(target_pid, pid_file)

        sigterm_calls: list[tuple[int, int]] = []
        real_kill = os.kill

        def selective_kill(pid: int, sig: int) -> None:
            if sig == signal.SIGTERM:
                sigterm_calls.append((pid, sig))
            else:
                real_kill(pid, sig)

        with patch("fin_assist.cli.server.os.kill", side_effect=selective_kill):
            stop_server(pid_file)

        assert sigterm_calls == [(target_pid, signal.SIGTERM)]

    def test_returns_true_on_successful_stop(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        import os

        _write_pid(os.getpid(), pid_file)

        with patch("fin_assist.cli.server.os.kill"):
            result = stop_server(pid_file)

        assert result is True


# ---------------------------------------------------------------------------
# ensure_server_running
# ---------------------------------------------------------------------------


class TestEnsureServerRunning:
    async def test_returns_base_url_when_already_healthy(self):
        with patch("fin_assist.cli.server._check_health", return_value=True):
            config = MagicMock()
            config.server.host = "127.0.0.1"
            config.server.port = 4096
            result = await ensure_server_running(config)

        assert result == "http://127.0.0.1:4096"

    async def test_uses_explicit_base_url_when_provided(self):
        with patch("fin_assist.cli.server._check_health", return_value=True):
            config = MagicMock()
            result = await ensure_server_running(config, base_url="http://127.0.0.1:9999")

        assert result == "http://127.0.0.1:9999"

    async def test_spawns_server_when_not_running(self):
        mock_proc = MagicMock()
        mock_proc.terminate = MagicMock()

        with (
            patch("fin_assist.cli.server._check_health", return_value=False),
            patch("fin_assist.cli.server._read_pid", return_value=None),
            patch(
                "fin_assist.cli.server._spawn_serve", new_callable=AsyncMock, return_value=mock_proc
            ) as mock_spawn,
            patch("fin_assist.cli.server._wait_for_health", new_callable=AsyncMock),
        ):
            config = MagicMock()
            config.server.host = "127.0.0.1"
            config.server.port = 4096
            result = await ensure_server_running(config)

        mock_spawn.assert_called_once()
        assert result == "http://127.0.0.1:4096"

    async def test_cleans_up_stale_pid_before_spawn(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        _write_pid(99999999, pid_file)  # stale — process not running

        mock_proc = MagicMock()
        mock_proc.terminate = MagicMock()

        with (
            patch("fin_assist.cli.server._check_health", return_value=False),
            patch(
                "fin_assist.cli.server._spawn_serve", new_callable=AsyncMock, return_value=mock_proc
            ),
            patch("fin_assist.cli.server._wait_for_health", new_callable=AsyncMock),
        ):
            config = MagicMock()
            config.server.host = "127.0.0.1"
            config.server.port = 4096
            await ensure_server_running(config, pid_file=pid_file)

        assert not pid_file.exists()

    async def test_raises_server_startup_error_on_timeout(self):
        mock_proc = MagicMock()
        mock_proc.terminate = MagicMock()
        mock_proc.wait = AsyncMock()
        mock_proc.kill = MagicMock()

        with (
            patch("fin_assist.cli.server._check_health", return_value=False),
            patch("fin_assist.cli.server._read_pid", return_value=None),
            patch(
                "fin_assist.cli.server._spawn_serve", new_callable=AsyncMock, return_value=mock_proc
            ),
            patch(
                "fin_assist.cli.server._wait_for_health",
                new_callable=AsyncMock,
                side_effect=TimeoutError("timeout"),
            ),
        ):
            config = MagicMock()
            config.server.host = "127.0.0.1"
            config.server.port = 4096

            with pytest.raises(ServerStartupError):
                await ensure_server_running(config)

    async def test_startup_error_message_references_log_file(self):
        mock_proc = MagicMock()
        mock_proc.terminate = MagicMock()
        mock_proc.wait = AsyncMock()
        mock_proc.kill = MagicMock()

        with (
            patch("fin_assist.cli.server._check_health", return_value=False),
            patch("fin_assist.cli.server._read_pid", return_value=None),
            patch(
                "fin_assist.cli.server._spawn_serve", new_callable=AsyncMock, return_value=mock_proc
            ),
            patch(
                "fin_assist.cli.server._wait_for_health",
                new_callable=AsyncMock,
                side_effect=TimeoutError("timeout"),
            ),
        ):
            config = MagicMock()
            config.server.host = "127.0.0.1"
            config.server.port = 4096

            with pytest.raises(ServerStartupError, match=str(LOG_FILE)):
                await ensure_server_running(config)

    async def test_removes_pid_file_on_startup_failure(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        mock_proc = MagicMock()
        mock_proc.terminate = MagicMock()
        mock_proc.wait = AsyncMock()
        mock_proc.kill = MagicMock()

        with (
            patch("fin_assist.cli.server._check_health", return_value=False),
            patch("fin_assist.cli.server._read_pid", return_value=None),
            patch(
                "fin_assist.cli.server._spawn_serve", new_callable=AsyncMock, return_value=mock_proc
            ),
            patch(
                "fin_assist.cli.server._wait_for_health",
                new_callable=AsyncMock,
                side_effect=TimeoutError("timeout"),
            ),
        ):
            config = MagicMock()
            config.server.host = "127.0.0.1"
            config.server.port = 4096

            with pytest.raises(ServerStartupError):
                await ensure_server_running(config, pid_file=pid_file)

        assert not pid_file.exists()

    async def test_derives_base_url_from_config(self):
        with patch("fin_assist.cli.server._check_health", return_value=True):
            config = MagicMock()
            config.server.host = "localhost"
            config.server.port = 8080
            result = await ensure_server_running(config)

        assert result == "http://localhost:8080"
