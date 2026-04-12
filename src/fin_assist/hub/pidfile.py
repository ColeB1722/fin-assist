"""Server-side PID file management with file locking.

The hub server writes and locks the PID file for its entire lifetime.
On shutdown (clean exit, SIGTERM), the file is removed via ``atexit``.
On crash/SIGKILL, the OS releases the lock — clients detect the stale
file by attempting a non-blocking ``flock``.

This module is only used by the server process (``fin-assist serve``).
Client-side PID reading lives in ``cli/server.py``.
"""

from __future__ import annotations

import atexit
import contextlib
import fcntl
import os
import signal
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


_pid_fd: int | None = None
_pid_path: Path | None = None


def acquire(pid_file: Path) -> None:
    """Write the current PID to *pid_file* and hold an exclusive lock.

    The lock is held until the process exits.  On normal exit the
    ``atexit`` handler removes the file.  On SIGKILL the OS releases
    the lock but leaves the file — callers should use :func:`is_locked`
    to detect stale files.

    Raises ``SystemExit`` if another server already holds the lock.
    """
    global _pid_fd, _pid_path  # noqa: PLW0603

    pid_file.parent.mkdir(parents=True, exist_ok=True)

    fd = os.open(str(pid_file), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        print(
            f"Another hub is already running (lock held on {pid_file}).",
            file=sys.stderr,
        )
        sys.exit(1)

    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, f"{os.getpid()}\n".encode())
    os.fsync(fd)

    _pid_fd = fd
    _pid_path = pid_file

    atexit.register(release)

    # Replace default SIGTERM handler so atexit functions run on SIGTERM.
    # The default SIGTERM handler terminates without running atexit.
    def _sigterm(signum: int, frame: object) -> None:  # noqa: ARG001
        # Trigger normal shutdown so atexit handlers fire.
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sigterm)


def release() -> None:
    """Remove the PID file and release the lock.

    Safe to call multiple times.  Registered as an ``atexit`` handler
    by :func:`acquire`.
    """
    global _pid_fd, _pid_path  # noqa: PLW0603

    if _pid_fd is not None:
        with contextlib.suppress(OSError):
            fcntl.flock(_pid_fd, fcntl.LOCK_UN)
            os.close(_pid_fd)
        _pid_fd = None

    if _pid_path is not None:
        with contextlib.suppress(OSError):
            _pid_path.unlink(missing_ok=True)
        _pid_path = None


def is_locked(pid_file: Path) -> bool:
    """Return True if *pid_file* is currently held by a running process.

    Uses a non-blocking ``flock`` probe: if we can acquire the lock the
    file is stale; if we can't, a server holds it.
    """
    if not pid_file.exists():
        return False

    try:
        fd = os.open(str(pid_file), os.O_RDONLY)
    except OSError:
        return False

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # We got the lock — file is stale.
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        # Lock is held by another process — server is alive.
        return True
    finally:
        os.close(fd)
