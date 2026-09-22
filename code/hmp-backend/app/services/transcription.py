"""Transcription service — Whisper integration (ADR-005).

Background worker pattern: 1 worker per ADR-009.
Chunks of 30 sec per NFR §QG-7.

US-005: Real Whisper integration with progress tracking.
"""
import asyncio
import queue  # E131: для потоковой записи utterance из worker thread
import time
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
    status: Literal[
        "queued", "processing", "paused",
        "completed", "failed", "cancelled",
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
        """
        if self._model is None:
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
                                "cudnn64_9.dll",
                                "cudnn64_8.dll",
                                "cudnn64_7.dll",
                            ],
                        )
                        use_device = "cpu"
                        use_compute = "int8"
                except Exception as cudnn_err:
                    logger.warning("cudnn_check_failed", error=str(cudnn_err))
                    use_device = "cpu"
                    use_compute = "int8"

            primary = settings.whisper_model
            try:
                logger.info("loading_whisper_model", model=primary, device=use_device)
                self._model = WhisperModel(
                    primary, device=use_device, compute_type=use_compute,
                )
                logger.info("whisper_model_loaded", model=primary, device=use_device)
                self._last_fallback_reason = None
                return self._model
            except Exception as e:
                logger.warning(
                    "whisper_primary_model_failed", primary=primary, error=str(e),
                )

            try:
                logger.info("whisper_fallback_to_tiny", requested=primary)
                self._model = WhisperModel("tiny", device="cpu", compute_type="int8")
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

            # E131: удаляем старые utterances для этого протокола (перезапись)
            try:
                from sqlalchemy import delete
                from app.db.session import AsyncSessionLocal
                from app.db.models import Utterance as _OldU
                async with AsyncSessionLocal() as clean_session:
                    await clean_session.execute(
                        delete(_OldU).where(_OldU.protocol_id == protocol_id)
                    )
                    await clean_session.commit()
                logger.info("old_utterances_cleared", protocol_id=str(protocol_id))
            except Exception as clear_err:
                logger.warning(
                    "old_utterances_clear_failed",
                    protocol_id=str(protocol_id),
                    error=str(clear_err),
                )

            model = await asyncio.to_thread(self._load_model)
            logger.info(
                "transcribe_model_loaded",
                task_id=str(task_id), model_loaded=model is not None,
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
                """
                while not stop_heartbeat.is_set():
                    elapsed = time.time() - transcribe_start_time
                    status.message = f"Обработка аудио... {int(elapsed)}с"
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
                            from app.db.session import AsyncSessionLocal
                            from sqlalchemy import select as _sel
                            from app.db.models import Utterance as _Utt
                            import json as _json
                            async with AsyncSessionLocal() as ps:
                                # Получаем последний сохранённый segment для time-tracking
                                last_seg_q = await ps.execute(
                                    _sel(_Utt).where(_Utt.protocol_id == protocol_id)
                                    .order_by(_Utt.start_sec.desc()).limit(1)
                                )
                                last_seg = last_seg_q.scalar_one_or_none()
                                if last_seg:
                                    t = await ps.get(_TT, task_id)
                                    if t:
                                        # Сохраняем уже сохранённые utterance
                                        segs_q = await ps.execute(
                                            _sel(_Utt.start_sec, _Utt.end_sec, _Utt.text)
                                            .where(_Utt.protocol_id == protocol_id)
                                            .order_by(_Utt.start_sec.asc())
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

            # E131: потоковая запись utterance — сегменты появляются в БД
            # по мере генерации, не дожидаясь конца транскрибации.
            utterances_task = asyncio.create_task(
                self._persist_utterances_loop(protocol_id, stop_heartbeat)
            )

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
                segments_generator, info = model.transcribe(
                    str(audio_path),
                    language=settings.whisper_language,
                    beam_size=settings.whisper_beam_size,
                    word_timestamps=False,
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

            # E129: Сохраняем сегменты ДО финального update_task_status_in_db
            if segments_list:
                try:
                    saved = await self._save_utterances(protocol_id, segments_list)
                    status.message = f"Сохранено реплик: {saved}"
                    logger.info(
                        "save_utterances_done",
                        task_id=str(task_id),
                        count=saved,
                    )
                except Exception as save_err:
                    logger.exception(
                        "save_utterances_failed",
                        task_id=str(task_id),
                        protocol_id=str(protocol_id),
                        error=str(save_err),
                    )
                    status.message = f"Транскрибация готова, но сохранение упало: {save_err}"

                # E130: помечаем протокол как готовый (есть utterance)
                try:
                    from sqlalchemy import update as _upd_proto
                    from app.db.session import AsyncSessionLocal
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
        from app.db.session import AsyncSessionLocal
        from app.db.models import Utterance

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
                    if seg_start in seen_starts:
                        continue  # уже в этом batch — пропускаем дубль
                    seen_starts.add(seg_start)

                    if current is None:
                        current = {
                            "start": seg_start,
                            "end": seg_end,
                            "texts": [seg.get("text", "")],
                        }
                    else:
                        pause = seg_start - current["end"]
                        if pause <= GROUP_PAUSE_THRESHOLD:
                            current["texts"].append(seg.get("text", ""))
                            current["end"] = seg_end
                        else:
                            grouped.append(current)
                            current = {
                                "start": seg_start,
                                "end": seg_end,
                                "texts": [seg.get("text", "")],
                            }

                if current is not None:
                    grouped.append(current)

                async with AsyncSessionLocal() as session:
                    for g in grouped:
                        merged_text = " ".join(t.strip() for t in g["texts"] if t.strip()).strip()
                        if not merged_text:
                            continue
                        u = Utterance(
                            protocol_id=protocol_id,
                            speaker_id=None,
                            start_sec=Decimal(str(round(g["start"], 3))),
                            end_sec=Decimal(str(round(g["end"], 3))),
                            text=merged_text,
                            text_original=merged_text,
                            confidence=None,
                            low_confidence=False,
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

    async def _save_utterances(
        self,
        protocol_id: uuid.UUID,
        segments_list: list,
    ) -> int:
        """Сохранить сегменты Whisper в таблицу utterance.

        E129/E137: без этого 298 (или сколько нашлось бы) реплик теряются.
        E137: ГРУППИРОВКА — объединяем соседние сегменты в одну реплику:
        - Если между seg[i].end и seg[i+1].start пауза <= 1.5 сек И
          один speaker (тут все speaker_id=None, поэтому любая последовательность) →
          объединяем текст и расширяем start_sec/end_sec.
        - Иначе — отдельная реплика.
        Это сокращает ~250 сегментов до ~30-50 реплик (по фразам).

        - Удаляет старые utterance для этого protocol_id (перезапись при повторной транскрибации)
        - Вставляет новые сегменты
        - speaker_id остаётся None — диаризация проставит позже
        - confidence из avg_logprob (если есть)

        Возвращает число вставленных строк.
        """
        from decimal import Decimal
        from sqlalchemy import delete
        from app.db.session import AsyncSessionLocal
        from app.db.models import Utterance

        inserted = 0
        async with AsyncSessionLocal() as session:
            # E153: перезапись при повторной транскрибации —
            # удаляем все старые Utterance для этого протокола.
            # Используем DELETE + commit сначала, чтобы flush прошёл до INSERT.
            try:
                await session.execute(
                    delete(Utterance).where(Utterance.protocol_id == protocol_id)
                )
                await session.commit()  # отдельный commit чтобы DELETE был виден
                # Переоткрываем транзакцию для INSERT
                await session.begin()
                logger.info(
                    "utterances_cleared_for_retranscription",
                    protocol_id=str(protocol_id),
                )
            except Exception as clear_err:
                logger.warning("utterances_clear_failed", error=str(clear_err))
                await session.rollback()

            # E137: Группировка последовательных сегментов
            GROUP_PAUSE_THRESHOLD = 1.5  # секунд — если пауза больше, новая реплика
            grouped = []
            current = None

            for seg in segments_list:
                text = (seg.text or "").strip()
                if not text:
                    continue

                alp = getattr(seg, "avg_logprob", None)
                conf = None
                if alp is not None:
                    import math
                    conf = Decimal(str(round(min(1.0, max(0.0, math.exp(alp))), 3)))

                seg_end = float(seg.end)
                seg_start = float(seg.start)

                if current is None:
                    current = {
                        "start": seg_start,
                        "end": seg_end,
                        "texts": [text],
                        "confs": [conf],
                    }
                else:
                    pause = seg_start - current["end"]
                    if pause <= GROUP_PAUSE_THRESHOLD:
                        # Объединяем в текущую реплику
                        current["texts"].append(text)
                        current["confs"].append(conf)
                        current["end"] = seg_end
                    else:
                        # Закрываем текущую, начинаем новую
                        grouped.append(current)
                        current = {
                            "start": seg_start,
                            "end": seg_end,
                            "texts": [text],
                            "confs": [conf],
                        }

            if current is not None:
                grouped.append(current)

            # Вставляем группы в БД
            for g in grouped:
                # Берём средний confidence
                valid_confs = [c for c in g["confs"] if c is not None]
                avg_conf = None
                if valid_confs:
                    s = sum(valid_confs)
                    avg_conf = Decimal(str(round(s / len(valid_confs), 3)))

                # Склеиваем текст через пробел (с заглавной в начале предложения)
                merged_text = " ".join(g["texts"]).strip()

                u = Utterance(
                    protocol_id=protocol_id,
                    speaker_id=None,
                    start_sec=Decimal(str(round(g["start"], 3))),
                    end_sec=Decimal(str(round(g["end"], 3))),
                    text=merged_text,
                    text_original=merged_text,
                    confidence=avg_conf,
                    low_confidence=bool(
                        avg_conf is not None and avg_conf < Decimal("0.4")
                    ),
                    important=False,
                    corrected_by_llm=False,
                )
                session.add(u)
                inserted += 1

            await session.commit()

            logger.info(
                "utterances_grouped_and_saved",
                protocol_id=str(protocol_id),
                input_segments=len(segments_list),
                grouped_count=inserted,
            )

        return inserted

    def get_status(self, task_id) -> TranscriptionStatus | None:
        """Return in-memory status for a task, if it exists.

        E120: метод отсутствовал — фронт всегда шёл в БД.
        E123: без DB fallback (sync-функция не может вызывать asyncio.run
              из работающего loop). Роутер сам делает DB fallback.
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
