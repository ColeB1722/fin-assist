"""Auto-start logic for the agent hub server."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
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
LOG_FILE = Path("~/.local/share/fin/hub.log").expanduser()


class ServerStartupError(Exception):
    """Raised when the server fails to start."""


async def _check_health(base_url: str) -> bool:
    """Return True if the hub server is reachable at base_url."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{base_url}/health")
            return response.status_code == 200
    except httpx.ConnectError:
        return False
    except httpx.TimeoutException:
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


async def _spawn_serve(config: Config, pid_file: Path = PID_FILE) -> asyncio.subprocess.Process:
    """Spawn `fin-assist serve` as a background process and write its PID."""
    db_path = os.path.expanduser(config.server.db_path)
    host = config.server.host
    port = config.server.port

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

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

    _write_pid(proc.pid, pid_file)
    return proc


async def _kill_and_cleanup(
    proc: asyncio.subprocess.Process,
    pid_file: Path,
    graceful_timeout: float = 2.0,
) -> None:
    """Terminate a subprocess and remove its PID file."""
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=graceful_timeout)
    except TimeoutError:
        proc.kill()
    _remove_pid(pid_file)


async def ensure_server_running(
    config: Config | None = None,
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
        config = load_config()

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

    proc = await _spawn_serve(config, pid_file)

    try:
        await _wait_for_health(base_url, timeout=timeout)
        console.print("[dim]Hub started.[/dim]")
        return base_url
    except TimeoutError as e:
        await _kill_and_cleanup(proc, pid_file)
        raise ServerStartupError(
            f"Server failed to start within {timeout}s. Check {LOG_FILE} for details."
        ) from e


def stop_server(pid_file: Path = PID_FILE) -> bool:
    """Stop the hub server by sending SIGTERM to the recorded PID.

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
        _remove_pid(pid_file)
        return True
    except (ProcessLookupError, PermissionError):
        _remove_pid(pid_file)
        return False
