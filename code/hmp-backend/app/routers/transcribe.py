"""Transcription endpoints (US-005, US-006 — API §4.4, §4.5).

Workflow:
  1. POST /transcribe/run — start transcription (BackgroundTasks + queue)
  2. GET  /transcribe/status/{task_id} — poll progress
  3. POST /transcribe/cancel/{task_id} — cancel running task
  4. GET  /transcribe/health — model availability check

Background work is delegated to ``app.services.transcription.transcription_service``
(singleton, ADR-005). For very long audio the model may exceed RSS budget — the
service is expected to chunk into 30-sec windows (NFR §QG-7).
"""
import asyncio
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging_config import get_logger
from app.db.models import AudioFile, Protocol
from app.db.session import get_db
from app.schemas import TranscriptionRequest, TranscriptionStatus
from app.services.transcription import transcription_service

# E098: Registry moved to app.services.active_tasks (avoid circular imports)
from app.services.active_tasks import (
    _active_transcription_tasks,
    register_active_task,
    unregister_active_task,
    is_task_alive,
    get_active_task,
)

# Backward-compatible aliases (for code that still uses old names)
_unregister_active_task = unregister_active_task
_is_task_alive = is_task_alive

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _estimated_completion(duration_sec: int | None) -> datetime:
    """Rough ETA — assumes 0.3× realtime for large-v3 on CUDA, falls back to 5 min."""
    seconds = 300
    if duration_sec:
        # 0.3× realtime for large-v3 GPU
        seconds = max(60, int(duration_sec * 0.3))
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# POST /transcribe/run
# ---------------------------------------------------------------------------


@router.post(
    "/transcribe/run",
    response_model=TranscriptionStatus,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a transcription job for a protocol",
)
async def run_transcription(
    body: TranscriptionRequest,
    background_tasks: BackgroundTasks,    # parameter kept for API
    db: AsyncSession = Depends(get_db),
) -> TranscriptionStatus:
    """Queue a transcription job for ``protocol_id``.

    Validates the protocol exists, has an audio file, and isn't already in
    ``transcribing`` status, then schedules a background task that runs
    ``transcription_service.transcribe``.
    """
    # --- Validate protocol ----------------------------------------------
    proto_row = await db.execute(
        select(Protocol).where(Protocol.id == body.protocol_id)
    )
    protocol: Protocol | None = proto_row.scalar_one_or_none()
    if not protocol:
        logger.warning("transcribe_protocol_not_found", protocol_id=str(body.protocol_id))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Протокол {body.protocol_id} не найден",
        )

    # Check status - allow restart if stuck in transcribing
    if protocol.status == "transcribing":
        # Allow restart - reset status first
        # E093: Use "idle" (canonical frontend state) instead of "loaded"
        logger.info(
            "transcribe_protocol_already_transcribing_force_restart",
            protocol_id=str(protocol.id),
        )
        protocol.status = "idle"
        protocol.transcribed = False
        await db.commit()
    if protocol.status == "diarizing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Сначала дождитесь окончания диаризации",
        )

    # Audio file is mandatory for transcription
    if not protocol.audio_file_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="У протокола нет привязанного аудио-файла",
        )

    audio_row = await db.execute(
        select(AudioFile).where(AudioFile.id == protocol.audio_file_id)
    )
    audio_file: AudioFile | None = audio_row.scalar_one_or_none()

    if not audio_file:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Аудио-файл не найден на диске",
        )

    # --- Queue task ------------------------------------------------------
    task_id = uuid.uuid4()
    estimated = _estimated_completion(audio_file.duration_sec)

    # E102: Register in _jobs (transcription_progress) — needed for cancel_job
    try:
        from app.services.transcription_progress import create_job
        create_job(
            protocol_id=str(body.protocol_id),
            task_id=str(task_id),
        )
    except Exception as create_job_err:
        logger.warning("create_job_failed", error=str(create_job_err))

    # E094: Create initial in-memory status with ALL fields
    transcription_service._tasks[task_id] = _DummyStatus(  # noqa: SLF001 — service contract
        id=task_id,
        protocol_id=body.protocol_id,
        status="queued",
        progress_percent=0,
        current_chunk=0,
        total_chunks=None,
        peak_rss_mb=None,
        estimated_completion=estimated,
        error_message=None,
        wer_quality=None,
        message="Инициализация...",  # E113: human-readable for UI
    )

    # Persist task in DB for survival across backend restarts (US-066)
    try:
        from app.db.models import TranscriptionTask as _TTModel
        from datetime import datetime as _dt
        db_task = _TTModel(
            id=task_id,
            protocol_id=body.protocol_id,
            status="queued",
            progress=0.0,
            current_chunk=0,
            started_at=_dt.now(),
        )
        db.add(db_task)
        await db.commit()
        logger.info("transcription_task_persisted", task_id=str(task_id))
    except Exception as e:
        logger.warning("transcription_task_persist_failed", error=str(e))
        await db.rollback()

    logger.info(
        "transcribe_queued",
        task_id=str(task_id),
        protocol_id=str(body.protocol_id),
        model=body.model,
        language=body.language,
        beam_size=body.beam_size,
        compute_type=body.compute_type,
    )

    # --- Schedule background work ---------------------------------------
    audio_file_path_str = audio_file.file_path
    audio_path = Path(audio_file_path_str)

    async def _runner() -> None:
        try:
            # E113: Pass real audio duration to transcribe for accurate estimates
            await transcription_service.transcribe(
                protocol_id=body.protocol_id,
                audio_path=audio_path,
                task_id=task_id,
                duration_sec=audio_file.duration_sec,
            )
            # E116: Await final status update (don't fire-and-forget for final state)
            from app.services.task_status import update_task_status_in_db
            await update_task_status_in_db(task_id, "completed", progress=100.0)
        except Exception as exc:  # pragma: no cover — defensive
            logger.exception(
                "transcribe_runner_failed", task_id=str(task_id), error=str(exc)
            )
            # E116: Await failure update
            try:
                from app.services.task_status import update_task_status_in_db
                await update_task_status_in_db(
                    task_id, "failed", error=str(exc)[:500]
                )
            except Exception:
                pass

    # E086: Register task BEFORE starting — use setdefault for atomicity
    async def _runner_with_cleanup() -> None:
        try:
            await _runner()
        finally:
            _unregister_active_task(str(task_id))

    bg_task = asyncio.create_task(_runner_with_cleanup())
    # E092: Check task.done() BEFORE registration
    if not bg_task.done():
        register_active_task(str(task_id), bg_task)
        logger.info(
            "transcription_task_registered",
            task_id=str(task_id),
            registry_size=len(_active_transcription_tasks),
        )
    else:
        logger.warning(
            "transcription_task_died_before_registration",
            task_id=str(task_id),
        )
    # DO NOT use background_tasks.add_task — it would create a SECOND task

    # Mark protocol as transcribing (best-effort; rolled back if commit fails)
    protocol.status = "transcribing"
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("transcribe_status_update_failed", protocol_id=str(body.protocol_id))

    return TranscriptionStatus(
        task_id=task_id,
        protocol_id=body.protocol_id,
        status="queued",
        progress_percent=0,
        estimated_completion=estimated,
    )


# ---------------------------------------------------------------------------
# GET /transcribe/status/{task_id}
# ---------------------------------------------------------------------------


@router.get(
    "/transcribe/status/{task_id}",
    response_model=TranscriptionStatus,
    summary="Get transcription status",
)
async def get_transcription_status(task_id: uuid.UUID) -> TranscriptionStatus:
    """Get current transcription status by task_id."""
    status_obj = transcription_service.get_status(task_id)
    if status_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Задача {task_id} не найдена",
        )
    return status_obj


@router.post(
    "/transcribe/cancel/{task_id}",
    summary="Cancel a running transcription",
)
async def cancel_transcription_endpoint(
    task_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Cancel a running transcription job.

    E095-E097, E104: Cancel job syncs 4 places:
    1. _jobs dict (legacy)
    2. DB TranscriptionTask (SYNCHRONOUS, no pending queue)
    3. asyncio.Task cancel
    4. _pending_db_cancels cleanup
    """
    from app.services.transcription_progress import cancel_job, _pending_db_cancels

    # Get the bg_task BEFORE cancel_job pops it from registry
    bg_task_to_await = None
    try:
        bg_task_to_await = _active_transcription_tasks.get(task_id)
    except Exception:
        pass

    if not cancel_job(task_id):
        logger.warning("cancel_job_not_found", task_id=task_id)
        return {"task_id": task_id, "status": "not_found", "message": "Задача не найдена"}

    # E104: Apply cancel to DB SYNCHRONOUSLY (not via pending queue)
    try:
        from app.db.models import TranscriptionTask as _TT
        try:
            tid_uuid = uuid.UUID(task_id)
        except (ValueError, TypeError) as uuid_err:
            logger.warning("cancel_invalid_uuid", task_id=task_id, error=str(uuid_err))
            tid_uuid = None
        if tid_uuid is not None:
            task = await db.get(_TT, tid_uuid)
            if task and task.status in ("queued", "running", "starting"):
                task.status = "cancelled"
                task.error_message = "Отменено пользователем"
                task.finished_at = datetime.now(timezone.utc)
                await db.commit()
                logger.info("cancel_applied_to_db", task_id=task_id)
            else:
                logger.info("cancel_db_already_terminal", task_id=task_id)
    except Exception as e:
        await db.rollback()
        logger.warning("cancel_db_apply_failed", task_id=task_id, error=str(e))

    # Clean up pending queue
    _pending_db_cancels.discard(task_id)

    # E097: Await cancelled task for graceful cleanup
    if bg_task_to_await and not bg_task_to_await.done():
        try:
            from app.services.transcription_progress import _await_cancelled_task
            await _await_cancelled_task(bg_task_to_await)
        except Exception:
            pass

    return {"task_id": task_id, "status": "cancelled", "message": "Транскрипция отменена"}


@router.get("/transcribe/health", summary="Transcription service health")
async def transcribe_health() -> dict:
    """Model availability check."""
    return {
        "status": "ok",
        "active_tasks": len(transcription_service._tasks),  # noqa: SLF001
    }


# ---------------------------------------------------------------------------
# GET /transcribe/progress/{task_id}
# ---------------------------------------------------------------------------


@router.get("/transcribe/progress/{task_id}", summary="Get progress by task_id")
async def get_transcription_progress(
    task_id: str, db: AsyncSession = Depends(get_db)
) -> dict:
    """Get transcription progress by task_id."""
    # ... uses transcription_service.get_status(task_id) which reads from _tasks
    try:
        status_obj = transcription_service.get_status(task_id)
        if status_obj is not None:
            return _serialize_task_status(task_id, status_obj)
    except (ValueError, Exception):
        pass

    # Not found in _tasks — try DB
    try:
        from app.db.models import TranscriptionTask as _TT
        task = await db.get(_TT, task_id)
        if task:
            return {
                "id": str(task.id),
                "task_id": str(task.id),
                "protocol_id": str(task.protocol_id),
                "status": task.status,
                "progress": task.progress or 0,
                "message": task.error_message or f"Транскрипция: {task.status}",
                "segments_count": task.current_chunk or 0,
            }
    except Exception:
        pass

    # Not found
    return {
        "task_id": task_id,
        "status": "unknown",
        "progress": 0,
        "message": "Задача не найдена или сервер был перезапущен",
    }


def _serialize_task_status(task_id, status_obj) -> dict:
    """Serialize TranscriptionStatus to dict for JSON response."""
    try:
        return {
            "id": str(status_obj.id),
            "task_id": str(status_obj.id),
            "protocol_id": str(status_obj.protocol_id),
            "status": status_obj.status,
            "progress": status_obj.progress_percent,
            "message": status_obj.message or status_obj.error_message or f"Транскрипция: {status_obj.status}",
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


# ---------------------------------------------------------------------------
# GET /transcribe/progress-by-protocol/{protocol_id}
# ---------------------------------------------------------------------------


@router.get(
    "/transcribe/progress-by-protocol/{protocol_id}",
    summary="Get transcription progress by protocol",
)
async def get_transcription_progress_by_protocol(
    protocol_id: uuid.UUID, db: AsyncSession = Depends(get_db)
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
            "id": None, "task_id": None,
            "protocol_id": str(protocol_id),
            "status": "error",
            "progress": 0,
            "message": f"Ошибка получения прогресса: {str(e)[:200]}",
        }


async def _get_progress_internal(
    protocol_id: uuid.UUID, db: AsyncSession,
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
                            logger.info("pending_cancel_applied", task_id=tid_str)
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
            "id": None, "task_id": None,
            "protocol_id": str(protocol_id),
            "status": "unknown", "progress": 0,
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
            "id": None, "task_id": None,
            "protocol_id": str(protocol_id),
            "status": "unknown", "progress": 0,
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
        is_alive_in_registry = _is_task_alive(task_id_str)

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
            elif age_sec > 1200 and (task.progress or 0) < 0.1:
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
            "message": task.error_message or f"Транскрипция: {task.status}",
            "segments_count": task.current_chunk or 0,
            "started_at": task.started_at.isoformat() if task.started_at else None,
        }

    # No active task - reset stuck protocol if needed
    if protocol.status == "transcribing":
        try:
            protocol.status = "idle"
            await db.commit()
            logger.info("stuck_protocol_reset_to_idle", protocol_id=str(protocol_id))
        except Exception as reset_err:
            await db.rollback()
            logger.warning(
                "stuck_protocol_reset_failed",
                protocol_id=str(protocol_id), error=str(reset_err),
            )
        return {
            "id": None, "task_id": None,
            "protocol_id": str(protocol_id),
            "status": "unknown", "progress": 0,
            "message": "Предыдущая транскрипция была прервана (зависла). Можно запустить заново.",
        }

    # E090: Fallback — progress всегда 0 для неактивных
    return {
        "id": None, "task_id": None,
        "protocol_id": str(protocol_id),
        "status": protocol.status if protocol.status else "idle",
        "progress": 0,
        "message": f"Статус: {protocol.status or 'idle'}",
    }


# ---------------------------------------------------------------------------
# Lightweight in-memory status placeholder
# ---------------------------------------------------------------------------


class _DummyStatus:
    """Stand-in status object when the service has not yet started the job.

    The service may store either ``TranscriptionStatus`` ORM rows (when the
    model is wired up) or simple objects with the same attributes. This class
    keeps the contract stable.
    """

    __slots__ = (
        "id",
        "protocol_id",
        "status",
        "progress_percent",
        "current_chunk",
        "total_chunks",
        "peak_rss_mb",
        "estimated_completion",
        "error_message",
        "wer_quality",
        "message",  # E113: human-readable status for UI
    )

    def __init__(
        self,
        id: uuid.UUID,
        protocol_id: uuid.UUID,
        status: str,
        progress_percent: int,
        current_chunk: int | None = None,
        total_chunks: int | None = None,
        peak_rss_mb: float | None = None,
        estimated_completion: datetime | None = None,
        error_message: str | None = None,
        wer_quality: float | None = None,
        message: str | None = None,  # E113
    ) -> None:
        self.id = id
        self.protocol_id = protocol_id
        self.status = status
        self.progress_percent = progress_percent
        self.current_chunk = current_chunk
        self.total_chunks = total_chunks
        self.peak_rss_mb = peak_rss_mb
        self.estimated_completion = estimated_completion
        self.error_message = error_message
        self.wer_quality = wer_quality
        self.message = message
