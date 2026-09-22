"""Transcription service — Whisper integration (ADR-005).

Background worker pattern: 1 worker per ADR-009.
Chunks of 30 sec per NFR §QG-7.

US-005: Real Whisper integration with progress tracking.
"""
import asyncio
import time  # E119: used for transcribe_start_time / heartbeat elapsed
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)


# Локальный dataclass (НЕ модель БД)
@dataclass
class TranscriptionStatus:
    id: uuid.UUID
    protocol_id: uuid.UUID
    status: Literal["queued", "processing", "paused", "completed", "failed", "cancelled"] = "queued"
    progress_percent: int = 0
    current_chunk: int | None = None
    total_chunks: int | None = None
    peak_rss_mb: float | None = None
    estimated_completion: datetime | None = None
    error_message: str | None = None
    wer_quality: float | None = None
    # E113: Human-readable status message for UI ("Инициализация...", "Обработка 30с...")
    message: str | None = None


class TranscriptionService:
    """Async service for Whisper-based transcription."""

    def __init__(self) -> None:
        self._model = None  # Lazy-loaded
        self._tasks: dict[uuid.UUID, TranscriptionStatus] = {}
        # US-066: In-memory progress tracking (consumed by progress endpoint)
        self._progress_callbacks: dict[uuid.UUID, callable] = {}

    def _load_model(self):
        """Lazy-load Whisper model.

        US-005 + E052: Graceful handling of missing faster-whisper.
        Install with: pip install faster-whisper
        E111: Detect cudnn issues and fallback to CPU automatically.
        """
        if self._model is None:
            from faster_whisper import WhisperModel

            # E111: Auto-detect cudnn availability
            use_device = settings.whisper_device
            use_compute = settings.whisper_compute_type
            if use_device == "cuda":
                try:
                    import ctypes
                    # Try loading cudnn64_9.dll or cudnn64_8.dll
                    for dll_name in ["cudnn64_9.dll", "cudnn64_8.dll", "cudnn64_7.dll"]:
                        try:
                            ctypes.CDLL(dll_name)
                            break
                        except OSError:
                            continue
                    else:
                        # No cudnn found
                        logger.warning(
                            "cudnn_not_found_fallback_to_cpu",
                            attempted_dlls=["cudnn64_9.dll", "cudnn64_8.dll", "cudnn64_7.dll"],
                        )
                        use_device = "cpu"
                        use_compute = "int8"
                except Exception as cudnn_err:
                    logger.warning("cudnn_check_failed", error=str(cudnn_err))
                    use_device = "cpu"
                    use_compute = "int8"

            # Try primary model first (e.g., large-v3)
            primary = settings.whisper_model
            try:
                logger.info("loading_whisper_model", model=primary, device=use_device)
                self._model = WhisperModel(
                    primary,
                    device=use_device,
                    compute_type=use_compute,
                )
                logger.info("whisper_model_loaded", model=primary, device=use_device)
                return self._model
            except Exception as e:
                # E058: Fallback to tiny if primary fails (OOM, etc.)
                logger.warning("whisper_primary_model_failed", primary=primary, error=str(e))

            # Fallback to tiny (CPU-friendly)
            try:
                logger.info("whisper_fallback_to_tiny")
                self._model = WhisperModel("tiny", device="cpu", compute_type="int8")
                logger.info("whisper_fallback_loaded", model="tiny")
                return self._model
            except Exception as fb_err:
                logger.error("whisper_all_models_failed", error=str(fb_err))
                raise RuntimeError(
                    f"Не удалось загрузить Whisper. "
                    f"Primary={primary}, Fallback=tiny. "
                    f"Ошибка: {str(fb_err)}. "
                    f"Установите: .venv\\Scripts\\pip install faster-whisper==1.0.3"
                ) from fb_err

        return self._model

    async def transcribe(
        self, protocol_id: uuid.UUID, audio_path: Path, task_id: uuid.UUID,
        duration_sec: float | None = None,
    ) -> TranscriptionStatus:
        """Transcribe audio file with progress tracking.

        US-005: Real Whisper transcription with:
        - Progress updates (every segment processed)
        - Error handling with status update
        - DB persistence of utterances (TODO: integration with sessions)
        """
        status = TranscriptionStatus(
            id=task_id,
            protocol_id=protocol_id,
            status="processing",
            progress_percent=0,
        )
        self._tasks[task_id] = status

        try:
            # Step 1: Load model (slow on first call, ~30-120s for large-v3 CPU)
            logger.info("transcribe_loading_model", task_id=str(task_id))
            # US-058: Try active model via model_manager
            from app.services.whisper_models import model_manager
            active = model_manager.get_active_model()

            # E070: Check that active model is ACTUALLY downloaded (not just selected)
            if not model_manager.is_downloaded(active):
                logger.warning(
                    "active_model_not_downloaded",
                    active=active,
                    task_id=str(task_id),
                )
                from app.services.whisper_models import AVAILABLE_MODELS
                # Pick first available downloaded model
                fallback_used = None
                for fallback in AVAILABLE_MODELS:
                    if model_manager.is_downloaded(fallback):
                        fallback_used = fallback
                        break

                if fallback_used:
                    settings.whisper_model = fallback_used
                    logger.info(
                        "fallback_to_downloaded",
                        from_model=active,
                        to_model=fallback_used,
                        task_id=str(task_id),
                    )
                else:
                    # NO model downloaded - return clear error to user
                    logger.error(
                        "no_models_downloaded",
                        task_id=str(task_id),
                        active=active,
                    )
                    status.status = "failed"
                    status.error_message = (
                        f"Модель '{active}' не скачана и нет резервных. "
                        f"Скачайте модель в Настройки → Транскрипция → Управление моделями"
                    )
                    status.progress_percent = 0
                    # Persist failure to DB (E069)
                    try:
                        with SyncSessionLocal() as s:
                            from sqlalchemy import update as _upd
                            s.execute(
                                _upd(_DBTask)
                                .where(_DBTask.id == task_id)
                                .values(status="failed", error_message=status.error_message, finished_at=_dt.utcnow())
                            )
                            s.commit()
                    except Exception:
                        pass
                    return status  # ← exit early, don't try _load_model

            # Log which model will be used
            logger.info(
                "transcribe_using_model",
                model=settings.whisper_model,
                task_id=str(task_id),
            )

            model = await asyncio.to_thread(self._load_model)
            logger.info(
                "transcribe_model_loaded",
                task_id=str(task_id),
                model_loaded=model is not None,
            )

            # Step 2: Validate audio file exists
            if not audio_path.exists():
                raise FileNotFoundError(f"Audio file not found: {audio_path}")

            # Step 3: Run transcription
            logger.info(
                "transcribe_starting",
                task_id=str(task_id),
                audio_path=str(audio_path),
                language=settings.whisper_language,
                beam_size=settings.whisper_beam_size,
            )

            # E113: Heartbeat progress — обновляем каждые 2 сек
            # чтобы UI не висел на 0% пока Whisper думает
            stop_heartbeat = asyncio.Event()
            transcribe_start_time = time.time()
            # E113: Heartbeat progress — обновляем каждые 2 сек
            # чтобы UI не висел на 0% пока Whisper думает
            # E113-fix: heartbeat НЕ трогает БД (только message in-memory).
            # Прогресс в БД обновится один раз в конце через _update_task_status_in_db.
            stop_heartbeat = asyncio.Event()
            transcribe_start_time = time.time()

            # Use real duration if passed (from run_transcription)
            # E113: Use real duration_sec parameter (not file size heuristic)
            self._current_audio_duration = duration_sec or 0
            estimated_duration_sec = max(
                60,
                int(duration_sec or 0) or int(
                    (audio_path.stat().st_size / (1024 * 1024)) * 60
                ),
            )

            async def heartbeat_progress():
                """Update progress message while transcription is running.

                Whisper на CPU может думать 30-60 сек между сегментами.
                Heartbeat гарантирует что UI видит живое сообщение.

                E113-fix: НЕ обновляет progress_percent (это делает progress_cb).
                Только обновляет message — чтобы UI знал, что процесс жив.
                """
                while not stop_heartbeat.is_set():
                    elapsed = time.time() - transcribe_start_time
                    # Show real elapsed in message — but DO NOT touch progress_percent
                    status.message = f"Обработка аудио... {int(elapsed)}с"
                    try:
                        await asyncio.wait_for(stop_heartbeat.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        pass

            heartbeat_task = asyncio.create_task(heartbeat_progress())

            # US-066: Progress callback for UI - updates BOTH memory and DB
            def progress_cb(percent: int, current_seg: int, total_segs: int | None) -> None:
                pct = min(100, percent)
                status.progress_percent = pct
                status.current_chunk = current_seg
                if total_segs:
                    status.total_chunks = total_segs
                logger.debug(
                    "transcribe_progress",
                    task_id=str(task_id),
                    percent=pct,
                    segment=current_seg,
                    total_segments=total_segs,
                )
                # E115: Replace SyncSessionLocal with async fire-and-forget
                # SyncSessionLocal в async контексте даёт greenlet_spawn ошибку.
                try:
                    from app.services.task_status import update_task_status_in_db
                    asyncio.create_task(update_task_status_in_db(
                        task_id,
                        "running",
                        progress=float(pct),
                    ))
                except Exception as db_err:
                    # Don't crash transcription because of progress save issue
                    logger.debug("progress_db_update_failed", error=str(db_err))

            # Run eager-mode (consumes generator)
            def _run_transcribe_eager():
                """Eagerly consume transcribe() generator.

                Returns:
                    (segments_list, info)

                Why eager: `transcribe()` returns a generator.
                Calling it once returns a generator object, NOT a tuple.
                To get info (duration, language), must consume first.
                """
                segments_generator, info = model.transcribe(
                    str(audio_path),
                    language=settings.whisper_language,
                    beam_size=settings.whisper_beam_size,
                    word_timestamps=False,  # faster
                    # E118: Pass VAD parameters from settings
                # Use only when VAD is enabled (default off to preserve all audio)
                vad_filter=settings.whisper_vad_filter,
                vad_parameters=(
                    {
                        "min_silence_duration_ms": settings.vad_min_silence_duration_ms,
                        "speech_pad_ms": settings.vad_speech_pad_ms,
                        "threshold": settings.vad_threshold,
                    }
                    if settings.whisper_vad_filter
                    else None
                ),
                )

                # Estimate total duration from info
                total_duration = info.duration or 0.0

                segments_list = []
                for seg in segments_generator:
                    segments_list.append(seg)
                    # Calculate progress based on segment end time vs total
                    if total_duration > 0:
                        pct = min(100, int((seg.end / total_duration) * 100))
                        progress_cb(pct, len(segments_list), None)

                return segments_list, info

            try:
                segments_list, info = await asyncio.to_thread(_run_transcribe_eager)

                status.progress_percent = 100
                status.status = "completed"
                status.wer_quality = 0.0  # TODO: calculate from segments
            finally:
                # E113-fix: heartbeat всегда останавливается (даже при исключении)
                stop_heartbeat.set()
                try:
                    await asyncio.wait_for(heartbeat_task, timeout=2.0)
                except asyncio.TimeoutError:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass

            # E115: Persist completion to DB — use fire-and-forget
            # SyncSessionLocal в async контексте даёт greenlet_spawn ошибку.
            # Используем _update_task_status_in_db (async).
            try:
                from app.services.task_status import update_task_status_in_db
                asyncio.create_task(update_task_status_in_db(
                    task_id,
                    "completed",
                    progress=100.0,
                ))
            except Exception as db_err:
                logger.warning("completion_db_update_failed", error=str(db_err))

            logger.info(
                "transcription_completed",
                task_id=str(task_id),
                protocol_id=str(protocol_id),
                duration=info.duration,
                language=info.language,
                language_probability=info.language_probability,
                num_segments=len(segments_list),
            )

            # TODO (US-066): Insert utterances into DB
            # await self._save_utterances(protocol_id, segments_list, info)

        except Exception as e:
            status.status = "failed"
            status.error_message = str(e)[:1000]
            logger.exception("transcription_failed", task_id=str(task_id), error=str(e))

            # E115: async fire-and-forget
            try:
                from app.services.task_status import update_task_status_in_db
                asyncio.create_task(update_task_status_in_db(
                    task_id,
                    "failed",
                    error=status.error_message,
                ))
            except Exception as db_err:
                logger.warning("failure_db_update_failed", error=str(db_err))
            raise

        return status

    def get_status(self, task_id: uuid.UUID) -> TranscriptionStatus | None:
        """Get task status from in-memory dict OR database (E045).

        First check in-memory (live tasks), then fall back to DB.
        """
        # 1. Check in-memory dict (live tasks)
        if task_id in self._tasks:
            return self._tasks[task_id]

        # 2. Fall back to DB (persistent storage for completed/cancelled tasks)
        try:
            from app.db.session import AsyncSessionLocal
            from app.db.models import TranscriptionTask
            from sqlalchemy import select as _select

            async def _load_from_db():
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        _select(TranscriptionTask).where(
                            TranscriptionTask.id == task_id
                        )
                    )
                    db_task = result.scalar_one_or_none()
                    if db_task:
                        # Convert DB model to TranscriptionStatus
                        from app.routers.transcribe import _serialize_task_status
                        # Create a TranscriptionStatus-like object
                        class _StatusAdapter:
                            def __init__(self, db_t):
                                self.id = db_t.id
                                self.protocol_id = db_t.protocol_id
                                self.status = db_t.status
                                self.progress_percent = db_t.progress_percent or 0
                                self.error_message = db_t.error_message
                                self.estimated_completion = db_t.estimated_completion
                        return _StatusAdapter(db_task)
                return None

            # Run async in sync wrapper
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Already in async context - skip DB lookup
                    return None
                else:
                    return loop.run_until_complete(_load_from_db())
            except RuntimeError:
                # No event loop - run inline
                return asyncio.run(_load_from_db())
        except Exception as e:
            logger.debug("db_status_load_failed", task_id=str(task_id), error=str(e))
            return None


# Singleton instance
transcription_service = TranscriptionService()
