"""Auto-start logic for the agent hub server."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import rich.console

from fin_assist.config.loader import load_config
from fin_assist.paths import PID_FILE

if TYPE_CHECKING:
    from fin_assist.config.schema import Config

console = rich.console.Console()

# Default timeout (seconds) to wait for the server to exit after SIGTERM.
_STOP_TIMEOUT: float = 10.0


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


# ---------------------------------------------------------------------------
# PID file helpers (client-side — reading only)
# ---------------------------------------------------------------------------


def _read_pid(pid_file: Path = PID_FILE) -> int | None:
    """Read the server PID from the PID file. Returns None if missing or invalid."""
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return None


def _pid_is_running(pid: int) -> bool:
    """Return True if a process with this PID is currently running.

    On Unix, uses ``os.kill(pid, 0)`` (signal 0 = existence check).
    On Windows, ``os.kill`` with signal 0 is not supported, so we
    use ``psutil``-style ``OpenProcess`` via ``ctypes``.
    """
    if sys.platform == "win32":
        return _pid_is_running_win32(pid)
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _pid_is_running_win32(pid: int) -> bool:
    """Windows-specific PID liveness check using ``OpenProcess``."""
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32  # ty: ignore[unresolved-attribute]  # pyright: ignore[reportAttributeAccessIssue]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        kernel32.CloseHandle(handle)
        return True
    return False


def _force_kill(pid: int) -> None:
    """Forcefully terminate a process — the OS-level "kill -9" equivalent.

    On Unix, sends ``SIGKILL``.  On Windows, opens the process with
    ``PROCESS_TERMINATE`` and calls ``TerminateProcess``.  Either way,
    the target process gets no chance to clean up.

    Raises ``ProcessLookupError`` if the PID is gone or ``PermissionError``
    if the caller can't signal it.
    """
    if sys.platform == "win32":
        _force_kill_win32(pid)
        return
    os.kill(pid, signal.SIGKILL)


def _force_kill_win32(pid: int) -> None:
    """Windows-specific forceful termination using ``TerminateProcess``."""
    import ctypes

    PROCESS_TERMINATE = 0x0001
    kernel32 = ctypes.windll.kernel32  # ty: ignore[unresolved-attribute]  # pyright: ignore[reportAttributeAccessIssue]
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        # Process is gone or we don't have permission.  Match the Unix
        # contract: ESRCH-like → ProcessLookupError.
        raise ProcessLookupError(f"No such process: {pid}")
    try:
        if not kernel32.TerminateProcess(handle, 1):
            raise PermissionError(f"TerminateProcess failed for pid {pid}")
    finally:
        kernel32.CloseHandle(handle)


def _cleanup_pid_files(pid_file: Path) -> None:
    """Remove both the PID file and its sidecar ``.lock`` file.

    The server normally removes both via its own ``atexit`` handler,
    but this is a defensive cleanup for crash/SIGKILL recovery and the
    failed-startup path.
    """
    pid_file.unlink(missing_ok=True)
    pid_file.with_name(pid_file.name + ".lock").unlink(missing_ok=True)


def _find_server_pid(port: int) -> int | None:
    """Find a running ``fin-assist serve`` process listening on *port*.

    Scans ``/proc`` for a process whose command line matches the expected
    pattern.  Used as a fallback when the PID file is missing but the
    server is still running (orphaned server).

    Returns the PID if found, None otherwise.
    """
    target = "fin_assist serve"
    port_arg = f"--port {port}"
    my_pid = os.getpid()

    proc_path = Path("/proc")
    if not proc_path.is_dir():
        return None

    for entry in proc_path.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == my_pid:
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().decode().replace("\x00", " ")
        except (OSError, PermissionError):
            continue
        if target in cmdline and port_arg in cmdline:
            return pid

    return None


# ---------------------------------------------------------------------------
# Spawn
# ---------------------------------------------------------------------------


def _spawn_serve(
    config: Config,
    pid_file: Path = PID_FILE,
    config_path: Path | None = None,
) -> subprocess.Popen[bytes]:
    """Spawn ``fin-assist serve`` as a detached background process.

    The server process itself writes and locks the PID file (via
    ``hub/pidfile.py``).  This function only passes the path.

    Uses ``subprocess.Popen`` (not ``asyncio.create_subprocess_exec``) so the
    child process is not tracked by any asyncio transport.  When
    ``asyncio.run()`` tears down the event loop it garbage-collects subprocess
    transports and their ``BaseSubprocessTransport.close()`` method kills any
    child that is still running — even with ``start_new_session=True``.
    ``Popen`` has no such lifecycle coupling: the child lives independently
    after ``Popen`` returns.

    Args:
        config: Resolved configuration.
        pid_file: Path the server should write its PID to.
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
        "--pid-file",
        str(pid_file),
    ]

    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    if config_path is not None:
        env["FIN_CONFIG_PATH"] = str(config_path.resolve())

    # Ensure the log's parent directory exists. On a fresh checkout (or after
    # ``rm -rf $FIN_DATA_DIR``) the directory won't exist yet; without this
    # the ``open()`` below raises ``FileNotFoundError``.
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    with open(log_path, "a", buffering=1, encoding="utf-8") as stderr_file:  # noqa: SIM115
        if sys.platform == "win32":
            proc = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
                env=env,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            )
        else:
            proc = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
                env=env,
                start_new_session=True,
            )

    return proc


def _kill_and_cleanup(
    proc: subprocess.Popen[bytes],
    graceful_timeout: float = 2.0,
) -> None:
    """Terminate a subprocess (used on startup failure)."""
    proc.terminate()
    try:
        proc.wait(timeout=graceful_timeout)
    except subprocess.TimeoutExpired:
        proc.kill()


# ---------------------------------------------------------------------------
# ensure_server_running
# ---------------------------------------------------------------------------


async def ensure_server_running(
    config: Config | None = None,
    config_path: Path | None = None,
    base_url: str | None = None,
    timeout: float = 10.0,
    pid_file: Path = PID_FILE,
) -> str:
    """Ensure the hub server is running.

    Checks if the server is reachable at base_url. If not, spawns
    ``fin-assist serve`` as a background subprocess and waits for it to
    become healthy.

    Args:
        config: Config object. If None, loads from default location.
        config_path: Resolved TOML config path, forwarded to the child
            process via ``FIN_CONFIG_PATH``.
        base_url: Base URL of the hub. If None, derived from config.
        timeout: Maximum seconds to wait for server to become healthy.
        pid_file: Path the server should write its PID file to.

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

    # Stale PID file check — clean up if the previous process is gone.
    # With server-owned locking, a stale file means the server crashed
    # (SIGKILL) and left the file behind without the lock.
    existing_pid = _read_pid(pid_file)
    if existing_pid and not _pid_is_running(existing_pid):
        _cleanup_pid_files(pid_file)

    console.print(f"[dim]Starting fin-assist hub at {base_url}...[/dim]")

    try:
        proc = _spawn_serve(config, pid_file, config_path=config_path)
    except OSError as e:
        # Spawning the subprocess failed before the server could run —
        # e.g. the log directory couldn't be created, the executable is
        # missing, or we hit a permission error.  Surface this as a
        # ServerStartupError so ``_hub_client`` renders it instead of
        # leaking a raw traceback.
        raise ServerStartupError(f"Failed to spawn hub process: {e}") from e

    try:
        await _wait_for_health(base_url, timeout=timeout)
        console.print("[dim]Hub started.[/dim]")
        return base_url
    except TimeoutError as e:
        _kill_and_cleanup(proc)
        _cleanup_pid_files(pid_file)
        log_path = os.path.expanduser(config.server.log_path)
        hint = _read_log_tail(log_path)
        msg = f"Server failed to start within {timeout}s."
        if hint:
            msg += f"\n\nLast log output:\n{hint}"
        else:
            msg += f" Check {log_path} for details."
        raise ServerStartupError(msg) from e


# ---------------------------------------------------------------------------
# stop_server
# ---------------------------------------------------------------------------


def stop_server(
    pid_file: Path = PID_FILE,
    timeout: float = _STOP_TIMEOUT,
    port: int | None = None,
) -> bool:
    """Stop the hub server by sending SIGTERM and waiting for exit.

    The server process cleans up its own PID and sidecar lock files via
    ``atexit``.  If it doesn't exit within *timeout* seconds, a forceful
    kill is sent (SIGKILL on Unix, TerminateProcess on Windows).

    When the PID file is missing (orphaned server), falls back to
    scanning ``/proc`` for a ``fin-assist serve`` process on *port*.

    Args:
        pid_file: Path to the PID file.
        timeout: Seconds to wait for the process to exit after SIGTERM.
        port: Server port, used for fallback PID discovery.

    Returns True if the server was stopped, False if no PID file was found
    or the process was not running.
    """
    pid = _read_pid(pid_file)

    if pid is None and port is not None:
        # Fallback: PID file missing but server may still be running.
        pid = _find_server_pid(port)

    if pid is None:
        return False

    if not _pid_is_running(pid):
        # Process is gone but PID file remains (crash / SIGKILL).
        _cleanup_pid_files(pid_file)
        return False

    # Note: on Windows, ``os.kill(pid, signal.SIGTERM)`` calls ``TerminateProcess``
    # — there is no SIGTERM/SIGKILL distinction.  The escalation path below
    # exists for Unix; on Windows the first kill is already forceful.
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        _cleanup_pid_files(pid_file)
        return False

    # Wait for the process to exit.
    elapsed = 0.0
    interval = 0.05
    while elapsed < timeout:
        time.sleep(interval)
        if not _pid_is_running(pid):
            # Server exited cleanly — it removed its own PID file.
            # Clean up just in case (e.g. race with atexit).
            _cleanup_pid_files(pid_file)
            return True
        elapsed += interval
        interval = min(interval * 2, 0.5)

    # Escalate to a forceful kill (SIGKILL on Unix, TerminateProcess on Windows).
    try:
        _force_kill(pid)
    except (ProcessLookupError, PermissionError):
        _cleanup_pid_files(pid_file)
        return True

    # Brief wait for the kill to take effect.
    time.sleep(0.2)
    _cleanup_pid_files(pid_file)
    return True


# ---------------------------------------------------------------------------
# check_status
# ---------------------------------------------------------------------------


@dataclass
class HubStatus:
    """Snapshot of the hub server's state."""

    healthy: bool
    """True if the server responded to a health check."""
    base_url: str
    """The URL that was checked."""
    pid: int | None = None
    """Server PID, if known (from PID file or process scan)."""
    pid_file_exists: bool = False
    """True if the PID file is present on disk."""


async def check_status(
    config: Config | None = None,
    pid_file: Path = PID_FILE,
) -> HubStatus:
    """Check the hub server's current status.

    Returns a :class:`HubStatus` with health, PID, and PID file info.

    Args:
        config: Config object. If None, loads from default location.
        pid_file: Path to the PID file.
    """
    if config is None:
        config, _ = load_config()

    host = config.server.host
    port = config.server.port
    base_url = f"http://{host}:{port}"

    healthy = await _check_health(base_url)
    pid = _read_pid(pid_file)
    pid_file_exists = pid_file.exists()

    # If PID file is missing but server is healthy, try to find the PID.
    if pid is None and healthy:
        pid = _find_server_pid(port)

    # If PID is stale, clear it.
    if pid is not None and not _pid_is_running(pid):
        pid = None

    return HubStatus(
        healthy=healthy,
        base_url=base_url,
        pid=pid,
        pid_file_exists=pid_file_exists,
    )
