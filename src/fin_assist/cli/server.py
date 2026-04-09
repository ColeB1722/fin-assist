"""Auto-start logic for the agent hub server."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import rich.console

from fin_assist.config.loader import load_config

if TYPE_CHECKING:
    from fin_assist.config.schema import Config

console = rich.console.Console()

PID_FILE = Path("~/.local/share/fin/hub.pid").expanduser()


class ServerStartupError(Exception):
    """Raised when the server fails to start."""


def _read_log_tail(log_path: str, max_lines: int = 20) -> str:
    """Read the last ``max_lines`` lines from the log file.

    Returns an empty string if the file doesn't exist or is empty.
    Used to surface the root cause when the server subprocess crashes
    before becoming healthy.
    """
    try:
        path = Path(log_path)
        if not path.exists():
            return ""
        text = path.read_text().strip()
        if not text:
            return ""
        lines = text.splitlines()
        return "\n".join(lines[-max_lines:])
    except OSError:
        return ""


async def _check_health(base_url: str) -> bool:
    """Return True if the hub server is reachable at base_url."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{base_url}/health")
            return response.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError):
        return False


async def _wait_for_health(
    base_url: str,
    timeout: float = 10.0,
    initial_interval: float = 0.05,
    max_interval: float = 1.0,
) -> None:
    """Poll /health until reachable or timeout.

    Uses ``asyncio.timeout`` for a hard wall-clock deadline — immune to
    scheduling jitter and the time spent inside each ``_check_health`` call.
    """
    interval = initial_interval
    try:
        async with asyncio.timeout(timeout):
            while True:
                await asyncio.sleep(interval)
                if await _check_health(base_url):
                    return
                interval = min(interval * 2, max_interval)
    except TimeoutError:
        raise TimeoutError(f"Server did not become healthy within {timeout}s") from None


def _write_pid(pid: int, pid_file: Path = PID_FILE) -> None:
    """Write the server PID to the PID file."""
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(pid))


def _read_pid(pid_file: Path = PID_FILE) -> int | None:
    """Read the server PID from the PID file. Returns None if missing or invalid."""
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return None


def _remove_pid(pid_file: Path = PID_FILE) -> None:
    """Remove the PID file if it exists."""
    with contextlib.suppress(OSError):
        pid_file.unlink(missing_ok=True)


def _pid_is_running(pid: int) -> bool:
    """Return True if a process with this PID is currently running."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _spawn_serve(
    config: Config,
    pid_file: Path = PID_FILE,
    config_path: Path | None = None,
) -> subprocess.Popen[bytes]:
    """Spawn `fin-assist serve` as a detached background process and write its PID.

    Uses ``subprocess.Popen`` (not ``asyncio.create_subprocess_exec``) so the
    child process is not tracked by any asyncio transport.  When
    ``asyncio.run()`` tears down the event loop it garbage-collects subprocess
    transports and their ``BaseSubprocessTransport.close()`` method kills any
    child that is still running — even with ``start_new_session=True``.
    ``Popen`` has no such lifecycle coupling: the child lives independently
    after ``Popen`` returns.

    Args:
        config: Resolved configuration.
        pid_file: Path to write the server PID.
        config_path: Resolved TOML config path.  When provided, set as
            ``FIN_CONFIG_PATH`` in the child environment so the subprocess
            loads the same file regardless of its working directory.
    """
    db_path = os.path.expanduser(config.server.db_path)
    host = config.server.host
    port = config.server.port
    log_path = os.path.expanduser(config.server.log_path)

    args = [
        sys.executable,
        "-m",
        "fin_assist",
        "serve",
        "--host",
        host,
        "--port",
        str(port),
        "--db",
        db_path,
    ]

    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    if config_path is not None:
        env["FIN_CONFIG_PATH"] = str(config_path.resolve())

    stderr_file = open(log_path, "a", buffering=1)  # noqa: SIM115
    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=stderr_file,
        env=env,
        start_new_session=True,
    )
    stderr_file.close()

    _write_pid(proc.pid, pid_file)
    return proc


def _kill_and_cleanup(
    proc: subprocess.Popen[bytes],
    pid_file: Path,
    graceful_timeout: float = 2.0,
) -> None:
    """Terminate a subprocess and remove its PID file."""
    proc.terminate()
    try:
        proc.wait(timeout=graceful_timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
    _remove_pid(pid_file)


async def ensure_server_running(
    config: Config | None = None,
    config_path: Path | None = None,
    base_url: str | None = None,
    timeout: float = 10.0,
    pid_file: Path = PID_FILE,
) -> str:
    """Ensure the hub server is running.

    Checks if the server is reachable at base_url. If not, spawns
    `fin-assist serve` as a background subprocess and waits for it to
    become healthy.

    Args:
        config: Config object. If None, loads from default location.
        config_path: Resolved TOML config path, forwarded to the child
            process via ``FIN_CONFIG_PATH``.
        base_url: Base URL of the hub. If None, derived from config.
        timeout: Maximum seconds to wait for server to become healthy.
        pid_file: Path to write the server PID file.

    Returns:
        The base_url of the (possibly newly started) server.

    Raises:
        ServerStartupError: If the server cannot be started or doesn't become
            healthy within the timeout.
    """
    if config is None:
        config, config_path = load_config()

    if base_url is None:
        host = config.server.host
        port = config.server.port
        base_url = f"http://{host}:{port}"

    if await _check_health(base_url):
        return base_url

    # Stale PID file check — clean up if the previous process is gone
    existing_pid = _read_pid(pid_file)
    if existing_pid and not _pid_is_running(existing_pid):
        _remove_pid(pid_file)

    console.print(f"[dim]Starting fin-assist hub at {base_url}...[/dim]")

    proc = _spawn_serve(config, pid_file, config_path=config_path)

    try:
        await _wait_for_health(base_url, timeout=timeout)
        console.print("[dim]Hub started.[/dim]")
        return base_url
    except TimeoutError as e:
        _kill_and_cleanup(proc, pid_file)
        log_path = os.path.expanduser(config.server.log_path)
        hint = _read_log_tail(log_path)
        msg = f"Server failed to start within {timeout}s."
        if hint:
            msg += f"\n\nLast log output:\n{hint}"
        else:
            msg += f" Check {log_path} for details."
        raise ServerStartupError(msg) from e


def stop_server(pid_file: Path = PID_FILE, wait_timeout: float = 0) -> bool:
    """Stop the hub server by sending SIGTERM to the recorded PID.

    Args:
        pid_file: Path to the PID file.
        wait_timeout: Seconds to wait for process to exit after SIGTERM.
            Default 0 means don't wait (immediate PID file removal).

    Returns True if the server was stopped, False if no PID file was found
    or the process was not running.
    """
    pid = _read_pid(pid_file)
    if pid is None:
        return False

    if not _pid_is_running(pid):
        _remove_pid(pid_file)
        return False

    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        _remove_pid(pid_file)
        return False

    if wait_timeout > 0:
        import time

        elapsed = 0.0
        interval = 0.05
        while elapsed < wait_timeout:
            time.sleep(interval)
            if not _pid_is_running(pid):
                _remove_pid(pid_file)
                return True
            elapsed += interval
            interval = min(interval * 2, 0.5)

    _remove_pid(pid_file)
    return True
