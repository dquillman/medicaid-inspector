"""
Background task status endpoints.
GET /api/admin/tasks       — list recent tasks
GET /api/admin/tasks/{id}  — get specific task status
"""
from fastapi import APIRouter, HTTPException, Depends
from core.task_queue import get_all_tasks, get_task_status
from routes.auth import require_admin

router = APIRouter(prefix="/api/admin", tags=["tasks"], dependencies=[Depends(require_admin)])


@router.get("/tasks")
async def list_tasks():
    """Return recent background tasks with status."""
    return {"tasks": get_all_tasks()}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Return a specific task's status."""
    task = get_task_status(task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")
    return task
