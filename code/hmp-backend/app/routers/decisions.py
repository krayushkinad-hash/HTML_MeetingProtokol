"""Decisions CRUD (US-023).

A *decision* is a manually-recorded outcome from a meeting protocol. LLM-extracted
decisions live behind the AI/summary pipeline; this router is for user-managed
records.

Endpoints:
  * POST   /decisions                       — create
  * GET    /protocols/{protocol_id}/decisions — list for a protocol
  * DELETE /decisions/{decision_id}         — remove
"""
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import get_logger
from app.db.models import Decision, Protocol, Utterance
from app.db.session import get_db

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Local schemas (kept here while app.schemas grows organically)
# ---------------------------------------------------------------------------

class DecisionCreate(BaseModel):
    """POST /decisions body."""
    protocol_id: uuid.UUID
    text: str = Field(..., min_length=1, max_length=2000)
    decided_by: str | None = Field(None, max_length=100)
    priority: Literal["low", "medium", "high"] = "medium"
    source_utterance_id: uuid.UUID | None = None
    # E146: прямой timestamp_sec для Live Mode (когда нет utterance)
    timestamp_sec: float | None = Field(None, ge=0)
    # E146: режим источника — для UX
    source: Literal["transcript", "live"] = "transcript"


class DecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    protocol_id: uuid.UUID
    text: str
    decided_by: str | None
    source_utterance_id: uuid.UUID | None
    timestamp_sec: float | None = None  # E146: вычисленное поле
    priority: str
    created_at: datetime


def _to_response(d: Decision) -> DecisionResponse:
    return DecisionResponse(
        id=d.id,
        protocol_id=d.protocol_id,
        text=d.text,
        decided_by=d.decided_by,
        source_utterance_id=d.source_utterance_id,
        priority=d.priority,
        created_at=d.created_at,
    )


# ---------------------------------------------------------------------------
# POST /decisions
# ---------------------------------------------------------------------------

@router.post(
    "/decisions",
    response_model=DecisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create decision (US-023)",
)
async def create_decision(
    body: DecisionCreate,
    db: AsyncSession = Depends(get_db),
) -> DecisionResponse:
    """Persist a new decision linked to a protocol."""
    # Validate protocol exists
    proto_row = await db.execute(
        select(Protocol).where(Protocol.id == body.protocol_id)
    )
    protocol: Protocol | None = proto_row.scalar_one_or_none()
    if not protocol:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Протокол {body.protocol_id} не найден",
        )

    # Determine timestamp_sec: prefer utterance.start_sec, else body.timestamp_sec
    timestamp_sec: float | None = body.timestamp_sec
    if body.source_utterance_id is not None:
        utt_row = await db.execute(
            select(Utterance).where(Utterance.id == body.source_utterance_id)
        )
        utterance: Utterance | None = utt_row.scalar_one_or_none()
        if utterance is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Реплика {body.source_utterance_id} не найдена",
            )
        if utterance.protocol_id != body.protocol_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Реплика принадлежит другому протоколу",
            )
        # E146: денормализуем timestamp из utterance.start_sec
        timestamp_sec = float(utterance.start_sec)

    # E146: сохраняем timestamp_sec отдельным полем через JSON в Decision
    # Но в БД у нас только source_utterance_id. Храним через fallback:
    # при list — если timestamp_sec=None, но есть source_utterance, JOIN.
    decision = Decision(
        protocol_id=body.protocol_id,
        text=body.text,
        decided_by=body.decided_by,
        source_utterance_id=body.source_utterance_id,
        priority=body.priority,
    )
    db.add(decision)
    await db.commit()
    await db.refresh(decision)

    logger.info(
        "decision_created",
        decision_id=str(decision.id),
        protocol_id=str(decision.protocol_id),
        priority=decision.priority,
        timestamp_sec=timestamp_sec,
        source=body.source,
    )

    # E146: возвращаем с timestamp_sec
    response = _to_response(decision)
    response.timestamp_sec = timestamp_sec
    return response


# ---------------------------------------------------------------------------
# GET /protocols/{protocol_id}/decisions
# ---------------------------------------------------------------------------
# GET /decisions?protocol_id=X (legacy: with query param)
# ---------------------------------------------------------------------------


@router.get(
    "/decisions",
    response_model=list[DecisionResponse],
    summary="List decisions by protocol_id query (compat)",
)
async def list_decisions_by_protocol(
    protocol_id: uuid.UUID = Query(...),
    priority: Literal["low", "medium", "high"] | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[DecisionResponse]:
    """Legacy endpoint — same as /protocols/{id}/decisions."""
    return await _list_decisions_impl(protocol_id, priority, db)


@router.get(
    "/protocols/{protocol_id}/decisions",
    response_model=list[DecisionResponse],
    summary="List decisions for a protocol",
)
async def list_decisions(
    protocol_id: uuid.UUID,
    priority: Literal["low", "medium", "high"] | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[DecisionResponse]:
    """List all decisions for a protocol."""
    return await _list_decisions_impl(protocol_id, priority, db)


async def _list_decisions_impl(
    protocol_id: uuid.UUID,
    priority: str | None,
    db: AsyncSession,
) -> list[DecisionResponse]:
    """Common impl for list_decisions endpoints.

    E146: используем joinload для source_utterance, чтобы вернуть timestamp_sec.
    """
    from sqlalchemy.orm import selectinload

    query = (
        select(Decision)
        .options(selectinload(Decision.protocol))
        .where(Decision.protocol_id == protocol_id)
    )
    if priority:
        query = query.where(Decision.priority == priority)
    query = query.order_by(Decision.created_at.desc())
    result = await db.execute(query)
    decisions = result.scalars().all()

    items = []
    for d in decisions:
        response = _to_response(d)
        # E146: timestamp_sec — из source_utterance.start_sec если есть
        if d.source_utterance_id is not None:
            utt_row = await db.execute(
                select(Utterance).where(Utterance.id == d.source_utterance_id)
            )
            utt = utt_row.scalar_one_or_none()
            if utt:
                response.timestamp_sec = float(utt.start_sec)
        items.append(response)

    return items


# ---------------------------------------------------------------------------
# DELETE /decisions/{decision_id}
# ---------------------------------------------------------------------------

@router.delete(
    "/decisions/{decision_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete decision",
)
async def delete_decision(
    decision_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict | None:
    """Hard-delete a decision (no soft-delete — these are user-managed)."""
    decision = await db.get(Decision, decision_id)
    if not decision:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Решение {decision_id} не найдено",
        )

    await db.delete(decision)
    await db.commit()

    logger.info(
        "decision_deleted",
        decision_id=str(decision_id),
        protocol_id=str(decision.protocol_id),
    )
