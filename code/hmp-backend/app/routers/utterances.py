"""Utterance endpoints (US-008, US-048, US-044, API §4.6)."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging_config import get_logger
from app.db.models import Protocol, ProtocolVersion, Speaker, Utterance
from app.db.session import get_db
from app.schemas import (
    UtteranceResponse,
    UtteranceUpdateSpeaker,
    UtteranceUpdateText,
)

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _load_utterance(db: AsyncSession, utterance_id: uuid.UUID) -> Utterance:
    """Fetch an utterance with speaker eagerly loaded or raise 404."""
    query = (
        select(Utterance)
        .options(selectinload(Utterance.speaker))
        .where(Utterance.id == utterance_id)
    )
    result = await db.execute(query)
    utterance = result.scalar_one_or_none()
    if not utterance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Реплика не найдена",
        )
    return utterance


def _to_response(utt: Utterance) -> UtteranceResponse:
    """Build UtteranceResponse including denormalised speaker_label."""
    return UtteranceResponse(
        id=utt.id,
        protocol_id=utt.protocol_id,
        speaker_id=utt.speaker_id,
        speaker_label=utt.speaker.speaker_label if utt.speaker else None,
        start_sec=utt.start_sec,
        end_sec=utt.end_sec,
        text=utt.text,
        confidence=utt.confidence,
        low_confidence=utt.low_confidence,
        important=utt.important,
        corrected_by_llm=utt.corrected_by_llm,
        created_at=utt.created_at,
        updated_at=utt.updated_at,
    )


async def _next_version_number(
    db: AsyncSession, protocol_id: uuid.UUID
) -> int:
    """Compute next protocol_version.version_number for the protocol."""
    from sqlalchemy import func

    result = await db.execute(
        select(func.coalesce(func.max(ProtocolVersion.version_number), 0)).where(
            ProtocolVersion.protocol_id == protocol_id
        )
    )
    return (result.scalar() or 0) + 1


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/utterances",
    response_model=dict,
    summary="List utterances for a protocol",
)
async def list_utterances(
    protocol_id: uuid.UUID = Query(..., description="Protocol ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    speaker_id: uuid.UUID | None = Query(None),
    low_confidence_only: bool = Query(False),
    # E133: after_sec для инкрементальной выборки (streaming)
    after_sec: float | None = Query(
        None,
        ge=0,
        description="Вернуть только реплики со start_sec > after_sec (для polling)",
    ),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List utterances with pagination (API §4.6).

    Ordered by ``start_sec`` then ``created_at`` for stable pagination.
    """
    # Verify protocol exists
    protocol = await db.get(Protocol, protocol_id)
    if not protocol:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Протокол не найден",
        )

    from sqlalchemy import func

    base = select(Utterance).where(Utterance.protocol_id == protocol_id)
    if speaker_id is not None:
        base = base.where(Utterance.speaker_id == speaker_id)
    if low_confidence_only:
        base = base.where(Utterance.low_confidence.is_(True))
    # E133: инкрементальная выборка — только новые реплики
    if after_sec is not None:
        base = base.where(Utterance.start_sec > after_sec)

    # Total count (без пагинации — для UI)
    total_query = select(func.count()).select_from(base.subquery())
    total = (await db.execute(total_query)).scalar() or 0

    # Page
    query = (
        base.options(selectinload(Utterance.speaker))
        .order_by(Utterance.start_sec.asc(), Utterance.created_at.asc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    utterances = result.scalars().all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": [_to_response(u) for u in utterances],
    }


@router.get(
    "/utterances/{utterance_id}",
    response_model=UtteranceResponse,
    summary="Get utterance by id",
)
async def get_utterance(
    utterance_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> UtteranceResponse:
    """Get a single utterance (API §4.6)."""
    utterance = await _load_utterance(db, utterance_id)
    return _to_response(utterance)


@router.patch(
    "/utterances/{utterance_id}/text",
    response_model=UtteranceResponse,
    summary="Edit utterance text with version snapshot",
)
async def update_utterance_text(
    utterance_id: uuid.UUID,
    body: UtteranceUpdateText,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UtteranceResponse:
    """US-048: edit utterance text. When the text actually changes and
    ``version_snapshot`` is true, write the previous text into
    ``protocol_version`` so it can be restored later.
    """
    utterance = await _load_utterance(db, utterance_id)

    correlation_id = getattr(request.state, "correlation_id", None)

    # No-op? Just return current state.
    if utterance.text == body.text:
        return _to_response(utterance)

    previous_text = utterance.text

    # Set text_original on the first edit only (preserve the original transcript).
    if utterance.text_original is None:
        utterance.text_original = previous_text

    utterance.text = body.text
    utterance.updated_at = datetime.now(timezone.utc)

    snapshot_taken = False
    if body.version_snapshot:
        snapshot = {
            "utterance_id": str(utterance.id),
            "field": "text",
            "previous_text": previous_text,
            "new_text": body.text,
            "previous_text_original": utterance.text_original,
        }
        version = ProtocolVersion(
            protocol_id=utterance.protocol_id,
            version_number=await _next_version_number(db, utterance.protocol_id),
            snapshot=snapshot,
            changed_field=f"utterance:{utterance.id}:text",
            changed_by="user",
            change_reason="utterance text edit (US-048)",
        )
        db.add(version)
        snapshot_taken = True

    await db.commit()
    await db.refresh(utterance)
    utterance = await _load_utterance(db, utterance.id)

    logger.info(
        "utterance_text_updated",
        utterance_id=str(utterance.id),
        protocol_id=str(utterance.protocol_id),
        snapshot_taken=snapshot_taken,
        correlation_id=correlation_id,
    )

    return _to_response(utterance)


@router.patch(
    "/utterances/{utterance_id}/speaker",
    response_model=UtteranceResponse,
    summary="Reassign utterance speaker",
)
async def update_utterance_speaker(
    utterance_id: uuid.UUID,
    body: UtteranceUpdateSpeaker,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UtteranceResponse:
    """US-008: reassign an utterance to a different speaker."""
    utterance = await _load_utterance(db, utterance_id)

    # Validate target speaker exists and belongs to same protocol
    target = await db.get(Speaker, body.speaker_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Целевой оратор не найден",
        )
    if target.protocol_id != utterance.protocol_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Оратор принадлежит другому протоколу",
        )

    correlation_id = getattr(request.state, "correlation_id", None)
    previous_speaker_id = utterance.speaker_id
    utterance.speaker_id = body.speaker_id
    utterance.updated_at = datetime.now(timezone.utc)

    await db.commit()
    utterance = await _load_utterance(db, utterance.id)

    logger.info(
        "utterance_speaker_reassigned",
        utterance_id=str(utterance.id),
        protocol_id=str(utterance.protocol_id),
        previous_speaker_id=str(previous_speaker_id) if previous_speaker_id else None,
        new_speaker_id=str(body.speaker_id),
        correlation_id=correlation_id,
    )

    return _to_response(utterance)


@router.get(
    "/utterances/{utterance_id}/versions",
    response_model=dict,
    summary="List text versions for an utterance",
)
async def list_utterance_versions(
    utterance_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """US-048: list version snapshots for an utterance, newest first."""
    utterance = await _load_utterance(db, utterance_id)

    result = await db.execute(
        select(ProtocolVersion)
        .where(
            ProtocolVersion.protocol_id == utterance.protocol_id,
            ProtocolVersion.changed_field == f"utterance:{utterance.id}:text",
        )
        .order_by(ProtocolVersion.version_number.desc())
    )
    versions = result.scalars().all()

    items = [
        {
            "version_number": v.version_number,
            "changed_field": v.changed_field,
            "changed_by": v.changed_by,
            "change_reason": v.change_reason,
            "created_at": v.created_at,
            "snapshot": v.snapshot,
        }
        for v in versions
    ]

    return {
        "utterance_id": str(utterance.id),
        "total": len(items),
        "items": items,
    }


@router.post(
    "/utterances/{utterance_id}/restore/{version_number}",
    response_model=UtteranceResponse,
    summary="Restore utterance text from a version snapshot",
)
async def restore_utterance_version(
    utterance_id: uuid.UUID,
    version_number: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UtteranceResponse:
    """Restore an utterance's text from a previously stored version
    snapshot. The current text is itself snapshotted first so the
    restore itself is reversible.
    """
    if version_number < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Номер версии должен быть положительным",
        )

    utterance = await _load_utterance(db, utterance_id)

    result = await db.execute(
        select(ProtocolVersion).where(
            ProtocolVersion.protocol_id == utterance.protocol_id,
            ProtocolVersion.version_number == version_number,
            ProtocolVersion.changed_field == f"utterance:{utterance.id}:text",
        )
    )
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Версия {version_number} для реплики не найдена",
        )

    snapshot = version.snapshot or {}
    target_text = snapshot.get("previous_text")
    if target_text is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Снимок версии не содержит previous_text",
        )

    correlation_id = getattr(request.state, "correlation_id", None)
    current_text = utterance.text

    # Snapshot the current text before replacing it.
    new_snapshot = {
        "utterance_id": str(utterance.id),
        "field": "text",
        "previous_text": current_text,
        "new_text": target_text,
        "previous_text_original": utterance.text_original,
        "restored_from_version": version_number,
    }
    db.add(
        ProtocolVersion(
            protocol_id=utterance.protocol_id,
            version_number=await _next_version_number(db, utterance.protocol_id),
            snapshot=new_snapshot,
            changed_field=f"utterance:{utterance.id}:text",
            changed_by="user",
            change_reason=f"restore from version {version_number}",
        )
    )

    utterance.text = target_text
    utterance.updated_at = datetime.now(timezone.utc)

    await db.commit()
    utterance = await _load_utterance(db, utterance.id)

    logger.info(
        "utterance_version_restored",
        utterance_id=str(utterance.id),
        protocol_id=str(utterance.protocol_id),
        restored_from_version=version_number,
        correlation_id=correlation_id,
    )

    return _to_response(utterance)
