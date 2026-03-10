"""
Atomic JSON writes with file locking.
Prevents data corruption from concurrent writes or process crashes mid-write.

Uses threading locks per file path (process-safe) and atomic write via
tempfile + os.replace (filesystem-safe).
"""
import json
import os
import tempfile
import threading
import pathlib
from typing import Any

# Per-path threading locks for in-process safety
_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _get_lock(path: str) -> threading.Lock:
    """Return (or create) a threading lock for the given file path."""
    with _locks_lock:
        if path not in _locks:
            _locks[path] = threading.Lock()
        return _locks[path]


def atomic_write_json(path: pathlib.Path | str, data: Any, indent: int | None = None) -> None:
    """
    Write JSON data to `path` atomically.

    1. Acquire a per-path threading lock.
    2. Write to a temp file in the same directory.
    3. os.replace() the temp file onto the target (atomic on most filesystems).

    If the process crashes mid-write, only the temp file is left behind — the
    original file remains intact.
    """
    path = pathlib.Path(path)
    path_str = str(path.resolve())
    lock = _get_lock(path_str)

    with lock:
        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file in same directory (same filesystem for atomic rename)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=f".{path.stem}_",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, default=str, indent=indent)
            # Atomic replace
            os.replace(tmp_path, str(path))
        except BaseException:
            # Clean up temp file on any error
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def locked_read_json(path: pathlib.Path | str) -> Any:
    """
    Read a JSON file with a shared (threading) lock.
    Returns None if the file does not exist.
    """
    path = pathlib.Path(path)
    path_str = str(path.resolve())
    lock = _get_lock(path_str)

    with lock:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
