"""Folders API — organize protocols into folders."""
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import get_logger
from app.db.models import Folder, Protocol
from app.db.session import get_db
from app.schemas import (
    FolderCreate,
    FolderResponse,
    FolderUpdate,
    MoveProtocolRequest,
    MoveProtocolsBatch,
)

logger = get_logger(__name__)
router = APIRouter(tags=["Folders"])


def _to_response(folder: Folder, protocol_count: int = 0) -> FolderResponse:
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        color=folder.color,
        icon=folder.icon,
        parent_id=folder.parent_id,
        sort_order=folder.sort_order,
        protocol_count=protocol_count,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


# ============================================================================
# GET /folders
# ============================================================================


@router.get(
    "/folders",
    response_model=List[FolderResponse],
    summary="List all folders",
)
async def list_folders(
    parent_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
) -> List[FolderResponse]:
    """List folders, optionally filtered by parent."""
    query = select(Folder).order_by(Folder.sort_order, Folder.name)
    if parent_id is not None:
        query = query.where(Folder.parent_id == parent_id)

    result = await db.execute(query)
    folders = result.scalars().all()

    # Count protocols for each folder
    counts_query = select(
        Protocol.folder_id,
        func.count(Protocol.id),
    ).where(Protocol.folder_id.isnot(None)).group_by(Protocol.folder_id)
    counts_result = await db.execute(counts_query)
    counts = {fid: cnt for fid, cnt in counts_result.all()}

    return [_to_response(f, counts.get(f.id, 0)) for f in folders]


# ============================================================================
# POST /folders
# ============================================================================


@router.post(
    "/folders",
    response_model=FolderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new folder",
)
async def create_folder(
    body: FolderCreate,
    db: AsyncSession = Depends(get_db),
) -> FolderResponse:
    """Create a new folder for organizing protocols."""
    # Validate parent exists if specified
    if body.parent_id:
        parent = await db.get(Folder, body.parent_id)
        if not parent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Родительская папка не найдена",
            )

    folder = Folder(
        name=body.name,
        color=body.color,
        icon=body.icon,
        parent_id=body.parent_id,
        sort_order=body.sort_order,
    )
    db.add(folder)
    await db.commit()
    await db.refresh(folder)

    logger.info("folder_created", folder_id=str(folder.id), name=folder.name)
    return _to_response(folder, 0)


# ============================================================================
# GET /folders/{folder_id}
# ============================================================================


@router.get(
    "/folders/{folder_id}",
    response_model=FolderResponse,
    summary="Get folder details",
)
async def get_folder(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> FolderResponse:
    """Get folder by ID with protocol count."""
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Папка не найдена",
        )

    # Count protocols
    count_query = select(func.count(Protocol.id)).where(
        Protocol.folder_id == folder_id
    )
    count = (await db.execute(count_query)).scalar() or 0

    return _to_response(folder, count)


# ============================================================================
# PATCH /folders/{folder_id}
# ============================================================================


@router.patch(
    "/folders/{folder_id}",
    response_model=FolderResponse,
    summary="Update folder",
)
async def update_folder(
    folder_id: uuid.UUID,
    body: FolderUpdate,
    db: AsyncSession = Depends(get_db),
) -> FolderResponse:
    """Update folder (name, color, parent, etc)."""
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Папка не найдена",
        )

    if body.name is not None:
        folder.name = body.name
    if body.color is not None:
        folder.color = body.color
    if body.icon is not None:
        folder.icon = body.icon
    if body.parent_id is not None:
        # Prevent circular references
        if body.parent_id == folder_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Папка не может быть родителем самой себя",
            )
        folder.parent_id = body.parent_id
    if body.sort_order is not None:
        folder.sort_order = body.sort_order

    folder.updated_at = func.now() if False else folder.updated_at  # SQLAlchemy handles
    from datetime import datetime
    folder.updated_at = datetime.now()

    await db.commit()
    await db.refresh(folder)

    logger.info("folder_updated", folder_id=str(folder.id))
    count = (await db.execute(
        select(func.count(Protocol.id)).where(Protocol.folder_id == folder_id)
    )).scalar() or 0

    return _to_response(folder, count)


# ============================================================================
# DELETE /folders/{folder_id}
# ============================================================================


@router.delete(
    "/folders/{folder_id}",
    summary="Delete folder",
)
async def delete_folder(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete folder. Protocols in folder become 'uncategorized'."""
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Папка не найдена",
        )

    # Remove folder_id from all protocols (they become uncategorized)
    update_query = (
        Protocol.__table__.update()
        .where(Protocol.folder_id == folder_id)
        .values(folder_id=None)
    )
    await db.execute(update_query)

    # Delete subfolders recursively (CASCADE in DB)
    await db.delete(folder)
    await db.commit()

    logger.info("folder_deleted", folder_id=str(folder_id))
    return {"status": "deleted", "folder_id": str(folder_id)}


# ============================================================================
# POST /folders/{folder_id}/protocols/{protocol_id}
# ============================================================================


@router.post(
    "/folders/{folder_id}/protocols/{protocol_id}",
    summary="Add protocol to folder",
)
async def add_protocol_to_folder(
    folder_id: uuid.UUID,
    protocol_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Add a protocol to a folder."""
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Папка не найдена",
        )

    protocol = await db.get(Protocol, protocol_id)
    if not protocol or protocol.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Протокол не найден",
        )

    protocol.folder_id = folder_id
    from datetime import datetime
    protocol.updated_at = datetime.now()
    await db.commit()

    logger.info("protocol_added_to_folder",
                protocol_id=str(protocol_id), folder_id=str(folder_id))
    return {"status": "ok", "protocol_id": str(protocol_id), "folder_id": str(folder_id)}


# ============================================================================
# DELETE /folders/{folder_id}/protocols/{protocol_id}
# ============================================================================


@router.delete(
    "/folders/{folder_id}/protocols/{protocol_id}",
    summary="Remove protocol from folder",
)
async def remove_protocol_from_folder(
    folder_id: uuid.UUID,
    protocol_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove a protocol from its folder (sets folder_id=null)."""
    protocol = await db.get(Protocol, protocol_id)
    if not protocol:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Протокол не найден",
        )

    if protocol.folder_id != folder_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Протокол не в этой папке",
        )

    protocol.folder_id = None
    from datetime import datetime
    protocol.updated_at = datetime.now()
    await db.commit()

    return {"status": "ok", "protocol_id": str(protocol_id)}


# ============================================================================
# PUT /protocols/{protocol_id}/folder
# ============================================================================


@router.put(
    "/protocols/{protocol_id}/folder",
    summary="Move protocol to folder",
)
async def move_protocol_to_folder(
    protocol_id: uuid.UUID,
    body: MoveProtocolRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Move a single protocol to a folder (or remove from folder if None)."""
    protocol = await db.get(Protocol, protocol_id)
    if not protocol:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Протокол не найден",
        )

    if body.folder_id is not None:
        folder = await db.get(Folder, body.folder_id)
        if not folder:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Папка не найдена",
            )

    protocol.folder_id = body.folder_id
    from datetime import datetime
    protocol.updated_at = datetime.now()
    await db.commit()

    return {"status": "ok", "protocol_id": str(protocol_id), "folder_id": str(body.folder_id)}


# ============================================================================
# POST /protocols/batch-move
# ============================================================================


@router.post(
    "/protocols/batch-move",
    summary="Move multiple protocols",
)
async def batch_move_protocols(
    body: MoveProtocolsBatch,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Move multiple protocols to a folder at once."""
    if body.folder_id is not None:
        folder = await db.get(Folder, body.folder_id)
        if not folder:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Папка не найдена",
            )

    from datetime import datetime
    for pid in body.protocol_ids:
        protocol = await db.get(Protocol, pid)
        if protocol:
            protocol.folder_id = body.folder_id
            protocol.updated_at = datetime.now()

    await db.commit()

    return {
        "status": "ok",
        "moved_count": len(body.protocol_ids),
        "folder_id": str(body.folder_id) if body.folder_id else None,
    }
