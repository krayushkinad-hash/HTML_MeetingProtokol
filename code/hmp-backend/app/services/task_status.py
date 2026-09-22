"""Task status update helper (E116).

Extracted from transcribe.py to avoid circular imports between
transcription.py and transcribe.py.
"""
from app.core.logging_config import get_logger

logger = get_logger(__name__)


async def update_task_status_in_db(
    task_id,
    status: str,
    progress: float = None,
    error: str = None,
) -> None:
    """Update TranscriptionTask status in DB.

    Uses AsyncSessionLocal (async) to avoid greenlet_spawn errors.
    Caller can await (for final updates) or fire-and-forget (for intermediate).

    E115: Async session, no greenlet_spawn.
    E116: Extracted to separate module (no circular imports).
    """
    try:
        from app.db.models import TranscriptionTask as _TT
        from app.db.session import AsyncSessionLocal
        from datetime import datetime as _dt

        async with AsyncSessionLocal() as session:
            tt = await session.get(_TT, task_id)
            if tt:
                tt.status = status
                if progress is not None:
                    tt.progress = progress
                if error is not None:
                    tt.error_message = error
                tt.finished_at = _dt.utcnow()
                await session.commit()
                logger.info(
                    "task_status_updated_in_db",
                    task_id=str(task_id),
                    status=status,
                )
    except Exception as e:
        logger.warning(
            "task_status_update_failed",
            task_id=str(task_id),
            status=status,
            error=str(e),
        )
