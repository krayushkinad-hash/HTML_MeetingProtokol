"""Diarization endpoints (US-007 — API §4.6).

Speaker diarization (US-007) groups utterances by voice via heuristic (E141):
- Без pyannote.audio, через паузы (PAUSE_THRESHOLD_SEC).
- При паузе > 2 сек между utterance.start и предыдущим utterance.end
  считаем что спикер сменился → создаём новый Speaker.

Эндпоинты:
  - POST /diarize/run — запуск (async, asyncio.create_task)
  - GET  /diarize/result/{protocol_id} — результат из DiarizationResult
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import get_logger
from app.db.models import DiarizationResult, Protocol
from app.db.session import get_db

logger = get_logger(__name__)
router = APIRouter()


# E141: Registry активных задач (для отмены и мониторинга)
_active_diarize_tasks: dict[uuid.UUID, asyncio.Task] = {}


# ---------------------------------------------------------------------------
# Schemas (local — not yet exposed via app.schemas package)
# ---------------------------------------------------------------------------

class DiarizeRunRequest(BaseModel):
    """POST /diarize/run body."""
    protocol_id: uuid.UUID
    num_speakers: int | None = Field(default=None, ge=1, le=20)
    min_speakers: int | None = Field(default=None, ge=1, le=10)
    max_speakers: int | None = Field(default=None, ge=1, le=20)
    pipeline_version: str | None = None


class DiarizeTaskAccepted(BaseModel):
    """202 Accepted response for diarize/run."""
    task_id: uuid.UUID
    protocol_id: uuid.UUID
    status: Literal["queued"]
    estimated_completion: datetime
    message: str = "Диаризация поставлена в очередь"


# In-memory task registry (mirrors transcribe pattern; service-backed later)
_diarize_tasks: dict[uuid.UUID, dict] = {}


# ---------------------------------------------------------------------------
# POST /diarize/run
# ---------------------------------------------------------------------------

@router.post(
    "/diarize/run",
    response_model=DiarizeTaskAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start diarization (US-007)",
)
async def run_diarization(
    body: DiarizeRunRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> DiarizeTaskAccepted:
    """Queue a speaker-diarization task.

    TODO(ADR-005): invoke ``pyannote.audio`` pipeline when
        ``settings.huggingface_token`` is configured; today we just persist
        a queued stub so the API surface is exercisable end-to-end.
    """
    proto_row = await db.execute(
        select(Protocol).where(Protocol.id == body.protocol_id)
    )
    protocol: Protocol | None = proto_row.scalar_one_or_none()
    if not protocol:
        logger.warning("diarize_protocol_not_found", protocol_id=str(body.protocol_id))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Протокол {body.protocol_id} не найден",
        )

    # E191-fix: эвристическая диаризация НЕ требует HF_TOKEN.
    # diarization_service работает по паузам (PAUSE_THRESHOLD_SEC),
    # без pyannote.audio и без обращения к HuggingFace.
    # Проверка токена удалена.

    task_id = uuid.uuid4()
    estimated = datetime.now(timezone.utc) + timedelta(minutes=2)

    _diarize_tasks[task_id] = {
        "id": task_id,
        "protocol_id": body.protocol_id,
        "status": "queued",
        "num_speakers": body.num_speakers,
        "pipeline_version": body.pipeline_version,
        "created_at": datetime.now(timezone.utc),
    }

    logger.info(
        "diarize_queued",
        task_id=str(task_id),
        protocol_id=str(body.protocol_id),
        num_speakers=body.num_speakers,
    )

    # E202: создаём новую сессию внутри _runner.
    # Старая db закрывается сразу после возврата из run_diarization.
    async def _runner() -> None:
        try:
            _diarize_tasks[task_id]["status"] = "running"

            from app.db.session import AsyncSessionLocal
            from app.services.diarization import diarization_service

            async with AsyncSessionLocal() as runner_db:
                result = await diarization_service.diarize_protocol(
                    db=runner_db,
                    protocol_id=body.protocol_id,
                    min_speakers=body.min_speakers,
                    max_speakers=body.max_speakers,
                )

            _diarize_tasks[task_id]["status"] = "completed"
            _diarize_tasks[task_id]["result_id"] = str(result.id)
            logger.info(
                "diarize_runner_completed",
                task_id=str(task_id),
                num_speakers=result.num_speakers_detected,
            )
        except Exception as exc:
            _diarize_tasks[task_id]["status"] = "failed"
            _diarize_tasks[task_id]["error"] = str(exc)[:500]
            logger.exception(
                "diarize_runner_failed",
                task_id=str(task_id),
                error=str(exc),
            )

    # E202: убрано сохранение db (нельзя использовать после возврата)
    # E141: asyncio.create_task вместо background_tasks (как в transcribe)
    bg_task = asyncio.create_task(_runner())
    _active_diarize_tasks[task_id] = bg_task  # регистрируем

    return DiarizeTaskAccepted(
        task_id=task_id,
        protocol_id=body.protocol_id,
        status="queued",
        estimated_completion=estimated,
    )


# ---------------------------------------------------------------------------
# GET /diarize/result/{protocol_id}
# ---------------------------------------------------------------------------

@router.get(
    "/diarize/result/{protocol_id}",
    summary="Get diarization result for protocol",
)
async def get_diarization_result(
    protocol_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the latest ``DiarizationResult`` for ``protocol_id`` (or 404)."""
    # First verify the protocol exists so we don't leak IDs
    proto_row = await db.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )
    protocol: Protocol | None = proto_row.scalar_one_or_none()
    if not protocol:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Протокол {protocol_id} не найден",
        )

    result_row = await db.execute(
        select(DiarizationResult).where(DiarizationResult.protocol_id == protocol_id)
    )
    diar: DiarizationResult | None = result_row.scalar_one_or_none()
    if not diar:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Результат диаризации ещё не готов",
        )

    return {
        "id": str(diar.id),
        "protocol_id": str(diar.protocol_id),
        "der_score": float(diar.der_score) if diar.der_score is not None else None,
        "num_speakers_detected": diar.num_speakers_detected,
        "num_speakers_expected": diar.num_speakers_expected,
        "pipeline_version": diar.pipeline_version,
        "confidence_avg": float(diar.confidence_avg) if diar.confidence_avg is not None else None,
        "segments": diar.segments_json or [],
        "created_at": diar.created_at,
    }
