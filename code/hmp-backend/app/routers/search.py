"""Full-text search across utterances (US-014, API §13).

Supports two modes:
  * ``mode=ilike`` — case-insensitive substring (default, robust for RU/Cyrillic)
  * ``mode=tsquery`` — PostgreSQL FTS with ``to_tsvector('russian', ...)``

If a ``protocol_id`` filter is given, the search is scoped to that protocol;
otherwise it runs across the entire corpus. Pagination via ``skip`` / ``limit``.

NOTE (DATA_MODEL §6.1): a GIN index on ``to_tsvector('russian', text)`` should
be added via Alembic migration for production performance; until then the
tsquery path falls back to a sequential scan.
"""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import get_logger
from app.db.models import Speaker, Utterance
from app.db.session import get_db

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# GET /search
# ---------------------------------------------------------------------------

@router.get(
    "/search",
    summary="Full-text search across utterances (US-014)",
)
async def search_utterances(
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    protocol_id: uuid.UUID | None = Query(None, description="Scope to protocol"),
    speaker_id: uuid.UUID | None = Query(None, description="Scope to speaker"),
    mode: Literal["ilike", "tsquery"] = Query("ilike", description="Match mode"),
    language: Literal["russian", "english", "simple"] = Query("russian"),
    skip: int = Query(0, ge=0, le=10_000),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Search utterance text. Returns matching utterances + total count."""
    if not q.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Параметр q не должен быть пустым",
        )

    base = select(Utterance)
    count_base = select(func.count()).select_from(Utterance)

    # --- Build WHERE ----------------------------------------------------
    if mode == "tsquery":
        try:
            lang = language
            ts_vector = func.to_tsvector(lang, Utterance.text)
            ts_query = func.plainto_tsquery(lang, q)
            match_clause = ts_vector.op("@@")(ts_query)
            base = base.where(match_clause)
            count_base = count_base.where(match_clause)
        except Exception as exc:
            # tsvector/plainto_tsquery unavailable — fall back to ilike
            logger.warning(
                "search_tsquery_unavailable",
                error=str(exc),
                fallback="ilike",
            )
            pattern = f"%{q}%"
            base = base.where(Utterance.text.ilike(pattern))
            count_base = count_base.where(Utterance.text.ilike(pattern))
    else:
        # Default ilike — robust across RU/EN and any substring
        pattern = f"%{q}%"
        base = base.where(Utterance.text.ilike(pattern))
        count_base = count_base.where(Utterance.text.ilike(pattern))

    if protocol_id is not None:
        base = base.where(Utterance.protocol_id == protocol_id)
        count_base = count_base.where(Utterance.protocol_id == protocol_id)

    if speaker_id is not None:
        base = base.where(Utterance.speaker_id == speaker_id)
        count_base = count_base.where(Utterance.speaker_id == speaker_id)

    # --- Total + page ---------------------------------------------------
    total = (await db.execute(count_base)).scalar() or 0

    rows = (
        await db.execute(
            base.order_by(Utterance.start_sec.asc())
            .offset(skip)
            .limit(limit)
        )
    ).scalars().all()

    items = [
        {
            "id": str(u.id),
            "protocol_id": str(u.protocol_id),
            "speaker_id": str(u.speaker_id) if u.speaker_id else None,
            "speaker_label": u.speaker.speaker_label if u.speaker else None,
            "start_sec": float(u.start_sec),
            "end_sec": float(u.end_sec),
            "text": u.text,
            "confidence": float(u.confidence) if u.confidence is not None else None,
            "low_confidence": u.low_confidence,
        }
        for u in rows
    ]

    logger.info(
        "search_executed",
        q_len=len(q),
        mode=mode,
        protocol_id=str(protocol_id) if protocol_id else None,
        speaker_id=str(speaker_id) if speaker_id else None,
        total=total,
        returned=len(items),
    )

    return {
        "query": q,
        "mode": mode,
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": items,
    }
