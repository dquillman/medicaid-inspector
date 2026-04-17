"""
File-based scan lock for multi-process safe scan coordination.

Replaces the in-memory `_scan_running` global flag with a file-based lock
(`backend/.scan.lock`) that works across multiple uvicorn workers.

The lock file contains: PID:TIMESTAMP
- PID: process ID that owns the lock
- TIMESTAMP: when the lock was acquired (epoch)

Stale lock detection: if the owning process is dead (os.kill check) or
the lock is older than STALE_LOCK_SECONDS, it is considered stale and
can be overridden.
"""
import logging
import os
import pathlib
import time

log = logging.getLogger(__name__)

SCAN_LOCK_FILE = pathlib.Path(__file__).parent.parent / ".scan.lock"
STALE_LOCK_SECONDS = 600  # 10 minutes


def _atomic_create_lock() -> bool:
    """
    Try to create the lock file atomically with O_EXCL semantics.
    Returns True if we created it, False if it already existed.
    Works cross-platform (Unix + Windows).
    """
    try:
        # O_CREAT | O_EXCL is atomic on all platforms — if the file exists,
        # this raises FileExistsError and we never overwrite.
        fd = os.open(str(SCAN_LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    except OSError as e:
        log.error("[scan_lock] Could not create lock file: %s", e)
        return False
    try:
        os.write(fd, f"{os.getpid()}:{time.time()}".encode("utf-8"))
    finally:
        os.close(fd)
    return True


def acquire_scan_lock() -> bool:
    """
    Try to acquire the file-based scan lock.
    Returns True on success, False if another process holds it.
    Automatically overrides stale locks from crashed/dead processes.
    """
    # Fast path: atomic create. If it succeeds, we hold the lock.
    if _atomic_create_lock():
        return True

    # Lock already exists — decide if it is stale. If it is, remove it and
    # retry the atomic create. A failed retry means someone else won the race.
    try:
        lock_content = SCAN_LOCK_FILE.read_text(encoding="utf-8").strip()
        parts = lock_content.split(":")
        pid = int(parts[0])
        lock_time = float(parts[1]) if len(parts) > 1 else 0

        stale = False
        try:
            os.kill(pid, 0)  # Signal 0 = check if process exists
            if time.time() - lock_time > STALE_LOCK_SECONDS:
                log.warning(
                    "[scan_lock] Stale lock from PID %d (%.0fs old) — overriding",
                    pid, time.time() - lock_time,
                )
                stale = True
        except (OSError, ProcessLookupError):
            log.warning("[scan_lock] Stale lock from dead PID %d — overriding", pid)
            stale = True

        if not stale:
            return False

        # Best-effort remove and retry. If the unlink or the retry loses a
        # race to another process, we return False rather than overwrite.
        try:
            SCAN_LOCK_FILE.unlink(missing_ok=True)
        except OSError as e:
            log.warning("[scan_lock] Could not remove stale lock: %s", e)
            return False
        return _atomic_create_lock()
    except Exception as e:
        log.warning("[scan_lock] Could not parse lock file: %s", e)
        return False


def release_scan_lock() -> None:
    """Release the scan lock if the current process owns it."""
    try:
        if SCAN_LOCK_FILE.exists():
            lock_content = SCAN_LOCK_FILE.read_text(encoding="utf-8").strip()
            pid = int(lock_content.split(":")[0])
            if pid == os.getpid():
                SCAN_LOCK_FILE.unlink(missing_ok=True)
    except Exception as e:
        log.warning("[scan_lock] Could not release lock: %s", e)


def is_scan_running() -> bool:
    """Check if any process currently holds the scan lock."""
    if not SCAN_LOCK_FILE.exists():
        return False
    try:
        lock_content = SCAN_LOCK_FILE.read_text(encoding="utf-8").strip()
        parts = lock_content.split(":")
        pid = int(parts[0])
        lock_time = float(parts[1]) if len(parts) > 1 else 0

        try:
            os.kill(pid, 0)
            # Process alive -- check staleness
            return time.time() - lock_time <= STALE_LOCK_SECONDS
        except (OSError, ProcessLookupError):
            return False  # Dead process
    except Exception:
        return False
