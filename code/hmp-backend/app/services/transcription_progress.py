"""Transcription progress tracker with WebSocket support."""
import asyncio
import json
import logging
import time
import uuid
from typing import Dict, Optional

# E105: Imports at module level (no circular — active_tasks doesn't import us)
from app.services.active_tasks import _active_transcription_tasks

logger = logging.getLogger(__name__)


# Global registry of active transcription jobs (legacy)
_jobs: Dict[str, dict] = {}


def create_job(protocol_id: str, task_id: str) -> dict:
    """Register a new transcription job."""
    job = {
        "task_id": task_id,
        "protocol_id": protocol_id,
        "status": "starting",  # starting, processing, completed, failed, cancelled
        "progress": 0,        # 0..100
        "message": "Инициализация...",
        "segments_count": 0,
        "started_at": time.time(),
        "updated_at": time.time(),
    }
    _jobs[task_id] = job
    return job


def update_job(task_id: str, status: str = None, progress: int = None, 
               message: str = None, segments_count: int = None):
    """Update job status."""
    if task_id not in _jobs:
        return
    job = _jobs[task_id]
    if status is not None:
        job["status"] = status
    if progress is not None:
        job["progress"] = max(0, min(100, progress))
    if message is not None:
        job["message"] = message
    if segments_count is not None:
        job["segments_count"] = segments_count
    job["updated_at"] = time.time()


def get_job(task_id: str) -> Optional[dict]:
    """Get job status."""
    return _jobs.get(task_id)


# E096: Async cancel signal — DB task for sync endpoint to schedule DB cancel
_pending_db_cancels: set[str] = set()


def cancel_job(task_id: str) -> bool:
    """Mark job as cancelled.

    E095/E096: Sync function — schedules async work:
    1. _jobs dict — sync (immediately)
    2. DB TranscriptionTask — schedule via _pending_db_cancels
       (processed by next _get_progress_internal call)
    3. asyncio.Task in registry — sync cancel
    """
    found = False

    # 1. In-memory _jobs (legacy, sync)
    if task_id in _jobs:
        _jobs[task_id]["status"] = "cancelled"
        _jobs[task_id]["message"] = "Отменено пользователем"
        _jobs[task_id]["updated_at"] = time.time()
        found = True

    # 2. asyncio.Task cancel — stop CPU work immediately
    # E098: Use shared registry from active_tasks module (no circular import)
    # E103: get() → cancel() → pop() order (not pop first)
    # Так _is_task_alive() не вернёт False между pop и cancel
    bg_task = _active_transcription_tasks.get(task_id)
    if bg_task:
        if not bg_task.done():
            bg_task.cancel()
            found = True
        # pop AFTER cancel — чтобы stale-detection не сработал
        _active_transcription_tasks.pop(task_id, None)

    # 3. Schedule DB cancel — only if found somewhere (E099)
    if found:
        _pending_db_cancels.add(task_id)
    else:
        # E106: Log if task not found — helps debug race conditions
        logger.warning(
            "cancel_job_not_found",
            task_id=task_id,
            in_jobs=task_id in _jobs,
            registry_size=len(_active_transcription_tasks),
        )

    return found


async def _await_cancelled_task(bg_task) -> None:
    """E097/E100: Await cancelled task to gracefully clean up resources."""
    try:
        await bg_task
    except asyncio.CancelledError:
        return
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "cancelled_task_exception", error=str(e)
        )
        return
    # E100: If we got here without exception — task was NOT cancelled
    # (it completed normally despite cancel() call)
    if not bg_task.cancelled():
        import logging
        logging.getLogger(__name__).warning(
            "task_ignored_cancel",
            task_repr=str(bg_task),
        )


def get_pending_cancels() -> set[str]:
    """Get and clear pending DB cancels (called from async context)."""
    pending = _pending_db_cancels.copy()
    _pending_db_cancels.clear()
    return pending


def cleanup_old_jobs(max_age_seconds: int = 3600):
    """Remove jobs older than max_age_seconds."""
    now = time.time()
    to_delete = [
        task_id for task_id, job in _jobs.items()
        if now - job["updated_at"] > max_age_seconds
    ]
    for task_id in to_delete:
        del _jobs[task_id]
    return len(to_delete)
