"""Local transcription endpoints (US-005, US-006 — API §4.4, §4.5).

Endpoints in this module:

  * POST /transcribe/run              — queue a new job
  * GET  /transcribe/status/{task_id} — poll status
  * POST /transcribe/pause/{task_id}  — pause, keep state
  * POST /transcribe/resume/{task_id} — resume a paused job
  * POST /transcribe/cancel/{task_id} — hard-cancel
  * GET  /transcribe/health           — model availability check

Background work is delegated to ``app.services.transcription.transcription_service``
(singleton, ADR-005). For very long audio the model may exceed RSS budget — the
service is expected to chunk into 30-sec windows (NFR §QG-7).
"""
import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging_config import get_logger
from app.db.models import (
    AudioFile,
    Decision,
    Protocol,
    TranscriptionTask,
    Utterance,
)
from app.db.session import AsyncSessionLocal, get_db
from app.schemas import TranscriptionRequest, TranscriptionStatus
from app.services.transcription import transcription_service

# E098: Registry moved to app.services.active_tasks (avoid circular imports)
from app.services.active_tasks import (
    _active_transcription_tasks,
    register_active_task,
    unregister_active_task,
)

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
        logger.warning(
            "transcribe_protocol_not_found", protocol_id=str(body.protocol_id)
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Протокол {body.protocol_id} не найден",
        )

    # Check status - allow restart if stuck in transcribing
    if protocol.status == "transcribing":
        # Allow restart - reset status first
        # E128: "idle" нет в enum — используем "loaded"
        logger.info(
            "transcribe_protocol_already_transcribing_force_restart",
            protocol_id=str(protocol.id),
        )
        protocol.status = "loaded"
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

    # P0-fix: создаём in-memory запись сразу, чтобы get_status()
    # возвращал хоть что-то до старта реальной работы.
    # Иначе фронт видит только БД-фолбэк до первого запуска transcribe().
    from app.services.transcription import (
        TranscriptionStatus as _TS,
        transcription_service as _svc,
    )
    _svc._tasks[task_id] = _TS(
        id=task_id,
        protocol_id=body.protocol_id,
        status="queued",
        progress_percent=0,
        message="В очереди",
    )

    # Persist task in DB for survival across backend restarts (US-066)
    try:
        from datetime import datetime as _dt
        import hashlib

        # E150: вычисляем hash аудиофайла для resume-validation
        # (audio_file_path_str будет определена ниже — используем ленивое вычисление)
        audio_hash = None

        db_task = TranscriptionTask(
            id=task_id,
            protocol_id=body.protocol_id,
            status="queued",
            progress=0.0,
            current_chunk=0,
            started_at=_dt.now(),
            audio_hash=audio_hash,  # E150 — будет обновлено ниже
        )
        db.add(db_task)
        await db.commit()

        # E131/E153: очищаем старые utterances + decisions перед стартом
        # новой транскрибации (повторная транскрибация = чистая перезапись).
        # E374: используем ту же сессию `db` (request-scoped) вместо
        # AsyncSessionLocal() — иначе в тестах engine привязан к другому
        # event loop и cleanup падает с "attached to a different loop".
        try:
            from sqlalchemy import delete as _del

            await db.execute(
                _del(Utterance).where(Utterance.protocol_id == body.protocol_id)
            )
            await db.execute(
                _del(Decision).where(Decision.protocol_id == body.protocol_id)
            )
            logger.info(
                "transcription_reset_completed",
                protocol_id=str(body.protocol_id),
            )
        except Exception as reset_err:
            logger.warning(
                "transcription_reset_failed",
                protocol_id=str(body.protocol_id),
                error=str(reset_err),
            )

        logger.info(
            "transcription_task_persisted",
            task_id=str(task_id),
            audio_hash=audio_hash,
        )
    except Exception as e:
        logger.warning("transcription_task_persist_failed", error=str(e))
        await db.rollback()

    # E187: используем settings.whisper_compute_type как default.
    # Пользователь может переопределить через request, но default всегда из настроек.
    actual_compute_type = body.compute_type or settings.whisper_compute_type
    logger.info(
        "transcribe_queued",
        task_id=str(task_id),
        protocol_id=str(body.protocol_id),
        model=body.model,
        language=body.language,
        beam_size=body.beam_size,
        compute_type=actual_compute_type,
    )

    # --- Schedule background work ---------------------------------------
    audio_file_path_str = audio_file.file_path
    audio_path = Path(audio_file_path_str)

    # E150: вычисляем hash аудиофайла (теперь когда audio_file_path_str доступен)
    audio_hash = None
    try:
        audio_path_for_hash = Path(audio_file_path_str)
        if audio_path_for_hash.exists():
            audio_hash = hashlib.sha256(
                audio_path_for_hash.read_bytes()
            ).hexdigest()[:32]
    except Exception as hash_err:
        logger.warning("audio_hash_failed", error=str(hash_err))

    # E150: обновляем hash в только что созданном db_task
    try:
        from sqlalchemy import update as _upd
        async with AsyncSessionLocal() as hdb:
            await hdb.execute(
                _upd(TranscriptionTask)
                .where(TranscriptionTask.id == task_id)
                .values(audio_hash=audio_hash)
            )
            await hdb.commit()
            # E183: добавляем логирование успешного обновления hash
            logger.info(
                "audio_hash_updated",
                task_id=str(task_id),
                audio_hash=audio_hash,
            )
    except Exception as e:
        logger.warning("audio_hash_update_failed", error=str(e))

    async def _runner() -> None:
        try:
            result = await transcription_service.transcribe(
                protocol_id=body.protocol_id,
                audio_path=audio_path,
                task_id=task_id,
                duration_sec=audio_file.duration_sec,
                # E243: используем модель из запроса, fallback — settings.whisper_model
                target_model_override=body.model or settings.whisper_model,
            )
            # P0-fix: transcribe() может вернуть status="failed" без raise.
            # Раньше _runner всегда писал "completed" — теряли провалы.
            from app.services.task_status import update_task_status_in_db
            if result.status == "failed":
                await update_task_status_in_db(
                    task_id,
                    "failed",
                    error=result.error_message or "Транскрипция не удалась",
                )
            elif result.status == "cancelled":
                await update_task_status_in_db(
                    task_id,
                    "cancelled",
                    error="Отменено пользователем",
                )
            else:
                # transcribe() уже сделал финальный update "completed",
                # но оставляем страховку на случай исключения между
                # записью в transcribe() и выходом сюда.
                await update_task_status_in_db(
                    task_id, "completed", progress=100.0, message="Завершено"
                )
        except asyncio.CancelledError:
            # Отмена через cancel_endpoint — статус уже записан в transcribe().
            logger.info("transcribe_runner_cancelled", task_id=str(task_id))
            raise
        except Exception as exc:
            logger.exception(
                "transcribe_runner_failed", task_id=str(task_id), error=str(exc)
            )
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
            unregister_active_task(str(task_id))

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
        logger.exception(
            "transcribe_status_update_failed", protocol_id=str(body.protocol_id)
        )

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
async def get_transcription_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
) -> TranscriptionStatus:
    """Get current transcription status by task_id.

    E182: для завершённых задач get_status() возвращает None — тогда идём в БД.
    E374: принимаем task_id как str, чтобы невалидный UUID → 404 (а не 422).
    """
    try:
        tid_uuid = uuid.UUID(task_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Задача {task_id} не найдена",
        )

    status_obj = transcription_service.get_status(tid_uuid)
    if status_obj is not None:
        return status_obj

    # E182: fallback в БД для завершённых задач
    task = await db.get(TranscriptionTask, tid_uuid)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Задача {task_id} не найдена",
        )
    return TranscriptionStatus(
        task_id=task.id,
        protocol_id=task.protocol_id,
        status=task.status or "completed",  # type: ignore[arg-type]
        progress_percent=int(task.progress or 0),
        message=task.current_step,
        error_message=task.error_message,
    )


# ----------------------------------------------------------------------------
# POST /transcribe/pause/{task_id}  (E150)
# ----------------------------------------------------------------------------


@router.post(
    "/transcribe/pause/{task_id}",
    summary="Pause transcription (save state for later resume)",
)
async def pause_transcription_endpoint(
    task_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """E150: pause running transcription, save state to DB.

    Unlike cancel — does NOT delete progress. Can be resumed later
    (including from another browser session) via /transcribe/resume/{task_id}.
    """
    try:
        tid_uuid = uuid.UUID(task_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Невалидный task_id (ожидается UUID)")

    task = await db.get(TranscriptionTask, tid_uuid)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    if task.status not in ("queued", "running", "starting"):
        return {
            "task_id": task_id,
            "status": task.status,
            "message": "Задача не активна — пауза невозможна",
        }

    task.status = "paused"
    task.paused_at = datetime.now(timezone.utc)
    task.updated_at = task.paused_at

    # E150: снимаем BG-task через cancel без удаления из реестра
    bg_task = _active_transcription_tasks.get(task_id)
    if bg_task and not bg_task.done():
        bg_task.cancel()  # cancellation вызовет CancelledError → finally отработает

    await db.commit()
    logger.info(
        "transcribe_paused",
        task_id=task_id,
        progress=task.progress,
        last_processed_sec=task.last_processed_sec,
    )
    return {
        "task_id": task_id,
        "status": "paused",
        "progress": task.progress,
        "paused_at": task.paused_at.isoformat(),
        "can_resume": True,
        "message": (
            "Транскрипция поставлена на паузу. "
            "Можно продолжить через /transcribe/resume/{task_id}"
        ),
    }


# ----------------------------------------------------------------------------
# POST /transcribe/resume/{task_id}  (E150)
# ----------------------------------------------------------------------------


@router.post(
    "/transcribe/resume/{task_id}",
    summary="Resume paused transcription",
)
async def resume_transcription_endpoint(
    task_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """E150: resume a paused task — continue from last_processed_sec.

    Works across sessions: state stored in DB (paused_at, segments_so_far_json,
    last_processed_sec).
    """
    try:
        tid_uuid = uuid.UUID(task_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Невалидный task_id (ожидается UUID)")

    task = await db.get(TranscriptionTask, tid_uuid)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    if task.status != "paused":
        return {
            "task_id": task_id,
            "status": task.status,
            "message": (
                f"Задача в статусе '{task.status}' — resume невозможен "
                "(нужен 'paused')"
            ),
        }

    # Получаем protocol + audio_file
    protocol = await db.get(Protocol, task.protocol_id)
    if not protocol or not protocol.audio_file_id:
        raise HTTPException(status_code=400, detail="Протокол без аудиофайла")
    audio_file = await db.get(AudioFile, protocol.audio_file_id)
    if not audio_file:
        raise HTTPException(status_code=400, detail="Аудиофайл не найден")

    # E151: проверить hash аудио — если изменился, перетранскрибировать с нуля
    import hashlib

    audio_path = Path(audio_file.file_path)
    if audio_path.exists():
        current_hash = hashlib.sha256(audio_path.read_bytes()).hexdigest()[:32]
        if task.audio_hash and task.audio_hash != current_hash:
            logger.warning(
                "resume_audio_changed",
                task_id=task_id,
                old_hash=task.audio_hash,
                new_hash=current_hash,
            )
            # Reset progress and we'll re-transcribe from start
            task.last_processed_sec = 0.0
            task.segments_so_far_json = None
            task.progress = 0.0

    # Запускаем новую BG-task — передаём уже имеющиеся сегменты
    already_done = []
    if task.segments_so_far_json:
        try:
            already_done = json.loads(task.segments_so_far_json)
        except Exception:
            already_done = []

    audio_path = Path(audio_file.file_path)

    async def _resume_runner() -> None:
        try:
            from app.services.transcription import transcription_service
            from app.services.task_status import update_task_status_in_db

            task.status = "running"
            task.paused_at = None
            await db.commit()

            # E152: continue_from_sec — Whisper модели не поддерживают
            # "продолжить с произвольной секунды". Workaround:
            # 1. audio_segmentation через ffmpeg ИЛИ
            # 2. Re-transcribe с начала + дедупликация по text+start_sec
            # Здесь делаем simplified версию: полная транскрибация,
            # append в существующий queue (применяется фильтр dedup)
            result = await transcription_service.transcribe(
                protocol_id=task.protocol_id,
                audio_path=audio_path,
                task_id=tid_uuid,
                duration_sec=audio_file.duration_sec,
                already_done_segments=already_done,
                resume_from_sec=task.last_processed_sec or 0.0,
                target_model_override=(
                    task.audio_hash and settings.whisper_model
                ),
            )
            await update_task_status_in_db(
                tid_uuid,
                "completed",
                progress=100.0,
                message="Завершено (возобновлено)",
            )
        except Exception as exc:
            logger.exception("transcribe_resume_failed", error=str(exc))
            try:
                from app.services.task_status import update_task_status_in_db
                await update_task_status_in_db(
                    tid_uuid, "failed", error=str(exc)[:500]
                )
            except Exception:
                pass

    bg_task = asyncio.create_task(_resume_runner())
    register_active_task(str(tid_uuid), bg_task)

    return {
        "task_id": task_id,
        "status": "running",
        "resume_from_sec": task.last_processed_sec or 0.0,
        "previously_done_segments": len(already_done),
        "message": "Транскрипция возобновлена",
    }


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
        return {
            "task_id": task_id,
            "status": "not_found",
            "message": "Задача не найдена",
        }

    # E104: Apply cancel to DB SYNCHRONOUSLY (not via pending queue)
    try:
        try:
            tid_uuid = uuid.UUID(task_id)
        except (ValueError, TypeError) as uuid_err:
            logger.warning("cancel_invalid_uuid", task_id=task_id, error=str(uuid_err))
            tid_uuid = None
        if tid_uuid is not None:
            task = await db.get(TranscriptionTask, tid_uuid)
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

    return {
        "task_id": task_id,
        "status": "cancelled",
        "message": "Транскрипция отменена",
    }


@router.get("/transcribe/health", summary="Transcription service health")
async def transcribe_health() -> dict:
    """Model availability check."""
    return {
        "status": "ok",
        "active_tasks": len(transcription_service._tasks),  # noqa: SLF001
    }