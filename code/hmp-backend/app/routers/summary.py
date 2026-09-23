"""Summary endpoints (US-022, US-037, API §11).

Endpoints:
    GET  /protocols/{protocol_id}/summary — fetch summary (404 if absent)
    POST /ai/summarize                    — generate summary (mock for now)

The actual LLM call lives in app.services.llm_client.llm_router.generate().
This router currently uses a placeholder so the contract is stable; replace
`_generate_summary_text()` with a real call when the integration ships.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field  # E225: добавлен Field для E219
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import get_logger
from app.db.models import Protocol, Summary, Utterance
from app.db.session import get_db
from app.schemas import SummarizeRequest, SummarizeResponse

logger = get_logger(__name__)
router = APIRouter()


# ============================================================================
# Local response schema (mirrors ORM)
# ============================================================================


class SummaryResponse(BaseModel):
    """Summary record returned by GET /protocols/{id}/summary."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    protocol_id: uuid.UUID
    text: str
    provider: str
    model: str | None
    tokens_used: int | None
    duration_ms: int | None = None  # E205: добавлено для совместимости с SummarizeResponse
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))  # E219: добавлено
    regenerated: int = 0  # E205: добавлено (default 0 для новых саммари)


# ============================================================================
# Helpers
# ============================================================================


def _to_response(s: Summary) -> SummaryResponse:
    return SummaryResponse(
        id=s.id,
        protocol_id=s.protocol_id,
        text=s.text,
        provider=s.provider,
        model=s.model,
        tokens_used=s.tokens_used,
        generated_at=s.generated_at,
        regenerated=s.regenerated,
    )


async def _collect_protocol_text(db: AsyncSession, protocol_id: uuid.UUID) -> str:
    """Concatenate all utterances of a protocol into one transcript.

    Used as the LLM prompt input. Returns empty string if there are no
    utterances yet (the summarizer can still run but will return a stub).
    """
    query = (
        select(Utterance.text)
        .where(Utterance.protocol_id == protocol_id)
        .order_by(Utterance.start_sec.asc())
    )
    result = await db.execute(query)
    texts = [row[0] for row in result.all() if row[0]]
    return "\n".join(texts)


async def _generate_summary_text(
    db: AsyncSession,
    protocol_id: uuid.UUID,
    req: SummarizeRequest,
) -> tuple[str, str, int]:
    """Generate summary text using LLM router.

    TODO: replace mock with:
        from app.services.llm_client import llm_router
        text, used_provider, tokens = await llm_router.generate(
            prompt=...,
            provider=req.provider,
            ...
        )

    For now we return a deterministic placeholder so the rest of the
    contract (DB row, regenerated counter, response shape) is exercised
    end-to-end.
    """
    transcript = await _collect_protocol_text(db, protocol_id)

    # Build a placeholder. Different styles → different lengths.
    style_prefix = {
        "brief": "Краткое саммари",
        "detailed": "Подробное саммари",
        "structured": "Структурированное саммари",
    }.get(req.style, "Саммари")

    snippet = transcript[:200].replace("\n", " ").strip()
    placeholder = (
        f"{style_prefix} протокола {protocol_id} "
        f"(стиль={req.style}, max_words={req.max_words}, "
        f"provider={req.provider}). "
        f"Транскрипт содержит {len(transcript)} символов. "
        f"Начало: {snippet or '[пусто]'}. "
        "[MOCK — реальная интеграция с LLM не подключена]"
    )

    # Truncate to max_words (rough approximation: 1 word ≈ 6 chars)
    max_chars = req.max_words * 6
    if len(placeholder) > max_chars:
        placeholder = placeholder[: max_chars - 3].rsplit(" ", 1)[0] + "..."

    # Mock tokens count
    tokens = len(placeholder.split())

    logger.info(
        "summary_generated_mock",
        protocol_id=str(protocol_id),
        provider=req.provider,
        style=req.style,
        tokens=tokens,
        transcript_chars=len(transcript),
    )
    return placeholder, req.provider, tokens


# ============================================================================
# GET /protocols/{protocol_id}/summary
# ============================================================================


@router.get(
    "/protocols/{protocol_id}/summary",
    summary="Get protocol summary (returns null if not generated)",
    responses={
        200: {"description": "Summary object or null if not yet generated"},
    },
)
async def get_summary(
    protocol_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """US-022 — fetch summary for a protocol. Returns null if not generated yet."""
    # Ensure protocol exists
    protocol = await db.get(Protocol, protocol_id)
    if not protocol or protocol.deleted_at is not None:
        return None

    query = select(Summary).where(Summary.protocol_id == protocol_id)
    result = await db.execute(query)
    summary = result.scalar_one_or_none()

    if not summary:
        return None

    return _to_response(summary)


# ============================================================================
# POST /ai/summarize
# ============================================================================


@router.post(
    "/ai/summarize",
    response_model=SummarizeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate summary (mock LLM)",
)
async def create_summary(
    req: SummarizeRequest,
    db: AsyncSession = Depends(get_db),
) -> SummarizeResponse:
    """US-037 — generate a summary for a protocol.

    If a summary already exists, its row is updated and `regenerated`
    counter is incremented. Returns the persisted summary as
    SummarizeResponse (matches the existing schema in app.schemas).
    """
    # Validate protocol
    protocol = await db.get(Protocol, req.protocol_id)
    if not protocol or protocol.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Протокол не найден",
        )

    text, used_provider, tokens = await _generate_summary_text(db, req.protocol_id, req)

    # Upsert Summary (1:1 with protocol — unique constraint)
    query = select(Summary).where(Summary.protocol_id == req.protocol_id)
    result = await db.execute(query)
    summary = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if summary:
        summary.text = text
        summary.provider = used_provider
        summary.model = req.provider  # store requested provider as "model" tag
        summary.tokens_used = tokens
        summary.generated_at = now
        summary.regenerated = (summary.regenerated or 0) + 1
        logger.info(
            "summary_regenerated",
            protocol_id=str(req.protocol_id),
            regenerated=summary.regenerated,
        )
    else:
        summary = Summary(
            protocol_id=req.protocol_id,
            text=text,
            provider=used_provider,
            model=req.provider,
            tokens_used=tokens,
            generated_at=now,
            regenerated=0,
        )
        db.add(summary)
        logger.info(
            "summary_created",
            protocol_id=str(req.protocol_id),
            provider=used_provider,
        )

    await db.commit()
    await db.refresh(summary)

    # Return shape compatible with SummarizeResponse schema in app.schemas
    return SummarizeResponse(
        id=summary.id,
        protocol_id=summary.protocol_id,
        text=summary.text,
        provider=summary.provider,
        model=summary.model,
        tokens_used=summary.tokens_used,
        duration_ms=None,
        generated_at=summary.generated_at,
    )
