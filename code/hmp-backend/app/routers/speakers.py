"""Speaker endpoints (US-007, US-008, US-009, API §5)."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status, Response
from fastapi.responses import Response
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import get_logger
from app.db.models import Protocol, Speaker, Utterance
from app.db.session import get_db
from app.schemas import (
    SpeakerMergeRequest,
    SpeakerResponse,
    SpeakerUpdate,
)

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _load_speaker(db: AsyncSession, speaker_id: uuid.UUID) -> Speaker:
    speaker = await db.get(Speaker, speaker_id)
    if not speaker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Оратор не найден",
        )
    return speaker


def _to_response(speaker: Speaker, utterance_count: int) -> SpeakerResponse:
    return SpeakerResponse(
        id=speaker.id,
        protocol_id=speaker.protocol_id,
        speaker_label=speaker.speaker_label,
        display_name=speaker.display_name,
        color=speaker.color,
        is_user=speaker.is_user,
        utterance_count=utterance_count,
        created_at=speaker.created_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/speakers",
    response_model=dict,
    summary="List speakers for a protocol",
)
async def list_speakers(
    protocol_id: uuid.UUID = Query(..., description="Protocol ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List speakers with utterance_count (US-007, API §5)."""
    protocol = await db.get(Protocol, protocol_id)
    if not protocol:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Протокол не найден",
        )

    # Aggregate utterance counts in a single query.
    count_subq = (
        select(
            Utterance.speaker_id.label("speaker_id"),
            func.count(Utterance.id).label("c"),
        )
        .where(Utterance.protocol_id == protocol_id)
        .group_by(Utterance.speaker_id)
        .subquery()
    )

    base = select(
        Speaker,
        func.coalesce(count_subq.c.c, 0).label("utterance_count"),
    ).where(Speaker.protocol_id == protocol_id)
    base = base.outerjoin(count_subq, count_subq.c.speaker_id == Speaker.id)

    total = (
        await db.execute(
            select(func.count()).select_from(base.subquery())
        )
    ).scalar() or 0

    query = (
        base.order_by(Speaker.speaker_label.asc())
        .offset(skip)
        .limit(limit)
    )
    rows = (await db.execute(query)).all()

    items = [
        _to_response(row[0], int(row[1])) for row in rows
    ]

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": items,
    }


@router.patch(
    "/speakers/{speaker_id}",
    response_model=SpeakerResponse,
    summary="Update speaker metadata",
)
async def update_speaker(
    speaker_id: uuid.UUID,
    body: SpeakerUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SpeakerResponse:
    """Partial update of display_name / color / is_user (US-008)."""
    speaker = await _load_speaker(db, speaker_id)
    correlation_id = getattr(request.state, "correlation_id", None)

    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Нет полей для обновления",
        )

    for field, value in update_data.items():
        setattr(speaker, field, value)

    await db.commit()
    await db.refresh(speaker)

    utterance_count = (
        await db.execute(
            select(func.count(Utterance.id)).where(Utterance.speaker_id == speaker.id)
        )
    ).scalar() or 0

    logger.info(
        "speaker_updated",
        speaker_id=str(speaker.id),
        protocol_id=str(speaker.protocol_id),
        fields=list(update_data.keys()),
        correlation_id=correlation_id,
    )

    return _to_response(speaker, int(utterance_count))


@router.post(
    "/speakers/merge",
    response_model=SpeakerResponse,
    summary="Merge two speakers",
)
async def merge_speakers(
    body: SpeakerMergeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SpeakerResponse:
    """US-009: reassign every utterance from ``source_id`` to
    ``target_id`` and delete the source. Optionally rename the target.
    """
    if body.source_id == body.target_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="source_id и target_id должны различаться",
        )

    source = await _load_speaker(db, body.source_id)
    target = await _load_speaker(db, body.target_id)

    if source.protocol_id != target.protocol_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Оратора нельзя объединить — разные протоколы",
        )

    correlation_id = getattr(request.state, "correlation_id", None)

    # Single UPDATE reassigns all utterances.
    reassigned = await db.execute(
        update(Utterance)
        .where(Utterance.speaker_id == source.id)
        .values(speaker_id=target.id, updated_at=datetime.now(timezone.utc))
    )

    if body.new_display_name is not None:
        target.display_name = body.new_display_name

    # Delete the now-orphan source speaker.
    await db.delete(source)

    await db.commit()
    await db.refresh(target)

    utterance_count = (
        await db.execute(
            select(func.count(Utterance.id)).where(Utterance.speaker_id == target.id)
        )
    ).scalar() or 0

    logger.info(
        "speakers_merged",
        source_id=str(body.source_id),
        target_id=str(body.target_id),
        utterances_reassigned=reassigned.rowcount or 0,
        correlation_id=correlation_id,
    )

    return _to_response(target, int(utterance_count))


@router.delete(
    "/speakers/{speaker_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete speaker",
)
async def delete_speaker(
    speaker_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a speaker. Only allowed when no utterances reference it."""
    speaker = await _load_speaker(db, speaker_id)

    utterance_count = (
        await db.execute(
            select(func.count(Utterance.id)).where(Utterance.speaker_id == speaker.id)
        )
    ).scalar() or 0

    if utterance_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Невозможно удалить оратора: на него ссылается "
                f"{utterance_count} реплик. Сначала объедините с другим оратором."
            ),
        )

    correlation_id = getattr(request.state, "correlation_id", None)
    protocol_id = speaker.protocol_id

    await db.delete(speaker)
    await db.commit()

    logger.info(
        "speaker_deleted",
        speaker_id=str(speaker_id),
        protocol_id=str(protocol_id),
        correlation_id=correlation_id,
    )
