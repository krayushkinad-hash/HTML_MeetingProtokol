"""Screenshots CRUD (US-016, US-021, API §6).

Endpoints:
    GET    /protocols/{protocol_id}/screenshots — list screenshots for a protocol
    POST   /screenshots/upload                   — upload PNG screenshot (multipart)
    GET    /screenshots/{id}                     — get screenshot metadata
    DELETE /screenshots/{id}                     — delete screenshot (file + DB row)

Screenshot files are persisted under:
    settings.protocols_path / {protocol_id} / screenshots / {uuid}.png
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status, Response
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging_config import get_logger
from app.db.models import Protocol, Screenshot
from app.db.session import get_db

logger = get_logger(__name__)
router = APIRouter()


# ============================================================================
# Response schemas (local — keeps router self-contained)
# ============================================================================


class ScreenshotResponse(BaseModel):
    """Screenshot metadata returned by API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    protocol_id: uuid.UUID
    file_path: str
    timestamp_sec: float
    width_px: int | None
    height_px: int | None
    file_size_kb: int | None
    caption: str | None
    created_at: str  # ISO-8601 string


def _to_response(s: Screenshot) -> ScreenshotResponse:
    """ORM → API response."""
    return ScreenshotResponse(
        id=s.id,
        protocol_id=s.protocol_id,
        file_path=s.file_path,
        timestamp_sec=float(s.timestamp_sec),
        width_px=s.width_px,
        height_px=s.height_px,
        file_size_kb=s.file_size_kb,
        caption=s.caption,
        created_at=s.created_at.isoformat() if s.created_at else "",
    )


# ============================================================================
# List — GET /protocols/{protocol_id}/screenshots
# ============================================================================


@router.get(
    "/protocols/{protocol_id}/screenshots",
    response_model=list[ScreenshotResponse],
    summary="List screenshots for a protocol",
)
async def list_screenshots(
    protocol_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[ScreenshotResponse]:
    """US-021 — list all screenshots of a protocol, sorted by timestamp_sec ASC."""
    # Ensure protocol exists (otherwise 404 instead of empty list)
    protocol = await db.get(Protocol, protocol_id)
    if not protocol or protocol.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Протокол не найден",
        )

    query = (
        select(Screenshot)
        .where(Screenshot.protocol_id == protocol_id)
        .order_by(Screenshot.timestamp_sec.asc())
    )
    result = await db.execute(query)
    items = result.scalars().all()

    logger.info(
        "screenshots_listed",
        protocol_id=str(protocol_id),
        count=len(items),
    )
    return [_to_response(s) for s in items]


# ============================================================================
# Upload — POST /screenshots/upload
# ============================================================================


@router.post(
    "/screenshots/upload",
    response_model=ScreenshotResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a screenshot (multipart)",
)
async def upload_screenshot(
    file: UploadFile = File(..., description="PNG image"),
    protocol_id: uuid.UUID = Form(...),
    timestamp_sec: float = Form(..., ge=0, description="Position in protocol timeline (seconds)"),
    caption: str | None = Form(None, max_length=2000),
    width_px: int | None = Form(None, ge=1),
    height_px: int | None = Form(None, ge=1),
    db: AsyncSession = Depends(get_db),
) -> ScreenshotResponse:
    """US-016 — save screenshot file + insert Screenshot row.

    File is stored at:
        settings.protocols_path / {protocol_id} / screenshots / {uuid}.png
    """
    # Validate protocol exists and is not deleted
    protocol = await db.get(Protocol, protocol_id)
    if not protocol or protocol.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Протокол не найден",
        )

    # Validate content type (best-effort; browsers vary)
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Ожидается image/*, получен {file.content_type}",
        )

    # Build target directory
    target_dir: Path = settings.protocols_path / str(protocol_id) / "screenshots"
    target_dir.mkdir(parents=True, exist_ok=True)

    # Filename: {uuid}.png (use suffix from filename or default png)
    suffix = Path(file.filename or "").suffix.lower() or ".png"
    screenshot_id = uuid.uuid4()
    target_path = target_dir / f"{screenshot_id}{suffix}"

    # Stream save in chunks (NFR §QG-7 chunk size)
    chunk_size = settings.video_range_chunk_size_mb * 1024 * 1024
    total_bytes = 0
    try:
        with target_path.open("wb") as f:
            while chunk := await file.read(chunk_size):
                f.write(chunk)
                total_bytes += len(chunk)
    except Exception as e:
        # Cleanup partial file
        if target_path.exists():
            try:
                target_path.unlink()
            except OSError:
                pass
        logger.exception(
            "screenshot_save_failed",
            protocol_id=str(protocol_id),
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка сохранения файла: {e}",
        )

    # Insert DB record
    screenshot = Screenshot(
        id=screenshot_id,
        protocol_id=protocol_id,
        file_path=str(target_path),
        timestamp_sec=timestamp_sec,
        width_px=width_px,
        height_px=height_px,
        file_size_kb=total_bytes // 1024 if total_bytes else None,
        caption=caption,
    )
    db.add(screenshot)
    await db.commit()
    await db.refresh(screenshot)

    logger.info(
        "screenshot_uploaded",
        screenshot_id=str(screenshot.id),
        protocol_id=str(protocol_id),
        timestamp_sec=timestamp_sec,
        file_size_kb=screenshot.file_size_kb,
    )
    return _to_response(screenshot)


# ============================================================================
# Get — GET /screenshots/{id}
# ============================================================================


@router.get(
    "/screenshots/{screenshot_id}",
    response_model=ScreenshotResponse,
    summary="Get screenshot metadata",
)
async def get_screenshot(
    screenshot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ScreenshotResponse:
    """US-016 — return screenshot metadata by id."""
    screenshot = await db.get(Screenshot, screenshot_id)
    if not screenshot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Скриншот не найден",
        )
    return _to_response(screenshot)


# ============================================================================
# Delete — DELETE /screenshots/{id}
# ============================================================================


@router.delete(
    "/screenshots/{screenshot_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete screenshot (file + DB record)",
)
async def delete_screenshot(
    screenshot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """US-021 — remove file from disk and DB row."""
    screenshot = await db.get(Screenshot, screenshot_id)
    if not screenshot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Скриншот не найден",
        )

    # Delete file (best-effort: log but don't fail if file is already gone)
    file_path = Path(screenshot.file_path)
    if file_path.exists():
        try:
            file_path.unlink()
        except OSError as e:
            logger.warning(
                "screenshot_file_delete_failed",
                screenshot_id=str(screenshot_id),
                path=str(file_path),
                error=str(e),
            )
    else:
        logger.warning(
            "screenshot_file_missing",
            screenshot_id=str(screenshot_id),
            path=str(file_path),
        )

    await db.delete(screenshot)
    await db.commit()

    logger.info("screenshot_deleted", screenshot_id=str(screenshot_id))
    return None
