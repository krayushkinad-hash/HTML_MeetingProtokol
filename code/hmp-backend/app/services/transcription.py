"""Transcription service — Whisper integration (ADR-005).

Background worker pattern: 1 worker per ADR-009.
Chunks of 30 sec per NFR §QG-7.

US-005: Real Whisper integration with progress tracking.
"""
import asyncio
import os  # E164: для сброса proxy env при загрузке модели
import queue  # E131: для потоковой записи utterance из worker thread
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app.core.config import settings
from app.core.logging_config import get_logger

# E168: модульный импорт для использования во всех функциях
from app.db.session import AsyncSessionLocal
# E240: Utterance используется в transcribe() и _persist_utterances_loop
from app.db.models import Utterance

logger = get_logger(__name__)


# Локальный dataclass (НЕ модель БД)
@dataclass
class TranscriptionStatus:
    """E197: Literal синхронизирован с Pydantic-схемой (добавлены running/starting)."""
    id: uuid.UUID
    protocol_id: uuid.UUID
    status: Literal[
        "queued", "processing", "running", "starting",
        "paused", "completed", "failed", "cancelled",
    ] = "queued"
    progress_percent: int = 0
    current_chunk: int | None = None
    total_chunks: int | None = None
    peak_rss_mb: float | None = None
    estimated_completion: datetime | None = None
    error_message: str | None = None
    wer_quality: float | None = None
    message: str | None = None


class TranscriptionService:
    """Async service for Whisper-based transcription."""

    def __init__(self) -> None:
        self._model = None  # Lazy-loaded
        self._tasks: dict[uuid.UUID, TranscriptionStatus] = {}
        self._progress_callbacks: dict[uuid.UUID, callable] = {}
        # E131: thread-safe очередь для потоковой записи utterance
        # worker thread пишет, persist loop в main event loop читает
        self._utterance_queue: queue.Queue = queue.Queue()

    def _load_model(self):
        """Lazy-load Whisper model.

        E052: Graceful handling of missing faster-whisper.
        E111: Detect cudnn issues and fallback to CPU automatically.
        E058: Fallback to tiny if primary fails (OOM, etc.).
        E125: set fallback flag so transcribe() can notify user.
        E166: Aggressively remove ALL proxy env vars BEFORE downloading
              (huggingface_hub reads them at snapshot_download time,
              not at import time — that's why removing them temporarily
              around `from faster_whisper import WhisperModel` is not enough).
        """
        if self._model is None:
            # E166: remove proxy env vars permanently for this process.
            # We are a local app on 127.0.0.1 — proxies are never needed.
            _proxy_keys = (
                "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SOCKS_PROXY",
                "http_proxy", "https_proxy", "all_proxy", "socks_proxy",
            )
            for _k in _proxy_keys:
                os.environ.pop(_k, None)
            # Tell requests/httpx/urllib to bypass proxies for everything
            os.environ["NO_PROXY"] = "*"
            os.environ["no_proxy"] = "*"
            # Do not let hf_hub go offline unless user explicitly asked
            os.environ.pop("HF_HUB_OFFLINE", None)

            from faster_whisper import WhisperModel

            use_device = settings.whisper_device
            use_compute = settings.whisper_compute_type

            if use_device == "cuda":
                try:
                    import ctypes
                    for dll_name in ("cudnn64_9.dll", "cudnn64_8.dll", "cudnn64_7.dll"):
                        try:
                            ctypes.CDLL(dll_name)
                            break
                        except OSError:
                            continue
                    else:
                        logger.warning(
                            "cudnn_not_found_fallback_to_cpu",
                            attempted_dlls=[
                                "cudnn64_9.dll", "cudnn64_8.dll", "cudnn64_7.dll",
                            ],
                        )
                        use_device = "cpu"
                        use_compute = "int8"
                except Exception as cudnn_err:
                    logger.warning("cudnn_check_failed", error=str(cudnn_err))
                    use_device = "cpu"
                    use_compute = "int8"

            primary = settings.whisper_model
            if getattr(self, "_target_model_override", None):
                primary = self._target_model_override

            # E244: используем локальный кеш + HF_HUB_DISABLE_TELEMETRY.
            # Без download_root WhisperModel каждое открытие проверяет HF и
            # может перескачивать (особенно после reload uvicorn).
            # local_files_only=True — если файлы уже есть в кеше, не проверяет
            # HuggingFace (гарантированно не скачивает).
            _model_cache = (
                Path.home() / ".cache" / "huggingface" / "hub"
            )
            try:
                _model_cache.mkdir(parents=True, exist_ok=True)
            except Exception:
                _model_cache = None

            try:
                logger.info("loading_whisper_model", model=primary, device=use_device)
                # E187: cpu_threads ускоряет на CPU (1.5x для base/small)
                cpu_threads = getattr(settings, 'whisper_cpu_threads', None)
                _common_kwargs = dict(
                    device=use_device,
                    compute_type=use_compute,
                    local_files_only=True,  # E244: не проверять HF, только кеш
                )
                if _model_cache:
                    _common_kwargs['download_root'] = str(_model_cache)
                if use_device == "cpu" and cpu_threads:
                    self._model = WhisperModel(primary, cpu_threads=cpu_threads, **_common_kwargs)
                else:
                    self._model = WhisperModel(primary, **_common_kwargs)
                logger.info("whisper_model_loaded", model=primary, device=use_device, cpu_threads=cpu_threads)
                self._last_fallback_reason = None
                return self._model
            except Exception as e:
                # E244: если local_files_only=True упал (файлы нет в кеше),
                # пробуем скачать с HuggingFace
                err_str = str(e).lower()
                if 'local_files_only' in err_str or 'not found' in err_str or '404' in err_str:
                    logger.info("local_files_only_failed_falling_back_to_download", model=primary)
                    _common_kwargs.pop('local_files_only', None)
                    try:
                        if use_device == "cpu" and cpu_threads:
                            self._model = WhisperModel(primary, cpu_threads=cpu_threads, **_common_kwargs)
                        else:
                            self._model = WhisperModel(primary, **_common_kwargs)
                        logger.info("whisper_model_loaded_after_download", model=primary)
                        self._last_fallback_reason = None
                        return self._model
                    except Exception as e2:
                        logger.warning("whisper_primary_model_failed_after_download", primary=primary, error=str(e2))
                        # fall through к fallback tiny
                else:
                    logger.warning(
                        "whisper_primary_model_failed", primary=primary, error=str(e),
                    )

            try:
                logger.info("whisper_fallback_to_tiny", requested=primary)
                # E187: cpu_threads для fallback
                _cpu_threads = getattr(settings, 'whisper_cpu_threads', None)
                # E244: тот же путь кеша что и для основной модели
                _tiny_kwargs = dict(
                    device="cpu",
                    compute_type="int8",
                    local_files_only=True,
                )
                if _model_cache:
                    _tiny_kwargs['download_root'] = str(_model_cache)
                if _cpu_threads:
                    self._model = WhisperModel("tiny", cpu_threads=_cpu_threads, **_tiny_kwargs)
                else:
                    self._model = WhisperModel("tiny", **_tiny_kwargs)
                logger.info("whisper_fallback_loaded", model="tiny")
                self._last_fallback_reason = (
                    f"Модель '{primary}' не загрузилась, используется tiny"
                )
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
        self,
        protocol_id: uuid.UUID,
        audio_path: Path,
        task_id: uuid.UUID,
        duration_sec: float | None = None,
        already_done_segments: list | None = None,  # E150: для resume
        resume_from_sec: float | None = None,        # E150: для resume
        target_model_override: str | None = None,    # E162: для upgrade endpoint
        only_update_weak: bool = False,                # E162: обновлять только слабые
    ) -> TranscriptionStatus:
        """Transcribe audio file with progress tracking.

        E150: при resume уже завершённые сегменты могут быть переданы
        в already_done_segments → мы их сразу запишем в БД, без повторной
        обработки Whisper.
        """
        status = TranscriptionStatus(
            id=task_id,
            protocol_id=protocol_id,
            status="processing",
            progress_percent=0,
            message="Инициализация...",
        )
        self._tasks[task_id] = status

        try:
            # Step 1: Load model
            logger.info("transcribe_loading_model", task_id=str(task_id))
            from app.services.whisper_models import model_manager
            active = model_manager.get_active_model()

            # E070: Check that active model is ACTUALLY downloaded
            if not model_manager.is_downloaded(active):
                logger.warning(
                    "active_model_not_downloaded", active=active, task_id=str(task_id),
                )
                from app.services.whisper_models import AVAILABLE_MODELS
                fallback_used = None
                for fallback in AVAILABLE_MODELS:
                    if model_manager.is_downloaded(fallback):
                        fallback_used = fallback
                        break

                if fallback_used:
                    settings.whisper_model = fallback_used
                    logger.info(
                        "fallback_to_downloaded",
                        from_model=active, to_model=fallback_used,
                        task_id=str(task_id),
                    )
                else:
                    logger.error(
                        "no_models_downloaded", task_id=str(task_id), active=active,
                    )
                    status.status = "failed"
                    status.error_message = (
                        f"Модель '{active}' не скачана и нет резервных. "
                        f"Скачайте модель в Настройки → Транскрипция → "
                        f"Управление моделями"
                    )
                    status.progress_percent = 0
                    # P0-fix: было обращение к SyncSessionLocal/_DBTask/_dt,
                    # которых нет в модуле. Заменено на безопасный async-хелпер.
                    try:
                        from app.services.task_status import update_task_status_in_db
                        await update_task_status_in_db(
                            task_id, "failed", error=status.error_message,
                        )
                    except Exception as db_err:
                        logger.warning(
                            "no_models_failed_persist_error", error=str(db_err),
                        )
                    return status

            logger.info(
                "transcribe_using_model",
                model=settings.whisper_model, task_id=str(task_id),
            )

            # E131: очистка очереди от предыдущего запуска
            while not self._utterance_queue.empty():
                try:
                    self._utterance_queue.get_nowait()
                except queue.Empty:
                    break

            # E166: old_utterances_cleared перенесён ПОСЛЕ _load_model
            # чтобы при ошибке загрузки модели данные не терялись.

            # E162: устанавливаем override модель ДО вызова _load_model
            if target_model_override:
                self._target_model_override = target_model_override
                logger.info("using_override_model", model=target_model_override)
            else:
                # E167: явно очищаем override если не передан — иначе
                # может leak между задачами
                self._target_model_override = None

            # E166: СНАЧАЛА загружаем модель. Если не получится — НЕ удалять старые.
            try:
                model = await asyncio.to_thread(self._load_model)
                logger.info(
                    "transcribe_model_loaded",
                    task_id=str(task_id), model_loaded=model is not None,
                )
            finally:
                # E167: очищаем override после загрузки
                self._target_model_override = None

            # E166: Только теперь безопасно удалять старые — модель загружена,
            # транскрибация точно пройдёт. Иначе при ошибке модели теряем данные.
            if not only_update_weak:
                try:
                    from sqlalchemy import delete
                    # E240: используем модульный AsyncSessionLocal и Utterance
                    async with AsyncSessionLocal() as clean_session:
                        await clean_session.execute(
                            delete(Utterance).where(Utterance.protocol_id == protocol_id)
                        )
                        await clean_session.commit()
                    logger.info("old_utterances_cleared_after_model_loaded",
                                protocol_id=str(protocol_id))
                except Exception as clear_err:
                    logger.warning(
                        "old_utterances_clear_failed",
                        protocol_id=str(protocol_id),
                        error=str(clear_err),
                    )
            else:
                logger.info(
                    "upgrade_mode_skip_clear",
                    protocol_id=str(protocol_id),
                    note="only_update_weak=True, will update in place",
                )

            # E125: notify user if we fell back to tiny
            fallback_reason = getattr(self, "_last_fallback_reason", None)
            if fallback_reason:
                status.message = fallback_reason
                self._last_fallback_reason = None

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

            # E113/E121: heartbeat + persist loop share one stop event and
            # one start time. Previously there were three duplicate
            # stop_heartbeat = asyncio.Event() — removed.
            stop_heartbeat = asyncio.Event()
            transcribe_start_time = time.time()
            self._current_audio_duration = duration_sec or 0

            async def heartbeat_progress():
                """Update in-memory message every 2s while Whisper works.

                Does NOT touch progress_percent — that's progress_cb's job.

                E183: fallback — если progress_cb не обновила progress за 30с
                (например, первый сегмент долго), вычисляем приблизительно
                по elapsed time / estimated_total. estimated_total берётся
                из self._current_audio_duration или info.duration.
                """
                # E216: убран nonlocal status — status это dataclass, мутация через
                # attribute (status.message = ...) не требует nonlocal
                while not stop_heartbeat.is_set():
                    elapsed = time.time() - transcribe_start_time
                    status.message = f"Обработка аудио... {int(elapsed)}с"

                    # E199: убран fake progress (estimated_speed = 0.5).
                    # Реальный progress_percent обновляется только в progress_cb
                    # при генерации первого сегмента. До этого — 0% (честно).

                    logger.debug(
                        "heartbeat",
                        task_id=str(task_id),
                        elapsed=int(elapsed),
                        progress=status.progress_percent,
                    )
                    try:
                        await asyncio.wait_for(stop_heartbeat.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        pass

            heartbeat_task = asyncio.create_task(heartbeat_progress())

            async def persist_progress_loop():
                """Persist status.progress_percent + message to DB every 2s.

                Runs from the main event loop (not from a worker thread),
                so asyncio.create_task inside is safe.

                E150: also save last_processed_sec + segments_so_far_json
                for resume (pause/resume — E150).
                """
                from app.services.task_status import update_task_status_in_db
                while not stop_heartbeat.is_set():
                    try:
                        await update_task_status_in_db(
                            task_id,
                            "running",
                            progress=float(status.progress_percent),
                            message=status.message or "",
                        )

                        # E150: параллельно сохраняем state для возможного resume
                        try:
                            from app.db.models import TranscriptionTask as _TT
                            from sqlalchemy import select as _sel
                            # E240: используем модульный Utterance
                            import json as _json
                            async with AsyncSessionLocal() as ps:
                                # Получаем последний сохранённый segment для time-tracking
                                last_seg_q = await ps.execute(
                                    _sel(Utterance).where(Utterance.protocol_id == protocol_id)
                                    .order_by(Utterance.start_sec.desc()).limit(1)
                                )
                                last_seg = last_seg_q.scalar_one_or_none()
                                if last_seg:
                                    t = await ps.get(_TT, task_id)
                                    if t:
                                        # Сохраняем уже сохранённые utterance
                                        segs_q = await ps.execute(
                                            _sel(Utterance.start_sec, Utterance.end_sec, Utterance.text)
                                            .where(Utterance.protocol_id == protocol_id)
                                            .order_by(Utterance.start_sec.asc())
                                        )
                                        segs = segs_q.all()
                                        t.segments_so_far_json = _json.dumps(
                                            [{"start": float(s[0]), "end": float(s[1]), "text": s[2]} for s in segs]
                                        )
                                        t.last_processed_sec = float(last_seg.end_sec)
                                        await ps.commit()
                        except Exception as state_err:
                            logger.debug("resume_state_save_skipped", error=str(state_err))

                        logger.debug(
                            "progress_persisted_to_db",
                            task_id=str(task_id),
                            progress=status.progress_percent,
                            message=status.message,
                        )
                    except Exception as db_err:
                        logger.warning(
                            "progress_persist_failed",
                            task_id=str(task_id),
                            error=str(db_err),
                        )
                    try:
                        await asyncio.wait_for(stop_heartbeat.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        pass

            persist_task = asyncio.create_task(persist_progress_loop())

            # E185: обёртка для utterances_task — если create_task упадёт,
            # гарантированно остановим heartbeat_task и persist_task
            utterances_task = None
            try:
                # E131: потоковая запись utterance — сегменты появляются в БД
                # по мере генерации, не дожидаясь конца транскрибации.
                utterances_task = asyncio.create_task(
                    self._persist_utterances_loop(protocol_id, stop_heartbeat)  # E184: без only_update_weak
                )
            except Exception as task_err:
                logger.error("utterances_task_create_failed", error=str(task_err))
                stop_heartbeat.set()
                # Cancel созданные таски
                for t in (heartbeat_task, persist_task):
                    if t and not t.done():
                        t.cancel()
                raise

            # US-066: Progress callback — in-memory ONLY.
            # E131: worker thread кладёт сегмент в queue.Queue,
            # persist_utterances_loop в main event loop забирает и пишет.
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

            def _run_transcribe_eager():
                """Consume the faster-whisper generator eagerly.

                E131: для каждого сегмента кладём dict в self._utterance_queue
                (thread-safe). persist loop в main event loop забирает и пишет в БД.
                """
                # E190: BatchedInferencePipeline требует VAD для chunked inference.
                # Если batched=True и VAD=False — принудительно включаем VAD с предупреждением.
                effective_vad = settings.whisper_vad_filter
                if settings.whisper_use_batched_pipeline and not effective_vad:
                    logger.warning(
                        "batched_pipeline_vad_forced",
                        note="whisper_use_batched_pipeline=True требует VAD. "
                             "Принудительно включаю whisper_vad_filter=True.",
                    )
                    effective_vad = True

                # E187: chunked transcription для длинных аудио
                # Разбиваем аудио на чанки по chunk_duration_sec (default 30 мин)
                # Это быстрее чем один проход на 1.5-часовом файле + не переполняется память.
                audio_full_path = str(audio_path)

                # E190: используем BatchedInferencePipeline если включено
                use_batched = getattr(settings, 'whisper_use_batched_pipeline', False)
                if use_batched:
                    try:
                        from faster_whisper import BatchedInferencePipeline
                        logger.info("using_batched_pipeline", chunk_duration=chunk_duration)
                        # BatchedInferencePipeline работает по chunks из segments_generator
                        # Возвращает генератор сегментов напрямую
                        segments_generator, info = model.transcribe(
                            audio_full_path,
                            language=settings.whisper_language,
                            beam_size=settings.whisper_beam_size,
                            word_timestamps=False,
                            condition_on_previous_text=False,  # E236: против галлюцинаций
                            vad_filter=effective_vad,
                        )
                    except ImportError:
                        logger.warning("batched_pipeline_unavailable_fallback_eager")
                        segments_generator, info = model.transcribe(
                            audio_full_path,
                            language=settings.whisper_language,
                            beam_size=settings.whisper_beam_size,
                            word_timestamps=False,
                            condition_on_previous_text=False,  # E236: против галлюцинаций
                            vad_filter=effective_vad,
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
                else:
                    segments_generator, info = model.transcribe(
                        audio_full_path,
                        language=settings.whisper_language,
                        beam_size=settings.whisper_beam_size,
                        word_timestamps=False,
                        condition_on_previous_text=False,  # E236: против галлюцинаций
                        vad_filter=effective_vad,
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

                total_duration = info.duration or 0.0
                segments_list = []
                for seg in segments_generator:
                    segments_list.append(seg)
                    # E131: кладём сегмент в очередь для persist loop
                    self._utterance_queue.put({
                        "start": float(seg.start),
                        "end": float(seg.end),
                        "text": seg.text or "",
                        "avg_logprob": getattr(seg, "avg_logprob", None),
                    })
                    if total_duration > 0:
                        pct = min(100, int((seg.end / total_duration) * 100))
                        progress_cb(pct, len(segments_list), None)

                return segments_list, info

            try:
                segments_list, info = await asyncio.to_thread(_run_transcribe_eager)
                status.progress_percent = 100
                status.status = "completed"
                status.wer_quality = 0.0
            finally:
                stop_heartbeat.set()

                try:
                    await asyncio.wait_for(heartbeat_task, timeout=2.0)
                except asyncio.TimeoutError:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass

                try:
                    await asyncio.wait_for(persist_task, timeout=2.0)
                except asyncio.TimeoutError:
                    persist_task.cancel()
                    try:
                        await persist_task
                    except asyncio.CancelledError:
                        pass

                # E132: utterances_task может занять больше времени —
                # внутри финальный flush. Даём ему 15 сек.
                try:
                    await asyncio.wait_for(utterances_task, timeout=15.0)
                except asyncio.TimeoutError:
                    utterances_task.cancel()
                    try:
                        await utterances_task
                    except asyncio.CancelledError:
                        pass

            # E189: _save_utterances убран — _persist_utterances_loop уже записал
            # все utterance в БД потоково. Повторный вызов удалял бы их и перезаписывал.
            if segments_list:
                # Просто проверяем что utterance записаны
                from sqlalchemy import select as _sel, func as _func
                async with AsyncSessionLocal() as chk:
                    cnt_q = await chk.execute(
                        _sel(_func.count(Utterance.id)).where(
                            Utterance.protocol_id == protocol_id
                        )
                    )
                    saved = cnt_q.scalar() or 0
                status.message = f"Сохранено реплик: {saved}"
                logger.info(
                    "utterances_count_final",
                    task_id=str(task_id),
                    count=saved,
                )

                # E130: помечаем протокол как готовый (есть utterance)
                try:
                    from sqlalchemy import update as _upd_proto
                    from app.db.models import Protocol as _Proto

                    async with AsyncSessionLocal() as proto_session:
                        await proto_session.execute(
                            _upd_proto(_Proto)
                            .where(_Proto.id == protocol_id)
                            .values(status="ready")
                        )
                        await proto_session.commit()
                    logger.info(
                        "protocol_marked_ready",
                        protocol_id=str(protocol_id),
                    )
                except Exception as proto_err:
                    logger.warning(
                        "protocol_status_update_failed",
                        protocol_id=str(protocol_id),
                        error=str(proto_err),
                    )

            # Финальный статус — после сохранения
            try:
                from app.services.task_status import update_task_status_in_db
                await update_task_status_in_db(
                    task_id,
                    "completed" if status.status != "failed" else "failed",
                    progress=100.0,
                    message=status.message or "Завершено",
                )
            except Exception as db_err:
                logger.warning(
                    "completion_db_update_failed",
                    task_id=str(task_id),
                    error=str(db_err),
                )

            logger.info(
                "transcription_completed",
                task_id=str(task_id),
                protocol_id=str(protocol_id),
                duration=info.duration,
                language=info.language,
                language_probability=info.language_probability,
                num_segments=len(segments_list),
            )

        except asyncio.CancelledError:
            # P2-fix: раньше CancelledError (BaseException) не ловился
            # except Exception, и статус оставался "processing".
            status.status = "cancelled"
            status.message = "Отменено пользователем"
            logger.info("transcription_cancelled", task_id=str(task_id))
            try:
                from app.services.task_status import update_task_status_in_db
                await update_task_status_in_db(
                    task_id,
                    "cancelled",
                    error="Отменено пользователем",
                )
            except Exception:
                pass
            raise

        except Exception as e:
            status.status = "failed"
            status.error_message = str(e)[:1000]
            logger.exception("transcription_failed", task_id=str(task_id), error=str(e))
            # P0-fix: await вместо create_task — гарантируем запись до выхода.
            try:
                from app.services.task_status import update_task_status_in_db
                await update_task_status_in_db(
                    task_id, "failed", error=status.error_message,
                )
            except Exception as db_err:
                logger.warning(
                    "failure_db_update_failed",
                    task_id=str(task_id),
                    error=str(db_err),
                )
            raise

        return status

    async def _persist_utterances_loop(
        self,
        protocol_id: uuid.UUID,
        stop_event: asyncio.Event,
    ) -> int:
        """Каждые 2 сек забирает сегменты из очереди и пишет в БД пачкой.

        E131/E132: работает в главном event loop. progress_cb в worker thread
        кладёт сегменты в queue.Queue (thread-safe). После завершения —
        финальный flush остатка.

        Args:
            protocol_id: UUID протокола для utterance
            stop_event: asyncio.Event останавливающий loop

        Returns:
            int: общее количество сохранённых utterance
        """
        from decimal import Decimal

        batch_total = 0

        async def save_batch(batch):
            nonlocal batch_total
            if not batch:
                return
            try:
                # E137: Группировка сегментов по паузам (≤1.5 сек)
                GROUP_PAUSE_THRESHOLD = 1.5
                grouped = []
                current = None

                # E153: дедупликация по (start_sec, end_sec) внутри batch
                # Если в очереди уже есть одинаковые timestamps от retry — пропустить
                seen_starts = set()
                for seg in batch:
                    seg_start = float(seg.get("start", 0))
                    seg_end = float(seg.get("end", 0))
                    # E236: Whisper иногда возвращает сегменты с start_sec за
                    # пределами аудио (галлюцинации на длинных записях).
                    # Пропускаем такие — они не имеют смысла.
                    if (self._current_audio_duration
                            and seg_start > self._current_audio_duration + 5):
                        logger.warning(
                            "utterance_outside_audio",
                            start=seg_start,
                            duration=self._current_audio_duration,
                        )
                        continue
                    if seg_start in seen_starts:
                        continue
                    seen_starts.add(seg_start)

                    # E215: сохраняем avg_logprob в группировке (раньше использовался seg
                    # из внешнего цикла, что давало неправильный confidence)
                    seg_log = seg.get("avg_logprob")
                    if current is None:
                        current = {
                            "start": seg_start,
                            "end": seg_end,
                            "texts": [seg.get("text", "")],
                            "logs": [seg_log],
                        }
                    else:
                        pause = seg_start - current["end"]
                        if pause <= GROUP_PAUSE_THRESHOLD:
                            current["texts"].append(seg.get("text", ""))
                            current["logs"].append(seg_log)
                            current["end"] = seg_end
                        else:
                            grouped.append(current)
                            current = {
                                "start": seg_start,
                                "end": seg_end,
                                "texts": [seg.get("text", "")],
                                "logs": [seg_log],
                            }

                if current is not None:
                    grouped.append(current)

                async with AsyncSessionLocal() as session:
                    from sqlalchemy import select as _sel
                    import math as _math

                    for g in grouped:
                        merged_text = " ".join(t.strip() for t in g["texts"] if t.strip()).strip()
                        if not merged_text:
                            continue

                        # E230: existing=None по умолчанию (обычная транскрибация создаёт новые).
                        # upgrade-режим (only_update_weak) сначала удаляет старые через
                        # `transcribe()` → if not only_update_weak: DELETE.
                        existing = None

                        if existing:
                            # E162: обновить text (confidence считается в момент сохранения ниже)
                            existing.text = merged_text
                        else:
                            # E215: confidence из ВСЕХ avg_logprob в группе g
                            # (раньше был баг: использовался seg из внешнего цикла)
                            conf = None
                            valid_logs = [l for l in g.get("logs", []) if l is not None]
                            if valid_logs:
                                mean_alp = sum(valid_logs) / len(valid_logs)
                                conf = Decimal(str(round(min(1.0, max(0.0, _math.exp(mean_alp))), 3)))

                            u = Utterance(
                                protocol_id=protocol_id,
                                speaker_id=None,
                                start_sec=Decimal(str(round(g["start"], 3))),
                                end_sec=Decimal(str(round(g["end"], 3))),
                                text=merged_text,
                                text_original=merged_text,
                                confidence=conf,
                                low_confidence=(conf is not None and conf < Decimal("0.4")),
                                important=False,
                                corrected_by_llm=False,
                            )
                            session.add(u)
                    await session.commit()
                batch_total += len(grouped)
                logger.info(
                    "utterances_batch_saved",
                    protocol_id=str(protocol_id),
                    batch_size=len(grouped),
                    total=batch_total,
                )
            except Exception as e:
                logger.exception(
                    "utterances_batch_save_failed",
                    protocol_id=str(protocol_id),
                    batch_size=len(batch),
                    error=str(e),
                )

        # Main loop: забираем из очереди каждые 2 сек
        while not stop_event.is_set():
            batch = []
            try:
                while True:
                    seg = self._utterance_queue.get_nowait()
                    batch.append(seg)
            except queue.Empty:
                pass

            await save_batch(batch)

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

        # Финальный flush — забираем всё, что осталось
        leftover = []
        try:
            while True:
                leftover.append(self._utterance_queue.get_nowait())
        except queue.Empty:
            pass

        await save_batch(leftover)

        if leftover:
            logger.info(
                "utterances_final_flush",
                protocol_id=str(protocol_id),
                count=len(leftover),
                batch_total=batch_total,
            )

        return batch_total
    def get_status(self, task_id) -> TranscriptionStatus | None:
        """Return in-memory status for a task, if it exists.

        E120: метод отсутствовал — фронт всегда шёл в БД.
        E123: без DB fallback (sync-функция не может вызывать asyncio.run
              из работающего loop). Роутер сам делает DB fallback.

        E182: для завершённых задач возвращаем None — фронт должен
        брать финальный статус из БД и останавливать polling. Иначе
        in-memory `processing` держит polling вечно.
        """
        import uuid as _uuid
        if isinstance(task_id, str):
            try:
                task_id = _uuid.UUID(task_id)
            except (ValueError, TypeError):
                return None

        status = self._tasks.get(task_id)
        if status is None:
            return None

        # E182: не отдаём завершённые задачи из памяти —
        # пусть роутер вернёт финальный статус из БД.
        if status.status in ("completed", "failed", "cancelled"):
            return None

        if status.status == "processing":
            try:
                from app.services.active_tasks import is_task_alive
                if not is_task_alive(str(task_id)):
                    status.status = "cancelled"
                    status.message = status.message or "Отменено"
            except Exception:
                # active_tasks может отсутствовать в тестах — молча пропускаем
                pass

        return status


# Singleton instance
transcription_service = TranscriptionService()
