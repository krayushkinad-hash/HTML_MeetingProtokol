"""Transcription progress — only legacy cancel logic remains.

E126: _jobs dict, create_job, update_job, get_job — мёртвый код.
Единственный источник правды — transcription_service._tasks + БД.
Cancel logic остаётся потому что router вызывает его синхронно.
"""
import asyncio
import logging
from typing import Dict, Optional

from app.services.active_tasks import _active_transcription_tasks

logger = logging.getLogger(__name__)

# E126: _jobs dict оставлен для cancel_job (legacy API совместимости)
_jobs: Dict[str, dict] = {}


def create_job(protocol_id: str, task_id: str) -> dict:
    """E126: DEPRECATED — оставлено для обратной совместимости.

    Реальный статус хранится в transcription_service._tasks.
    """
    job = {
        "task_id": task_id,
        "protocol_id": protocol_id,
        "status": "starting",
        "progress": 0,
        "message": "Инициализация...",
        "segments_count": 0,
    }
    _jobs[task_id] = job
    return job


def update_job(task_id: str, status: str = None, progress: int = None,
               message: str = None, segments_count: int = None):
    """E126: DEPRECATED — no-op."""
    pass


def get_job(task_id: str) -> Optional[dict]:
    """E126: DEPRECATED — returns stub."""
    return _jobs.get(task_id)


# E096: Pending DB cancels — async endpoint processes these
_pending_db_cancels: set[str] = set()


def cancel_job(task_id: str) -> bool:
    """Mark job as cancelled.

    E095/E096: Sync function — schedules async work:
    1. _jobs dict — sync (immediately)
    2. asyncio.Task in registry — sync cancel
    3. DB cancel — processed by next /progress-by-protocol call

    E099: Returns False if task not found anywhere.
    """
    found = False

    # 1. In-memory _jobs (legacy, sync)
    if task_id in _jobs:
        _jobs[task_id]["status"] = "cancelled"
        _jobs[task_id]["message"] = "Отменено пользователем"
        found = True

    # 2. asyncio.Task cancel — stop CPU work immediately
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
        # E106: Log if task not found
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
        logging.getLogger(__name__).warning("cancelled_task_exception", error=str(e))
        return
    if not bg_task.cancelled():
        logging.getLogger(__name__).warning("task_ignored_cancel", task_repr=str(bg_task))


def get_pending_cancels() -> set[str]:
    """E096: Get and clear pending DB cancels."""
    pending = _pending_db_cancels.copy()
    _pending_db_cancels.clear()
    return pending


def cleanup_old_jobs(max_age_seconds: int = 3600):
    """Remove jobs older than max_age_seconds."""
    import time
    now = time.time()
    to_delete = [
        task_id for task_id, job in _jobs.items()
        if isinstance(job, dict) and "updated_at" in job
        and now - job["updated_at"] > max_age_seconds
    ]
    for task_id in to_delete:
        del _jobs[task_id]
    return len(to_delete)
