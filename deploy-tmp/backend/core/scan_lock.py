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


def acquire_scan_lock() -> bool:
    """
    Try to acquire the file-based scan lock.
    Returns True on success, False if another process holds it.
    Automatically overrides stale locks from crashed/dead processes.
    """
    if SCAN_LOCK_FILE.exists():
        try:
            lock_content = SCAN_LOCK_FILE.read_text(encoding="utf-8").strip()
            parts = lock_content.split(":")
            pid = int(parts[0])
            lock_time = float(parts[1]) if len(parts) > 1 else 0

            try:
                os.kill(pid, 0)  # Signal 0 = check if process exists
                # Process is alive -- check if lock is stale by age
                if time.time() - lock_time > STALE_LOCK_SECONDS:
                    log.warning(
                        "[scan_lock] Stale lock from PID %d (%.0fs old) — overriding",
                        pid, time.time() - lock_time,
                    )
                else:
                    return False  # Lock is held and not stale
            except (OSError, ProcessLookupError):
                # Process is dead -- stale lock
                log.warning("[scan_lock] Stale lock from dead PID %d — overriding", pid)
        except Exception as e:
            log.warning("[scan_lock] Could not parse lock file: %s — overriding", e)

    # Write our PID and timestamp
    try:
        SCAN_LOCK_FILE.write_text(f"{os.getpid()}:{time.time()}", encoding="utf-8")
        return True
    except Exception as e:
        log.error("[scan_lock] Could not write lock file: %s", e)
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
