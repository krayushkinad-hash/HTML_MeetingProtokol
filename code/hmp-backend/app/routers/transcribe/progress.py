"""Progress tracking helpers for the transcription router.

Holds the helpers shared by the local and upgrade sub-modules:

  * ``_serialize_task_status`` — convert an in-memory ``TranscriptionStatus``
    (or anything that quacks like one) to a JSON-safe ``dict``.
  * ``_get_progress_internal`` — DB lookup for the latest progress record
    tied to a protocol. Used by both ``/transcribe/progress/...`` and
    ``/transcribe/progress-by-protocol/{protocol_id}``.

The two HTTP entry points are exposed in ``app.routers.transcribe_pkg.local``
(run/status/cancel/pause/resume) and the dedicated progress routes live here.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import get_logger
from app.db.session import get_db
from app.services.transcription import transcription_service

# E098: Registry moved to app.services.active_tasks (avoid circular imports)
from app.services.active_tasks import (
    _active_transcription_tasks,
    is_task_alive,
)

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_task_status(task_id: str, status_obj) -> dict:
    """Serialize ``TranscriptionStatus`` to dict for JSON response.

    The service stores either ORM instances or plain dicts depending on
    backend state, so we read attributes defensively.
    """
    try:
        return {
            "id": str(status_obj.id),
            "task_id": str(status_obj.id),
            "protocol_id": str(status_obj.protocol_id),
            "status": status_obj.status,
            "progress": status_obj.progress_percent,
            "progress_percent": status_obj.progress_percent,
            "message": (
                status_obj.message
                or status_obj.error_message
                or f"Транскрипция: {status_obj.status}"
            ),
            "segments_count": status_obj.current_chunk or 0,
            "peak_rss_mb": status_obj.peak_rss_mb,
            "estimated_completion": (
                status_obj.estimated_completion.isoformat()
                if status_obj.estimated_completion
                else None
            ),
        }
    except Exception:
        return {
            "task_id": str(task_id),
            "status": "unknown",
            "progress": 0,
            "message": "Ошибка сериализации",
        }


async def _get_progress_internal(
    protocol_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """Internal logic for transcription progress.

    E082: Verify task is REALLY alive in active registry, not just DB status.
    E096: Process pending DB cancels scheduled by sync cancel_job endpoint.
    """
    # E096/E101: Process pending DB cancels from sync endpoint
    try:
        from app.services.transcription_progress import (
            get_pending_cancels,
            _pending_db_cancels,
        )
        pending = get_pending_cancels()
        if pending:
            from app.db.models import TranscriptionTask as _TTCancel
            try:
                for tid_str in pending:
                    try:
                        tid_uuid = uuid.UUID(tid_str)
                        task = await db.get(_TTCancel, tid_uuid)
                        if task and task.status in ("queued", "running", "starting"):
                            task.status = "cancelled"
                            task.error_message = "Отменено пользователем"
                            task.finished_at = datetime.now(timezone.utc)
                            logger.info(
                                "pending_cancel_applied", task_id=tid_str
                            )
                    except (ValueError, TypeError) as uuid_err:
                        logger.warning(
                            "pending_cancel_invalid_uuid",
                            task_id=tid_str,
                            error=str(uuid_err),
                        )
                    except Exception as cancel_err:
                        logger.warning(
                            "pending_cancel_apply_failed",
                            task_id=tid_str,
                            error=str(cancel_err),
                        )
                await db.commit()
            except Exception as commit_err:
                await db.rollback()
                _pending_db_cancels.update(pending)
                logger.warning(
                    "pending_cancel_batch_failed",
                    error=str(commit_err),
                    count=len(pending),
                )
    except Exception:
        pass

    try:
        from app.db.models import TranscriptionTask as _TT
    except ImportError:
        return {
            "id": None,
            "task_id": None,
            "protocol_id": str(protocol_id),
            "status": "unknown",
            "progress": 0,
            "message": "TranscriptionTask модель недоступна",
        }

    from app.db.models import Protocol, TranscriptionTask

    # Get protocol
    proto_result = await db.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )
    protocol = proto_result.scalar_one_or_none()

    if not protocol:
        return {
            "id": None,
            "task_id": None,
            "protocol_id": str(protocol_id),
            "status": "unknown",
            "progress": 0,
            "message": "Протокол не найден",
        }

    # Find active task (E108: limit 1)
    task_result = await db.execute(
        select(TranscriptionTask)
        .where(TranscriptionTask.protocol_id == protocol_id)
        .where(TranscriptionTask.status.in_(["queued", "running", "starting"]))
        .order_by(TranscriptionTask.started_at.desc())
        .limit(1)
    )
    task = task_result.scalar_one_or_none()

    if task:
        # E082: Verify task is alive in active registry
        task_id_str = str(task.id)
        is_alive_in_registry = is_task_alive(task_id_str)

        # E078/E079: Detect stale "running" tasks with safe datetime
        is_stale = False
        age_sec = 0
        if task.started_at and task.status in ("queued", "running", "starting"):
            started = task.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            age_sec = (datetime.now(timezone.utc) - started).total_seconds()

            if not is_alive_in_registry and age_sec > 60:
                is_stale = True
                logger.warning(
                    "task_not_in_registry",
                    task_id=task_id_str,
                    age_sec=int(age_sec),
                    registry_size=len(_active_transcription_tasks),
                )
            # E122: 60 минут вместо 20 (CPU base на часовой записи — норма, не stale)
            elif age_sec > 3600 and (task.progress or 0) < 0.1:
                is_stale = True

        if is_stale:
            task.status = "failed"
            task.error_message = (
                f"Задача зависла (started {int(age_sec)}s назад, "
                f"progress={task.progress})"
            )
            task.finished_at = datetime.now(timezone.utc)
            try:
                await db.commit()
                logger.info(
                    "stale_task_marked_failed",
                    task_id=task_id_str,
                    protocol_id=str(protocol_id),
                    age_sec=int(age_sec),
                )
            except Exception as commit_err:
                await db.rollback()
                logger.warning(
                    "stale_task_commit_failed",
                    task_id=task_id_str,
                    error=str(commit_err),
                )

        return {
            "id": task_id_str,
            "task_id": task_id_str,
            "protocol_id": str(protocol_id),
            "status": task.status,
            "progress": task.progress or 0,
            # E127: current_step хранит "Обработка 145с..." — отдаём его во фронт
            "message": (
                task.error_message
                or task.current_step
                or f"Транскрипция: {task.status}"
            ),
            "segments_count": task.current_chunk or 0,
            "started_at": task.started_at.isoformat() if task.started_at else None,
        }

    # No active task - reset stuck protocol if needed
    if protocol.status == "transcribing":
        try:
            # E128: "idle" нет в enum — используем "loaded"
            protocol.status = "loaded"
            await db.commit()
            logger.info(
                "stuck_protocol_reset_to_loaded", protocol_id=str(protocol_id)
            )
        except Exception as reset_err:
            await db.rollback()
            logger.warning(
                "stuck_protocol_reset_failed",
                protocol_id=str(protocol_id),
                error=str(reset_err),
            )
        return {
            "id": None,
            "task_id": None,
            "protocol_id": str(protocol_id),
            "status": "unknown",
            "progress": 0,
            "message": (
                "Предыдущая транскрипция была прервана (зависла). "
                "Можно запустить заново."
            ),
        }

    # E090: Fallback — progress всегда 0 для неактивных
    return {
        "id": None,
        "task_id": None,
        "protocol_id": str(protocol_id),
        "status": protocol.status if protocol.status else "idle",
        "progress": 0,
        "message": f"Статус: {protocol.status or 'idle'}",
    }


# ---------------------------------------------------------------------------
# GET /transcribe/progress/{task_id}
# ---------------------------------------------------------------------------


@router.get(
    "/transcribe/progress/{task_id}",
    summary="Get progress by task_id",
)
async def get_transcription_progress(
    task_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get transcription progress by task_id."""
    # 1. In-memory (живая задача)
    try:
        status_obj = transcription_service.get_status(task_id)
    except Exception as e:
        logger.warning("get_status_failed", task_id=task_id, error=str(e))
        status_obj = None

    if status_obj is not None:
        try:
            return _serialize_task_status(task_id, status_obj)
        except Exception as e:
            logger.exception(
                "serialize_task_status_failed", task_id=task_id, error=str(e)
            )

    # 2. DB fallback
    try:
        from app.db.models import TranscriptionTask as _TT
        from app.db.models import Utterance as _U
        from sqlalchemy import func, select as _select

        task = await db.get(_TT, task_id)
        if task:
            # E131: реальное число уже сохранённых utterance
            count_result = await db.execute(
                _select(func.count(_U.id)).where(
                    _U.protocol_id == task.protocol_id
                )
            )
            utterances_count = count_result.scalar() or 0
            return {
                "id": str(task.id),
                "task_id": str(task.id),
                "protocol_id": str(task.protocol_id),
                "status": task.status,
                "progress": task.progress or 0,
                "progress_percent": task.progress or 0,
                # E127: current_step → message
                "message": (
                    task.error_message
                    or task.current_step
                    or f"Транскрипция: {task.status}"
                ),
                "segments_count": utterances_count,
            }
    except Exception as e:
        logger.warning("db_progress_lookup_failed", task_id=task_id, error=str(e))

    # 3. Not found
    return {
        "task_id": task_id,
        "status": "unknown",
        "progress": 0,
        "progress_percent": 0,
        "message": "Задача не найдена или сервер был перезапущен",
    }


# ---------------------------------------------------------------------------
# GET /transcribe/progress-by-protocol/{protocol_id}
# ---------------------------------------------------------------------------


@router.get(
    "/transcribe/progress-by-protocol/{protocol_id}",
    summary="Get transcription progress by protocol",
)
async def get_transcription_progress_by_protocol(
    protocol_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get current transcription progress for a protocol."""
    try:
        return await _get_progress_internal(protocol_id, db)
    except Exception as e:
        logger.error(
            "transcription_progress_error",
            protocol_id=str(protocol_id),
            error=str(e),
            exc_info=True,
        )
        return {
            "id": None,
            "task_id": None,
            "protocol_id": str(protocol_id),
            "status": "error",
            "progress": 0,
            "message": f"Ошибка получения прогресса: {str(e)[:200]}",
        }