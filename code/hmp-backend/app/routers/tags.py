"""Tags CRUD (US-025, US-042, API §10)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status, Response
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import get_logger
from app.db.models import Protocol, Tag
from app.db.session import get_db

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Local schemas (no Tag schemas in app/schemas/__init__.py yet)
# ---------------------------------------------------------------------------

class TagCreate(BaseModel):
    """Request body for POST /tags."""
    protocol_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=50)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class TagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    protocol_id: uuid.UUID
    name: str
    source: str
    color: str | None
    created_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_response(tag: Tag) -> TagResponse:
    return TagResponse(
        id=tag.id,
        protocol_id=tag.protocol_id,
        name=tag.name,
        source=tag.source,
        color=tag.color,
        created_at=tag.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/protocols/{protocol_id}/tags",
    response_model=dict,
    summary="List tags for a protocol",
)
async def list_tags(
    protocol_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """API §10."""
    protocol = await db.get(Protocol, protocol_id)
    if not protocol:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Протокол не найден",
        )

    result = await db.execute(
        select(Tag)
        .where(Tag.protocol_id == protocol_id)
        .order_by(Tag.name.asc())
    )
    tags = result.scalars().all()

    return {
        "total": len(tags),
        "items": [_to_response(t) for t in tags],
    }


@router.post(
    "/tags",
    response_model=TagResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create tag",
)
async def create_tag(
    body: TagCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TagResponse:
    """Create a tag for a protocol (US-025). The unique constraint on
    ``(protocol_id, name)`` is enforced by the DB; we surface it as 409.
    """
    protocol = await db.get(Protocol, body.protocol_id)
    if not protocol:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Протокол не найден",
        )

    tag = Tag(
        protocol_id=body.protocol_id,
        name=body.name,
        color=body.color,
        source="manual",
    )
    db.add(tag)

    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        # Likely a unique violation on (protocol_id, name).
        if "idx_tag_protocol_name" in str(exc) or "unique" in str(exc).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Тег с именем «{body.name}» уже существует в этом протоколе",
            )
        raise

    await db.refresh(tag)

    logger.info(
        "tag_created",
        tag_id=str(tag.id),
        protocol_id=str(tag.protocol_id),
        name=tag.name,
        correlation_id=getattr(request.state, "correlation_id", None),
    )

    return _to_response(tag)


@router.delete(
    "/tags/{tag_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete tag",
)
async def delete_tag(
    tag_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a tag (US-025)."""
    tag = await db.get(Tag, tag_id)
    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Тег не найден",
        )

    correlation_id = getattr(request.state, "correlation_id", None)
    protocol_id = tag.protocol_id
    name = tag.name

    await db.delete(tag)
    await db.commit()

    logger.info(
        "tag_deleted",
        tag_id=str(tag_id),
        protocol_id=str(protocol_id),
        name=name,
        correlation_id=correlation_id,
    )
