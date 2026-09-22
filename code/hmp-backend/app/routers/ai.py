"""AI text-processing endpoints (US-045, US-046, US-049, API §12).

Endpoints (all currently stubs — wire to app.services.llm_client.llm_router
when ready; the placeholder implementation returns the input untouched so
the contract is stable and tests can run):

    POST /ai/cleanup-text        — fix typos (US-045)
    POST /ai/restore-punctuation — restore punctuation (US-046)
    POST /ai/review-transcript   — review transcript quality (US-049)
    POST /ai/semantic-search     — semantic search (TODO: embeddings)
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import get_logger
from app.db.models import Protocol
from app.db.session import get_db

logger = get_logger(__name__)
router = APIRouter()


# ============================================================================
# Request / Response schemas
# ============================================================================


class AITextRequest(BaseModel):
    """Common request shape for AI text endpoints."""

    text: str = Field(..., min_length=1, max_length=20000, description="Input text")
    protocol_id: uuid.UUID | None = Field(
        None, description="Optional protocol context for the operation"
    )


class AITextResponse(BaseModel):
    """Common response shape."""

    text: str
    changed: bool
    notes: str | None = None
    provider: str = "mock"


class TranscriptReviewItem(BaseModel):
    """Single issue reported by /ai/review-transcript."""

    start: int = Field(..., description="0-based char offset of the issue")
    end: int = Field(..., description="0-based char offset (exclusive)")
    severity: str = Field(..., description="low | medium | high")
    message: str
    suggestion: str | None = None


class TranscriptReviewResponse(BaseModel):
    """Review output (US-049)."""

    reviewed_text: str
    issues: list[TranscriptReviewItem]
    quality_score: float = Field(..., ge=0.0, le=1.0)
    provider: str = "mock"


class SemanticSearchRequest(BaseModel):
    """Request body for /ai/semantic-search."""

    query: str = Field(..., min_length=1, max_length=1000)
    protocol_id: uuid.UUID | None = None
    top_k: int = Field(default=10, ge=1, le=50)


class SemanticSearchHit(BaseModel):
    """Single hit returned by /ai/semantic-search."""

    utterance_id: uuid.UUID | None = None
    start_sec: float
    end_sec: float
    text: str
    score: float = Field(..., ge=0.0, le=1.0)


class SemanticSearchResponse(BaseModel):
    """Search response (US-049)."""

    query: str
    hits: list[SemanticSearchHit]
    provider: str = "mock"


# ============================================================================
# Internal helpers
# ============================================================================


async def _ensure_protocol(protocol_id: uuid.UUID | None, db: AsyncSession) -> None:
    """If protocol_id provided, 404 if missing/deleted."""
    if protocol_id is None:
        return
    protocol = await db.get(Protocol, protocol_id)
    if not protocol or protocol.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Протокол не найден",
        )


# ============================================================================
# POST /ai/cleanup-text — US-045
# ============================================================================


@router.post(
    "/ai/cleanup-text",
    response_model=AITextResponse,
    summary="Fix typos / clean text (MOCK)",
)
async def cleanup_text(
    req: AITextRequest,
    db: AsyncSession = Depends(get_db),
) -> AITextResponse:
    """US-045 — remove common ASR artifacts.

    TODO: replace with `llm_router.generate(prompt=CLEANUP_PROMPT, ...)`.
    Currently echoes the input; the `changed=False` flag signals to the
    client that nothing happened, so the UI can decide whether to retry.
    """
    await _ensure_protocol(req.protocol_id, db)

    logger.info(
        "ai_cleanup_text",
        protocol_id=str(req.protocol_id) if req.protocol_id else None,
        text_len=len(req.text),
    )
    return AITextResponse(
        text=req.text,
        changed=False,
        notes="MOCK — реальная модель не подключена",
        provider="mock",
    )


# ============================================================================
# POST /ai/restore-punctuation — US-046
# ============================================================================


@router.post(
    "/ai/restore-punctuation",
    response_model=AITextResponse,
    summary="Restore punctuation (MOCK)",
)
async def restore_punctuation(
    req: AITextRequest,
    db: AsyncSession = Depends(get_db),
) -> AITextResponse:
    """US-046 — restore punctuation/capitalization for ASR output.

    TODO: integrate llm_router.generate() with RESTORE_PUNCT_PROMPT.
    """
    await _ensure_protocol(req.protocol_id, db)

    logger.info(
        "ai_restore_punctuation",
        protocol_id=str(req.protocol_id) if req.protocol_id else None,
        text_len=len(req.text),
    )
    return AITextResponse(
        text=req.text,
        changed=False,
        notes="MOCK — реальная модель не подключена",
        provider="mock",
    )


# ============================================================================
# POST /ai/review-transcript — US-049
# ============================================================================


@router.post(
    "/ai/review-transcript",
    response_model=TranscriptReviewResponse,
    summary="Review transcript quality (MOCK)",
)
async def review_transcript(
    req: AITextRequest,
    db: AsyncSession = Depends(get_db),
) -> TranscriptReviewResponse:
    """US-049 — flag low-confidence spans and grammar issues.

    TODO: combine `Utterance.low_confidence` flags with LLM-driven grammar
    checks via llm_router.generate().
    """
    await _ensure_protocol(req.protocol_id, db)

    logger.info(
        "ai_review_transcript",
        protocol_id=str(req.protocol_id) if req.protocol_id else None,
        text_len=len(req.text),
    )

    # Stub: no issues, perfect score
    return TranscriptReviewResponse(
        reviewed_text=req.text,
        issues=[],
        quality_score=1.0,
        provider="mock",
    )


# ============================================================================
# POST /ai/semantic-search — US-049
# ============================================================================


@router.post(
    "/ai/semantic-search",
    response_model=SemanticSearchResponse,
    summary="Semantic search across utterances (MOCK)",
)
async def semantic_search(
    req: SemanticSearchRequest,
    db: AsyncSession = Depends(get_db),
) -> SemanticSearchResponse:
    """US-049 — semantic search using vector embeddings.

    TODO:
      1. Compute embedding for `req.query` via local model (e.g. E5/GTE).
      2. Compare against pre-computed utterance embeddings stored alongside
         Utterance (column TBD; add JSONB column in a future migration).
      3. Return top_k matches.

    For now returns an empty hit list so the contract is stable.
    """
    await _ensure_protocol(req.protocol_id, db)

    logger.info(
        "ai_semantic_search",
        protocol_id=str(req.protocol_id) if req.protocol_id else None,
        query=req.query,
        top_k=req.top_k,
    )
    return SemanticSearchResponse(
        query=req.query,
        hits=[],
        provider="mock",
    )
