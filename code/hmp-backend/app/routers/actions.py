"""Action items CRUD (US-023, US-024, API §8)."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status, Response
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import get_logger
from app.db.models import ActionItem, Protocol
from app.db.session import get_db
from app.schemas import (
    ActionItemCreate,
    ActionItemResponse,
    ActionItemUpdate,
    ExtractActionsRequest,
)

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Response model for /ai/extract-actions (stub)
# ---------------------------------------------------------------------------

class ExtractActionsResponse(BaseModel):
    """Stub response for action-extraction endpoint (real LLM wired in a
    later milestone — see SCAFFOLD_REPORT.md)."""
    extracted_count: int = 0
    average_confidence: float | None = None
    action_items: list[ActionItemResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _load_action_item(db: AsyncSession, action_id: uuid.UUID) -> ActionItem:
    item = await db.get(ActionItem, action_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action item не найден",
        )
    return item


def _to_response(item: ActionItem) -> ActionItemResponse:
    return ActionItemResponse.model_validate(item)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/protocols/{protocol_id}/action-items",
    response_model=dict,
    summary="List action items for a protocol",
)
async def list_action_items(
    protocol_id: uuid.UUID,
    status_filter: str | None = Query(None, alias="status"),
    owner: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """API §8 — list with optional filters ``status`` and ``owner``."""
    protocol = await db.get(Protocol, protocol_id)
    if not protocol:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Протокол не найден",
        )

    if status_filter is not None and status_filter not in {
        "open", "in_progress", "done", "cancelled"
    }:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Недопустимое значение status",
        )

    base = select(ActionItem).where(ActionItem.protocol_id == protocol_id)
    if status_filter is not None:
        base = base.where(ActionItem.status == status_filter)
    if owner is not None:
        base = base.where(ActionItem.owner == owner)

    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar() or 0

    query = (
        base.order_by(
            ActionItem.deadline.asc().nullslast(),
            ActionItem.created_at.asc(),
        )
        .offset(skip)
        .limit(limit)
    )
    items = (await db.execute(query)).scalars().all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": [_to_response(i) for i in items],
    }


@router.post(
    "/action-items",
    response_model=ActionItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create action item manually",
)
async def create_action_item(
    body: ActionItemCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ActionItemResponse:
    """Create an action item (US-023)."""
    protocol = await db.get(Protocol, body.protocol_id)
    if not protocol:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Протокол не найден",
        )

    item = ActionItem(
        protocol_id=body.protocol_id,
        owner=body.owner,
        task=body.task,
        deadline=body.deadline,
        status="open",
        source="manual",
        source_utterance_id=body.source_utterance_id,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    logger.info(
        "action_item_created",
        action_item_id=str(item.id),
        protocol_id=str(item.protocol_id),
        owner=item.owner,
        correlation_id=getattr(request.state, "correlation_id", None),
    )

    return _to_response(item)


@router.patch(
    "/action-items/{action_item_id}",
    response_model=ActionItemResponse,
    summary="Update action item",
)
async def update_action_item(
    action_item_id: uuid.UUID,
    body: ActionItemUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ActionItemResponse:
    """Partial update — supports status / deadline / owner / task (US-024)."""
    item = await _load_action_item(db, action_item_id)
    correlation_id = getattr(request.state, "correlation_id", None)

    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Нет полей для обновления",
        )

    for field, value in update_data.items():
        setattr(item, field, value)

    # Auto-stamp completed_at when transitioning to "done".
    if "status" in update_data and item.status == "done" and item.completed_at is None:
        item.completed_at = datetime.now(timezone.utc)
    # Clear completed_at if reopened.
    elif "status" in update_data and item.status != "done" and item.completed_at is not None:
        item.completed_at = None

    await db.commit()
    await db.refresh(item)

    logger.info(
        "action_item_updated",
        action_item_id=str(item.id),
        protocol_id=str(item.protocol_id),
        fields=list(update_data.keys()),
        correlation_id=correlation_id,
    )

    return _to_response(item)


@router.delete(
    "/action-items/{action_item_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete action item",
)
async def delete_action_item(
    action_item_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Hard-delete an action item (US-024)."""
    item = await _load_action_item(db, action_item_id)
    correlation_id = getattr(request.state, "correlation_id", None)
    protocol_id = item.protocol_id

    await db.delete(item)
    await db.commit()

    logger.info(
        "action_item_deleted",
        action_item_id=str(action_item_id),
        protocol_id=str(protocol_id),
        correlation_id=correlation_id,
    )


@router.post(
    "/ai/extract-actions",
    response_model=ExtractActionsResponse,
    summary="Extract action items from protocol via LLM (stub)",
)
async def extract_actions(
    body: ExtractActionsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ExtractActionsResponse:
    """Stub endpoint — real LLM extraction is wired in a later milestone.

    Today it verifies the protocol exists and returns an empty result so
    the API contract is stable for the frontend.
    """
    protocol = await db.get(Protocol, body.protocol_id)
    if not protocol:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Протокол не найден",
        )

    correlation_id = getattr(request.state, "correlation_id", None)
    logger.info(
        "extract_actions_stub_called",
        protocol_id=str(body.protocol_id),
        provider=body.provider,
        min_confidence=body.min_confidence,
        correlation_id=correlation_id,
    )

    # TODO(US-024, US-038): integrate real LLM provider (hermes / gigachat /
    # local_ollama). Pseudocode:
    #   1. Fetch all utterances for protocol_id
    #   2. Build prompt with min_confidence threshold + dictionary hints
    #   3. Call LLM via app.services.llm_adapter
    #   4. Parse JSON list[ActionItemDraft]
    #   5. Filter by confidence, persist with source='llm_extracted'

    return ExtractActionsResponse(
        extracted_count=0,
        average_confidence=None,
        action_items=[],
    )
