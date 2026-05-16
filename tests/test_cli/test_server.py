"""Tests for cli/server.py — auto-start hub server logic."""

from __future__ import annotations

import re
import signal
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from fin_assist.cli.server import (
    HubStatus,
    ServerStartupError,
    _check_health,
    _find_server_pid,
    _force_kill,
    _pid_is_running,
    _read_pid,
    _wait_for_health,
    check_status,
    ensure_server_running,
    stop_server,
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
# PID file helpers (client-side)
# ---------------------------------------------------------------------------


class TestPidHelpers:
    def test_read_pid_returns_value(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        pid_file.write_text("12345\n")
        assert _read_pid(pid_file) == 12345

    def test_read_pid_returns_none_when_missing(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        assert _read_pid(pid_file) is None

    def test_read_pid_returns_none_on_invalid_content(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        pid_file.write_text("not-a-number")
        assert _read_pid(pid_file) is None

    def test_pid_is_running_true_for_current_process(self):
        import os

        assert _pid_is_running(os.getpid()) is True

    def test_pid_is_running_false_for_nonexistent_pid(self):
        # PID 0 is always invalid for kill(); PID max is unreachable in practice
        assert _pid_is_running(99999999) is False


# ---------------------------------------------------------------------------
# _find_server_pid
# ---------------------------------------------------------------------------


class TestFindServerPid:
    def test_returns_none_when_no_proc(self):
        with patch("fin_assist.cli.server.Path") as mock_path_cls:
            mock_proc = MagicMock()
            mock_proc.is_dir.return_value = False
            mock_path_cls.return_value = mock_proc
            assert _find_server_pid(4096) is None

    def test_returns_pid_when_matching_process_found(self, tmp_path):
        # Create a fake /proc/<pid>/cmdline
        proc_dir = tmp_path / "42"
        proc_dir.mkdir()
        cmdline = "python3\x00-m\x00fin_assist\x00serve\x00--port\x004096"
        (proc_dir / "cmdline").write_bytes(cmdline.encode())

        with (
            patch("fin_assist.cli.server.Path", return_value=tmp_path),
            patch("fin_assist.cli.server.os.getpid", return_value=999),
        ):
            assert _find_server_pid(4096) == 42

    def test_returns_none_when_no_matching_process(self, tmp_path):
        proc_dir = tmp_path / "42"
        proc_dir.mkdir()
        cmdline = "python3\x00-m\x00some_other_app\x00serve"
        (proc_dir / "cmdline").write_bytes(cmdline.encode())

        with (
            patch("fin_assist.cli.server.Path", return_value=tmp_path),
            patch("fin_assist.cli.server.os.getpid", return_value=999),
        ):
            assert _find_server_pid(4096) is None

    def test_skips_own_pid(self, tmp_path):
        proc_dir = tmp_path / "999"
        proc_dir.mkdir()
        cmdline = "python3\x00-m\x00fin_assist\x00serve\x00--port\x004096"
        (proc_dir / "cmdline").write_bytes(cmdline.encode())

        with (
            patch("fin_assist.cli.server.Path", return_value=tmp_path),
            patch("fin_assist.cli.server.os.getpid", return_value=999),
        ):
            assert _find_server_pid(4096) is None


# ---------------------------------------------------------------------------
# stop_server
# ---------------------------------------------------------------------------


class TestForceKill:
    @pytest.mark.skipif(sys.platform == "win32", reason="Unix-only signal path")
    def test_unix_calls_os_kill_with_sigkill(self):
        with patch("fin_assist.cli.server.os.kill") as mock_kill:
            _force_kill(12345)
        mock_kill.assert_called_once_with(12345, signal.SIGKILL)

    def test_propagates_process_lookup_error(self):
        if sys.platform == "win32":
            # On Windows, a non-existent PID makes OpenProcess return NULL,
            # which our wrapper translates into ProcessLookupError.
            with pytest.raises(ProcessLookupError):
                _force_kill(0xFFFFFFFE)  # very unlikely to exist
        else:
            with patch("fin_assist.cli.server.os.kill", side_effect=ProcessLookupError):
                with pytest.raises(ProcessLookupError):
                    _force_kill(12345)


class TestStopServer:
    def test_returns_false_when_no_pid_file(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        assert stop_server(pid_file) is False

    def test_returns_false_when_process_not_running(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        pid_file.write_text("99999999\n")
        result = stop_server(pid_file)
        assert result is False
        # Stale file should be cleaned up
        assert not pid_file.exists()

    def test_sends_sigterm_to_process(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        import os
        import signal

        target_pid = os.getpid()
        pid_file.write_text(f"{target_pid}\n")

        sigterm_calls: list[tuple[int, int]] = []
        real_kill = os.kill

        def selective_kill(pid: int, sig: int) -> None:
            if sig == signal.SIGTERM:
                sigterm_calls.append((pid, sig))
            else:
                real_kill(pid, sig)

        with (
            patch("fin_assist.cli.server.os.kill", side_effect=selective_kill),
            patch("fin_assist.cli.server._pid_is_running", side_effect=[True, False]),
            patch("fin_assist.cli.server.time.sleep"),
        ):
            stop_server(pid_file, timeout=1.0)

        assert sigterm_calls == [(target_pid, signal.SIGTERM)]

    def test_waits_for_process_to_exit(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        pid_file.write_text("12345\n")

        # Simulate process exiting after 2 checks
        with (
            patch("fin_assist.cli.server.os.kill"),
            patch("fin_assist.cli.server._pid_is_running", side_effect=[True, True, False]),
            patch("fin_assist.cli.server.time.sleep"),
        ):
            result = stop_server(pid_file, timeout=5.0)

        assert result is True

    def test_escalates_to_force_kill_on_timeout(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        pid_file.write_text("12345\n")

        sigterm_calls: list[tuple[int, int]] = []
        force_kill_calls: list[int] = []

        def track_kill(pid: int, sig: int) -> None:
            sigterm_calls.append((pid, sig))

        def track_force_kill(pid: int) -> None:
            force_kill_calls.append(pid)

        # Process never exits from SIGTERM, so we must escalate to _force_kill.
        # We patch _force_kill directly so the test is portable: on Unix it
        # would have called os.kill(SIGKILL); on Windows, TerminateProcess.
        with (
            patch("fin_assist.cli.server.os.kill", side_effect=track_kill),
            patch("fin_assist.cli.server._force_kill", side_effect=track_force_kill),
            patch("fin_assist.cli.server._pid_is_running", return_value=True),
            patch("fin_assist.cli.server.time.sleep"),
        ):
            result = stop_server(pid_file, timeout=0.0)

        assert result is True
        # Initial SIGTERM was sent (Unix-style graceful first attempt) ...
        assert (12345, signal.SIGTERM) in sigterm_calls
        # ... then we escalated to a forceful kill.
        assert 12345 in force_kill_calls

    def test_returns_true_on_successful_stop(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        pid_file.write_text("12345\n")

        with (
            patch("fin_assist.cli.server.os.kill"),
            patch("fin_assist.cli.server._pid_is_running", side_effect=[True, False]),
            patch("fin_assist.cli.server.time.sleep"),
        ):
            result = stop_server(pid_file, timeout=5.0)

        assert result is True

    def test_falls_back_to_find_server_pid_when_no_pid_file(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        # No PID file exists — but _find_server_pid discovers the orphan.
        with (
            patch("fin_assist.cli.server._find_server_pid", return_value=12345),
            patch("fin_assist.cli.server.os.kill"),
            patch("fin_assist.cli.server._pid_is_running", side_effect=[True, False]),
            patch("fin_assist.cli.server.time.sleep"),
        ):
            result = stop_server(pid_file, port=4096)

        assert result is True

    def test_no_fallback_without_port(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        # No PID file and no port — cannot fall back.
        assert stop_server(pid_file) is False


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
            patch("fin_assist.cli.server._spawn_serve", return_value=mock_proc) as mock_spawn,
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
        pid_file.write_text("99999999\n")  # stale — process not running

        mock_proc = MagicMock()
        mock_proc.terminate = MagicMock()

        with (
            patch("fin_assist.cli.server._check_health", return_value=False),
            patch("fin_assist.cli.server._spawn_serve", return_value=mock_proc),
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
        mock_proc.wait = MagicMock()
        mock_proc.kill = MagicMock()

        with (
            patch("fin_assist.cli.server._check_health", return_value=False),
            patch("fin_assist.cli.server._read_pid", return_value=None),
            patch("fin_assist.cli.server._spawn_serve", return_value=mock_proc),
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

    async def test_startup_error_message_references_log_file(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.terminate = MagicMock()
        mock_proc.wait = MagicMock()
        mock_proc.kill = MagicMock()

        log_path = tmp_path / "test.log"

        with (
            patch("fin_assist.cli.server._check_health", return_value=False),
            patch("fin_assist.cli.server._read_pid", return_value=None),
            patch("fin_assist.cli.server._spawn_serve", return_value=mock_proc),
            patch(
                "fin_assist.cli.server._wait_for_health",
                new_callable=AsyncMock,
                side_effect=TimeoutError("timeout"),
            ),
        ):
            config = MagicMock()
            config.server.host = "127.0.0.1"
            config.server.port = 4096
            config.server.log_path = str(log_path)

            with pytest.raises(ServerStartupError, match=re.escape(str(log_path))):
                await ensure_server_running(config)

    async def test_removes_pid_file_on_startup_failure(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        mock_proc = MagicMock()
        mock_proc.terminate = MagicMock()
        mock_proc.wait = MagicMock()
        mock_proc.kill = MagicMock()

        with (
            patch("fin_assist.cli.server._check_health", return_value=False),
            patch("fin_assist.cli.server._read_pid", return_value=None),
            patch("fin_assist.cli.server._spawn_serve", return_value=mock_proc),
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

    async def test_wraps_spawn_oserror_as_startup_error(self, tmp_path):
        """Regression: a raw OSError from _spawn_serve (e.g. missing log
        directory) previously escaped unhandled, producing a traceback for
        ``fin start`` and a silent ``return 1`` for ``fin do``.  It must be
        wrapped as ``ServerStartupError`` so ``_hub_client`` can render it.
        """
        pid_file = tmp_path / "hub.pid"

        with (
            patch("fin_assist.cli.server._check_health", return_value=False),
            patch("fin_assist.cli.server._read_pid", return_value=None),
            patch(
                "fin_assist.cli.server._spawn_serve",
                side_effect=FileNotFoundError(2, "No such file or directory"),
            ),
        ):
            config = MagicMock()
            config.server.host = "127.0.0.1"
            config.server.port = 4096

            with pytest.raises(ServerStartupError, match="Failed to spawn"):
                await ensure_server_running(config, pid_file=pid_file)


# ---------------------------------------------------------------------------
# _spawn_serve
# ---------------------------------------------------------------------------


class TestSpawnServe:
    def test_creates_log_parent_directory_if_missing(self, tmp_path):
        """Regression: ``_spawn_serve`` used to raise ``FileNotFoundError``
        when ``log_path``'s parent directory didn't exist (fresh checkout or
        after ``rm -rf $FIN_DATA_DIR``).  It must create the directory first.
        """
        from fin_assist.cli.server import _spawn_serve

        # A nested log path whose parents don't exist yet.
        log_path = tmp_path / "nested" / "dirs" / "hub.log"
        assert not log_path.parent.exists()

        config = MagicMock()
        config.server.host = "127.0.0.1"
        config.server.port = 4096
        config.server.db_path = str(tmp_path / "hub.db")
        config.server.log_path = str(log_path)

        pid_file = tmp_path / "hub.pid"

        mock_proc = MagicMock()
        with patch("fin_assist.cli.server.subprocess.Popen", return_value=mock_proc):
            _spawn_serve(config, pid_file=pid_file)

        assert log_path.parent.is_dir()

    @pytest.mark.skipif(sys.platform == "win32", reason="Tests Unix branch of _spawn_serve")
    def test_unix_uses_start_new_session(self, tmp_path):
        """On Unix the child must be spawned with ``start_new_session=True``
        so it survives terminal closure.  No Windows-specific flags should
        leak through (``creationflags``/``startupinfo``)."""
        import subprocess as _subprocess

        from fin_assist.cli.server import _spawn_serve

        config = MagicMock()
        config.server.host = "127.0.0.1"
        config.server.port = 4096
        config.server.db_path = str(tmp_path / "hub.db")
        config.server.log_path = str(tmp_path / "hub.log")
        pid_file = tmp_path / "hub.pid"

        mock_proc = MagicMock()
        with patch("fin_assist.cli.server.subprocess.Popen", return_value=mock_proc) as mock_popen:
            _spawn_serve(config, pid_file=pid_file)

        kwargs = mock_popen.call_args.kwargs
        assert kwargs.get("start_new_session") is True
        # creationflags either absent or 0 on Unix; never a Windows constant.
        assert kwargs.get("creationflags", 0) == 0
        assert kwargs.get("startupinfo") is None
        # stdin and stdout must be redirected to DEVNULL to truly detach
        # from the controlling terminal.
        assert kwargs.get("stdin") == _subprocess.DEVNULL
        assert kwargs.get("stdout") == _subprocess.DEVNULL

    @pytest.mark.skipif(sys.platform != "win32", reason="Tests Windows branch of _spawn_serve")
    def test_windows_uses_hidden_console_session(self, tmp_path):
        """Regression for corporate-EDR Windows machines.

        We need *exactly* this flag combination:

        * ``creationflags=CREATE_NO_WINDOW`` — allocate a windowless console
          session up front so libraries that probe the console don't trigger
          ``AllocConsole`` and pop a window.
        * ``STARTUPINFO(STARTF_USESHOWWINDOW, SW_HIDE)`` — belt-and-suspenders
          hint that any console window must be hidden.
        * NO ``DETACHED_PROCESS`` — mutually exclusive with
          ``CREATE_NO_WINDOW``; combining them was observed to either pop a
          window (some libraries call ``AllocConsole`` when no console exists)
          or be silently killed by EDR.
        * NO ``CREATE_NEW_PROCESS_GROUP`` — observed to hang or be killed by
          corporate EDR.
        * NO ``pythonw.exe`` swap — uv-managed installs ship a working
          ``python.exe`` but a ``pythonw.exe`` that fails to start.
        """
        # Guard the body under a runtime sys.platform check so the type
        # checker narrows ``subprocess`` to the Win32 stub (which exposes
        # STARTUPINFO, CREATE_NO_WINDOW, etc.).  The skipif decorator alone
        # doesn't narrow the platform for the type checker.
        if sys.platform != "win32":
            return

        import subprocess as _subprocess

        from fin_assist.cli.server import _spawn_serve

        config = MagicMock()
        config.server.host = "127.0.0.1"
        config.server.port = 4096
        config.server.db_path = str(tmp_path / "hub.db")
        config.server.log_path = str(tmp_path / "hub.log")
        pid_file = tmp_path / "hub.pid"

        mock_proc = MagicMock()
        with patch("fin_assist.cli.server.subprocess.Popen", return_value=mock_proc) as mock_popen:
            _spawn_serve(config, pid_file=pid_file)

        kwargs = mock_popen.call_args.kwargs

        # Exact creationflags: CREATE_NO_WINDOW and nothing else.
        flags = kwargs.get("creationflags", 0)
        assert flags & _subprocess.CREATE_NO_WINDOW, (
            "CREATE_NO_WINDOW must be set so the child gets a windowless console"
        )
        assert not (flags & _subprocess.DETACHED_PROCESS), (
            "DETACHED_PROCESS must NOT be combined with CREATE_NO_WINDOW"
        )
        assert not (flags & _subprocess.CREATE_NEW_PROCESS_GROUP), (
            "CREATE_NEW_PROCESS_GROUP triggers EDR on corporate Windows"
        )

        # STARTUPINFO must request hidden window.
        startupinfo = kwargs.get("startupinfo")
        assert startupinfo is not None, "STARTUPINFO required to hide the console window"
        assert startupinfo.dwFlags & _subprocess.STARTF_USESHOWWINDOW
        assert startupinfo.wShowWindow == _subprocess.SW_HIDE

        # Sanity: stdin/stdout/stderr properly redirected.
        assert kwargs.get("stdin") == _subprocess.DEVNULL
        assert kwargs.get("stdout") == _subprocess.DEVNULL
        # stderr is the open log file handle, not DEVNULL.
        assert kwargs.get("stderr") is not None

        # Sanity: executable must be ``python.exe``, not ``pythonw.exe``.
        # The first arg to Popen is the argv list; args[0] is the interpreter.
        argv = mock_popen.call_args.args[0]
        assert not argv[0].endswith("pythonw.exe"), (
            "pythonw.exe was observed to fail on uv-managed corporate installs"
        )


# ---------------------------------------------------------------------------
# check_status
# ---------------------------------------------------------------------------


class TestCheckStatus:
    async def test_healthy_server_with_pid_file(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        pid_file.write_text("12345\n")

        config = MagicMock()
        config.server.host = "127.0.0.1"
        config.server.port = 4096

        with (
            patch("fin_assist.cli.server._check_health", return_value=True),
            patch("fin_assist.cli.server._pid_is_running", return_value=True),
        ):
            status = await check_status(config, pid_file=pid_file)

        assert status.healthy is True
        assert status.pid == 12345
        assert status.pid_file_exists is True
        assert status.base_url == "http://127.0.0.1:4096"

    async def test_healthy_server_without_pid_file(self, tmp_path):
        pid_file = tmp_path / "hub.pid"

        config = MagicMock()
        config.server.host = "127.0.0.1"
        config.server.port = 4096

        with (
            patch("fin_assist.cli.server._check_health", return_value=True),
            patch("fin_assist.cli.server._find_server_pid", return_value=99999),
            patch("fin_assist.cli.server._pid_is_running", return_value=True),
        ):
            status = await check_status(config, pid_file=pid_file)

        assert status.healthy is True
        assert status.pid == 99999
        assert status.pid_file_exists is False

    async def test_not_running(self, tmp_path):
        pid_file = tmp_path / "hub.pid"

        config = MagicMock()
        config.server.host = "127.0.0.1"
        config.server.port = 4096

        with patch("fin_assist.cli.server._check_health", return_value=False):
            status = await check_status(config, pid_file=pid_file)

        assert status.healthy is False
        assert status.pid is None
        assert status.pid_file_exists is False

    async def test_stale_pid_cleared(self, tmp_path):
        pid_file = tmp_path / "hub.pid"
        pid_file.write_text("12345\n")

        config = MagicMock()
        config.server.host = "127.0.0.1"
        config.server.port = 4096

        with (
            patch("fin_assist.cli.server._check_health", return_value=False),
            patch("fin_assist.cli.server._pid_is_running", return_value=False),
        ):
            status = await check_status(config, pid_file=pid_file)

        assert status.healthy is False
        assert status.pid is None
        assert status.pid_file_exists is True  # file existed when read
