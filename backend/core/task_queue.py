"""
Simple in-process background task queue with status tracking.

Provides a centralized way to run and monitor background tasks (scans,
enrichment, etc.) instead of raw asyncio.create_task calls.

Tasks are stored in memory (last 100) with status tracking:
  queued -> running -> completed | failed
"""
import asyncio
import logging
import time
import uuid
from collections import deque
from typing import Any, Callable, Coroutine, Optional

log = logging.getLogger(__name__)

MAX_TASK_HISTORY = 100


class Task:
    """Represents a queued/running/completed background task."""

    def __init__(self, task_id: str, task_type: str):
        self.id = task_id
        self.type = task_type
        self.status = "queued"  # queued | running | completed | failed
        self.created_at = time.time()
        self.started_at: Optional[float] = None
        self.completed_at: Optional[float] = None
        self.result: Any = None
        self.error: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "type": self.type,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }
        # Include result summary (not full data — could be huge)
        if self.result is not None:
            if isinstance(self.result, dict):
                d["result"] = self.result
            else:
                d["result"] = str(self.result)
        else:
            d["result"] = None

        # Duration
        if self.started_at:
            end = self.completed_at or time.time()
            d["duration_sec"] = round(end - self.started_at, 1)
        else:
            d["duration_sec"] = None

        return d


# ── Global task registry ────────────────────────────────────────────────────

_tasks: deque[Task] = deque(maxlen=MAX_TASK_HISTORY)
_tasks_by_id: dict[str, Task] = {}


def _register_task(task: Task) -> None:
    """Add task to the registry, evicting old entries if at capacity."""
    _tasks.append(task)
    _tasks_by_id[task.id] = task
    # Clean up evicted entries from the dict
    if len(_tasks_by_id) > MAX_TASK_HISTORY * 2:
        active_ids = {t.id for t in _tasks}
        stale = [k for k in _tasks_by_id if k not in active_ids]
        for k in stale:
            del _tasks_by_id[k]


def enqueue_task(
    task_type: str,
    func: Callable[..., Coroutine],
    *args: Any,
    **kwargs: Any,
) -> str:
    """
    Enqueue an async function as a background task.

    Returns the task ID. The function is scheduled via asyncio.create_task
    and wrapped to track status automatically.
    """
    task_id = uuid.uuid4().hex[:12]
    task = Task(task_id, task_type)
    _register_task(task)

    async def _wrapper():
        task.status = "running"
        task.started_at = time.time()
        log.info("[task_queue] Task %s (%s) started", task_id, task_type)
        try:
            result = await func(*args, **kwargs)
            task.status = "completed"
            task.completed_at = time.time()
            task.result = result
            log.info(
                "[task_queue] Task %s (%s) completed in %.1fs",
                task_id, task_type,
                task.completed_at - task.started_at,
            )
        except Exception as exc:
            task.status = "failed"
            task.completed_at = time.time()
            task.error = str(exc)
            log.error(
                "[task_queue] Task %s (%s) failed: %s",
                task_id, task_type, exc,
                exc_info=True,
            )

    asyncio.create_task(_wrapper())
    return task_id


def get_task_status(task_id: str) -> Optional[dict]:
    """Return task status dict, or None if not found."""
    task = _tasks_by_id.get(task_id)
    return task.to_dict() if task else None


def get_all_tasks() -> list[dict]:
    """Return all tracked tasks, newest first."""
    return [t.to_dict() for t in reversed(_tasks)]
