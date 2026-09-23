"""User dictionary CRUD (US-047, API §11)."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status, Response
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import get_logger
from app.db.models import Dictionary, UserSetting
from app.db.session import get_db
from app.schemas import (
    DictionaryTermCreate,
    DictionaryTermResponse,
    DictionaryTermUpdate,
)

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DICTIONARY_LIMIT = 1000  # API §4.10 → 422 LIMIT_EXCEEDED


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def get_or_create_singleton_user_setting(db: AsyncSession) -> UserSetting:
    """MVP single-user: the first user_setting row is the "current"
    one. If the table is empty, create a default row.
    """
    # user_setting has no created_at column — sort by id for deterministic
    # singleton selection across requests.
    result = await db.execute(
        select(UserSetting).order_by(UserSetting.id.asc()).limit(1)
    )
    setting = result.scalar_one_or_none()
    if setting is not None:
        return setting

    setting = UserSetting(
        llm_provider="hermes",
        whisper_model="large-v3",
        theme="auto",
        notifications_enabled=True,
        hotkey_show_search="Ctrl+K",
        updated_at=datetime.now(timezone.utc),
    )
    db.add(setting)
    await db.commit()
    await db.refresh(setting)
    return setting


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/dictionary",
    response_model=dict,
    summary="List dictionary terms",
)
async def list_dictionary(
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List terms of the singleton user setting (US-047)."""
    user_setting = await get_or_create_singleton_user_setting(db)

    base = select(Dictionary).where(
        Dictionary.user_setting_id == user_setting.id
    )

    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar() or 0

    query = (
        base.order_by(Dictionary.term.asc())
        .offset(skip)
        .limit(limit)
    )
    items = (await db.execute(query)).scalars().all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": [DictionaryTermResponse.model_validate(i) for i in items],
    }


@router.post(
    "/dictionary",
    response_model=DictionaryTermResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add dictionary term",
)
async def create_term(
    body: DictionaryTermCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DictionaryTermResponse:
    """Add a term (US-047, API §4.10).

    - 422 INVALID_TERM handled by Pydantic validators on body.
    - 422 LIMIT_EXCEEDED — more than ``DICTIONARY_LIMIT`` terms for user.
    - 409 ALREADY_EXISTS — duplicate (case-insensitive, LOWER(term)).
    """
    user_setting = await get_or_create_singleton_user_setting(db)

    # Limit check
    total = (
        await db.execute(
            select(func.count(Dictionary.id)).where(
                Dictionary.user_setting_id == user_setting.id
            )
        )
    ).scalar() or 0
    if total >= DICTIONARY_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Достигнут лимит словаря ({DICTIONARY_LIMIT} терминов)",
        )

    # Case-insensitive duplicate check.
    existing = (
        await db.execute(
            select(Dictionary.id).where(
                Dictionary.user_setting_id == user_setting.id,
                func.lower(Dictionary.term) == body.term.lower(),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Термин «{body.term}» уже есть в словаре",
        )

    term = Dictionary(
        user_setting_id=user_setting.id,
        term=body.term,
        category=body.category,
        weight=body.weight,
    )
    db.add(term)
    await db.commit()
    await db.refresh(term)

    logger.info(
        "dictionary_term_created",
        term_id=str(term.id),
        user_setting_id=str(user_setting.id),
        term=term.term,
        category=term.category,
        correlation_id=getattr(request.state, "correlation_id", None),
    )

    return DictionaryTermResponse.model_validate(term)


@router.patch(
    "/dictionary/{term_id}",
    response_model=DictionaryTermResponse,
    summary="Update dictionary term",
)
async def update_term(
    term_id: uuid.UUID,
    body: DictionaryTermUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DictionaryTermResponse:
    """Partial update of term / category / weight (US-047)."""
    term = await db.get(Dictionary, term_id)
    if not term:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Термин не найден",
        )

    correlation_id = getattr(request.state, "correlation_id", None)
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Нет полей для обновления",
        )

    # If term text is changing, check for LOWER-case duplicate.
    if "term" in update_data and update_data["term"].lower() != term.term.lower():
        new_term_lower = update_data["term"].lower()
        dup = (
            await db.execute(
                select(Dictionary.id).where(
                    Dictionary.user_setting_id == term.user_setting_id,
                    Dictionary.id != term.id,
                    func.lower(Dictionary.term) == new_term_lower,
                )
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Термин «{update_data['term']}» уже есть в словаре",
            )

    for field, value in update_data.items():
        setattr(term, field, value)

    await db.commit()
    await db.refresh(term)

    logger.info(
        "dictionary_term_updated",
        term_id=str(term.id),
        user_setting_id=str(term.user_setting_id),
        fields=list(update_data.keys()),
        correlation_id=correlation_id,
    )

    return DictionaryTermResponse.model_validate(term)


@router.delete(
    "/dictionary/{term_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete dictionary term",
)
async def delete_term(
    term_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a term (US-047)."""
    term = await db.get(Dictionary, term_id)
    if not term:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Термин не найден",
        )

    correlation_id = getattr(request.state, "correlation_id", None)
    user_setting_id = term.user_setting_id
    term_text = term.term

    await db.delete(term)
    await db.commit()

    logger.info(
        "dictionary_term_deleted",
        term_id=str(term_id),
        user_setting_id=str(user_setting_id),
        term=term_text,
        correlation_id=correlation_id,
    )
