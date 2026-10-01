"""Weak-segment upgrade endpoint (US-086, E162).

Re-runs a larger Whisper model over only the segments whose original
confidence is below ``confidence_threshold`` and writes the new text /
confidence back to the DB.

Endpoint:
  POST /transcribe/upgrade/{protocol_id}
"""
import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import get_logger
from app.db.models import AudioFile, Protocol, Utterance
from app.db.session import get_db

logger = get_logger(__name__)

router = APIRouter()


# ----------------------------------------------------------------------------
# POST /transcribe/upgrade/{protocol_id}  (E162)
# ----------------------------------------------------------------------------


@router.post(
    "/transcribe/upgrade/{protocol_id}",
    summary="Upgrade low-confidence segments with larger model (US-086)",
)
async def upgrade_weak_segments_endpoint(
    protocol_id: str,
    target_model: str = "large-v3",  # E162: default large-v3
    confidence_threshold: float = 0.7,  # E162: < threshold → upgrade
    db: AsyncSession = Depends(get_db),
) -> dict:
    """E162: повторно распознать только слабые сегменты (confidence < threshold) большой моделью.

    Стратегия:
    1. Загружаем все Utterance для протокола
    2. Отбираем те, у которых confidence < threshold
    3. Запускаем большую модель только на этих аудио-фрагментах
    4. Обновляем text и confidence в БД

    Возвращает статистику: сколько обработано / улучшено.
    """
    try:
        pid = uuid.UUID(protocol_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Невалидный protocol_id")

    proto = await db.get(Protocol, pid)
    if not proto:
        raise HTTPException(status_code=404, detail="Протокол не найден")

    # Найти аудиофайл
    if not proto.audio_file_id:
        raise HTTPException(status_code=400, detail="Протокол без аудиофайла")
    audio_file = await db.get(AudioFile, proto.audio_file_id)
    if not audio_file:
        raise HTTPException(status_code=400, detail="Аудиофайл не найден")
    audio_path = Path(audio_file.file_path)
    if not audio_path.exists():
        raise HTTPException(
            status_code=400, detail=f"Аудио не найдено: {audio_path}"
        )

    # Загружаем все Utterance для протокола с confidence < threshold
    # либо low_confidence=True (даже без численного confidence)
    weak_q = await db.execute(
        select(Utterance)
        .where(
            Utterance.protocol_id == pid,
            (
                (
                    Utterance.confidence.isnot(None)
                    & (Utterance.confidence < confidence_threshold)
                )
                | (Utterance.confidence.is_(None))
                | (Utterance.low_confidence.is_(True))
            ),
        )
        .order_by(Utterance.start_sec.asc())
    )
    weak_segments = list(weak_q.scalars().all())

    if not weak_segments:
        return {
            "protocol_id": protocol_id,
            "target_model": target_model,
            "weak_segments_found": 0,
            "upgraded": 0,
            "skipped": 0,
            "message": "Нет слабых сегментов для улучшения",
        }

    logger.info(
        "upgrade_weak_segments_start",
        protocol_id=protocol_id,
        target_model=target_model,
        weak_count=len(weak_segments),
        threshold=confidence_threshold,
    )

    # Запускаем большую модель — она будет работать по всему аудио,
    # но мы сохраним только результаты для "слабых" сегментов
    # (Whisper не умеет resume с произвольной секунды — см. E152)
    # E220: выносим blocking call в фоновую задачу.
    # Иначе HTTP-запрос будет висеть минуты → таймаут браузера.
    task_id = uuid.uuid4()

    async def _upgrade_runner():
        try:
            from app.db.session import AsyncSessionLocal
            from app.services.transcription import transcription_service

            async with AsyncSessionLocal() as runner_db:
                await transcription_service.transcribe(
                    protocol_id=pid,
                    audio_path=audio_path,
                    task_id=task_id,
                    duration_sec=audio_file.duration_sec,
                    target_model_override=target_model,
                    only_update_weak=True,
                )
            logger.info(
                "upgrade_weak_segments_completed",
                protocol_id=protocol_id,
                target_model=target_model,
            )
        except Exception as exc:
            logger.exception("upgrade_runner_failed", error=str(exc))

    bg = asyncio.create_task(_upgrade_runner())
    from app.services.active_tasks import register_active_task

    register_active_task(str(task_id), bg)

    return {
        "protocol_id": protocol_id,
        "target_model": target_model,
        "task_id": str(task_id),
        "weak_segments_found": len(weak_segments),
        "message": (
            f"Upgrade queued: {len(weak_segments)} сегментов "
            f"будут обработаны моделью {target_model}"
        ),
    }