"""Server-side PID file management with file locking.

The hub server writes and locks the PID file for its entire lifetime.
On shutdown (clean exit, SIGTERM), the file is removed via ``atexit``.
On crash/SIGKILL, the OS releases the lock — clients detect the stale
file by attempting a non-blocking lock probe via :func:`is_locked`.

Uses the ``filelock`` library for cross-platform locking:
- Unix: ``fcntl.flock``
- Windows: ``msvcrt.locking``

This module is only used by the server process (``fin-assist serve``).
Client-side PID reading lives in ``cli/server.py``.
"""

from __future__ import annotations

import atexit
import contextlib
import os
import signal
import sys
from typing import TYPE_CHECKING

from filelock import BaseFileLock, FileLock, Timeout

if TYPE_CHECKING:
    from pathlib import Path


_lock: BaseFileLock | None = None
_pid_path: Path | None = None


def acquire(pid_file: Path) -> None:
    """Write the current PID to *pid_file* and hold an exclusive lock.

    The lock is held until the process exits.  On normal exit the
    ``atexit`` handler removes the file.  On SIGKILL the OS releases
    the lock but leaves the file — callers should use :func:`is_locked`
    to detect stale files.

    Raises ``SystemExit`` if another server already holds the lock.
    """
    global _lock, _pid_path  # noqa: PLW0603

    pid_file.parent.mkdir(parents=True, exist_ok=True)

    lock = FileLock(str(pid_file), timeout=0)
    try:
        lock.acquire()
    except Timeout:
        print(
            f"Another hub is already running (lock held on {pid_file}).",
            file=sys.stderr,
        )
        sys.exit(1)

    pid_file.write_text(f"{os.getpid()}\n")

    _lock = lock
    _pid_path = pid_file

    atexit.register(release)

    if sys.platform != "win32":

        def _sigterm(signum: int, frame: object) -> None:  # noqa: ARG001
            sys.exit(0)

        signal.signal(signal.SIGTERM, _sigterm)


def release() -> None:
    """Remove the PID file and release the lock.

    Safe to call multiple times.  Registered as an ``atexit`` handler
    by :func:`acquire`.
    """
    global _lock, _pid_path  # noqa: PLW0603

    if _lock is not None:
        with contextlib.suppress(OSError):
            _lock.release()
        _lock = None

    if _pid_path is not None:
        with contextlib.suppress(OSError):
            _pid_path.unlink(missing_ok=True)
        _pid_path = None


def is_locked(pid_file: Path) -> bool:
    """Return True if *pid_file* is currently held by a running process.

    Uses a non-blocking lock probe: if we can acquire the lock the
    file is stale; if we can't, a server holds it.
    """
    if not pid_file.exists():
        return False

    lock = FileLock(str(pid_file), timeout=0)
    try:
        lock.acquire()
        lock.release()
        return False
    except Timeout:
        return True
