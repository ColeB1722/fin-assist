"""Server-side PID file management with file locking.

The hub server writes its PID to a plain text file (``hub.pid``) and
holds an exclusive lock on a sidecar file (``hub.pid.lock``) for its
entire lifetime.  On shutdown (clean exit, SIGTERM), both files are
removed via ``atexit``.  On crash/SIGKILL, the OS releases the lock
but leaves the files — clients detect the stale state by attempting
a non-blocking lock probe via :func:`is_locked`.

Uses the ``filelock`` library for cross-platform locking:
- Unix: ``fcntl.flock``
- Windows: ``msvcrt.locking``

A sidecar lock file is required because on Windows ``msvcrt.locking``
locks byte ranges of the file you open — meaning you cannot also write
to that same file with a separate handle (PermissionError).  Using a
dedicated lock file decouples the lock semantics from the PID payload.

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
_lock_path: Path | None = None


def _lock_path_for(pid_file: Path) -> Path:
    """Return the sidecar lock-file path for *pid_file*."""
    return pid_file.with_name(pid_file.name + ".lock")


def acquire(pid_file: Path) -> None:
    """Write the current PID to *pid_file* and hold an exclusive lock.

    The lock is held on a sidecar ``<pid_file>.lock`` file until the
    process exits.  On normal exit the ``atexit`` handler removes both
    files.  On SIGKILL the OS releases the lock but leaves the files —
    callers should use :func:`is_locked` to detect stale state.

    Raises ``SystemExit`` if another server already holds the lock.
    """
    global _lock, _pid_path, _lock_path  # noqa: PLW0603

    pid_file.parent.mkdir(parents=True, exist_ok=True)

    lock_file = _lock_path_for(pid_file)
    lock = FileLock(str(lock_file), timeout=0)
    try:
        lock.acquire()
    except Timeout:
        print(
            f"Another hub is already running (lock held on {lock_file}).",
            file=sys.stderr,
        )
        sys.exit(1)

    pid_file.write_text(f"{os.getpid()}\n")

    _lock = lock
    _pid_path = pid_file
    _lock_path = lock_file

    atexit.register(release)

    if sys.platform != "win32":

        def _sigterm(signum: int, frame: object) -> None:  # noqa: ARG001
            sys.exit(0)

        signal.signal(signal.SIGTERM, _sigterm)


def release() -> None:
    """Remove the PID and lock files and release the lock.

    Safe to call multiple times.  Registered as an ``atexit`` handler
    by :func:`acquire`.
    """
    global _lock, _pid_path, _lock_path  # noqa: PLW0603

    if _lock is not None:
        with contextlib.suppress(OSError):
            _lock.release()
        _lock = None

    if _pid_path is not None:
        with contextlib.suppress(OSError):
            _pid_path.unlink(missing_ok=True)
        _pid_path = None

    if _lock_path is not None:
        with contextlib.suppress(OSError):
            _lock_path.unlink(missing_ok=True)
        _lock_path = None


def is_locked(pid_file: Path) -> bool:
    """Return True if *pid_file* is currently held by a running process.

    Uses a non-blocking lock probe on the sidecar lock file: if we
    can acquire it, the PID file is stale; if we can't, a server holds it.
    """
    if not pid_file.exists():
        return False

    lock_file = _lock_path_for(pid_file)
    if not lock_file.exists():
        # PID file present but no lock file — definitely stale.
        return False

    lock = FileLock(str(lock_file), timeout=0)
    try:
        lock.acquire()
        lock.release()
        return False
    except Timeout:
        return True
