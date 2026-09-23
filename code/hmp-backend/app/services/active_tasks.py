"""Active transcription tasks registry (shared between modules).

E098: Extracted to avoid circular imports between
app.routers.transcribe and app.services.transcription_progress.
"""
import asyncio
from typing import Dict


# Global registry of active transcription tasks (asyncio.Task handles)
_active_transcription_tasks: Dict[str, asyncio.Task] = {}


def register_active_task(task_id_str: str, task: asyncio.Task) -> None:
    """Register a running transcription task."""
    _active_transcription_tasks[task_id_str] = task


def unregister_active_task(task_id_str: str) -> None:
    """Unregister a completed/failed task."""
    _active_transcription_tasks.pop(task_id_str, None)


def is_task_alive(task_id_str: str) -> bool:
    """Check if task is still alive in registry.

    Synchronous (no await) — safe under GIL for single-process asyncio.
    """
    task = _active_transcription_tasks.get(task_id_str)
    if task is None:
        return False
    if task.done():
        # Auto-cleanup
        _active_transcription_tasks.pop(task_id_str, None)
        return False
    return True


def get_active_task(task_id_str: str):
    """Get active task (or None if not registered)."""
    return _active_transcription_tasks.get(task_id_str)
