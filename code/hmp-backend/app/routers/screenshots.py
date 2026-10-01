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

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
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

# ============================================================================
# US-019: автоматическое создание скриншотов из видео по таймкодам
# ============================================================================

class SynthesizeRequest(BaseModel):
    """Запрос на авто-скриншоты."""
    max_screenshots: int = Field(10, ge=1, le=50)
    strategy: str = Field(
        "uniform",
        description="uniform | important | decisions | change_detection"
    )


class SynthesizeResponse(BaseModel):
    """Ответ с результатом синтеза скриншотов."""
    screenshots_created: int
    strategy: str
    protocol_id: str


@router.post("/protocols/{protocol_id}/screenshots/synthesize", response_model=SynthesizeResponse)
async def synthesize_screenshots(
    protocol_id: uuid.UUID,
    req: SynthesizeRequest,
    db: AsyncSession = Depends(get_db),
):
    """US-019: извлечь кадры из видео по таймкодам реплик.

    Параметры:
    - max_screenshots: максимум скриншотов (1-50)
    - strategy:
        - "uniform" — равномерно по времени
        - "important" — только реплики с пометкой "Важное"
        - "decisions" — только реплики-решения

    Возвращает: количество созданных скриншотов.
    """
    # Проверяем протокол
    proto = await db.get(Protocol, protocol_id)
    if not proto:
        raise HTTPException(404, f"Protocol not found: {protocol_id}")
    if not proto.audio_file_id:
        raise HTTPException(400, "Protocol has no audio/video file attached")

    from app.db.models import AudioFile
    audio = await db.get(AudioFile, proto.audio_file_id)
    if not audio or not audio.file_path:
        raise HTTPException(400, "AudioFile not found or no file_path")

    video_path = Path(audio.file_path)
    if not video_path.exists():
        raise HTTPException(404, f"Video file not found on disk: {video_path}")

    # Папка скриншотов
    from app.core.config import settings as _settings
    output_dir = video_path.parent / "screenshots"

    # Вызываем соответствующий сервис по стратегии
    from app.services.video_screenshots import (
        generate_screenshots_for_protocol,
        generate_screenshots_change_detection,
    )

    if req.strategy == "change_detection":
        screenshots = await generate_screenshots_change_detection(
            protocol_id=protocol_id,
            video_path=video_path,
            output_dir=output_dir,
            max_screenshots=req.max_screenshots,
            db=db,
        )
    else:
        screenshots = await generate_screenshots_for_protocol(
            protocol_id=protocol_id,
            video_path=video_path,
            output_dir=output_dir,
            max_screenshots=req.max_screenshots,
            strategy=req.strategy,
            db=db,
        )

    logger.info(
        f"US-019 synthesized {len(screenshots)} screenshots "
        f"for protocol={protocol_id} strategy={req.strategy}"
    )

    return SynthesizeResponse(
        screenshots_created=len(screenshots),
        strategy=req.strategy,
        protocol_id=str(protocol_id),
    )

# ============================================================================
# E266: debug endpoint для диагностики US-019
# ============================================================================

@router.get("/_debug/screenshot")
async def debug_screenshot():
    """Показывает статус всех зависимостей для скриншотов."""
    import sys

    result = {
        "python": sys.version.split()[0],
        "modules": {},
        "ffmpeg": None,
        "test_extract": None,
    }

    # Проверка модулей
    for mod_name in ["PIL", "imagehash", "fastapi", "sqlalchemy", "asyncpg"]:
        try:
            m = __import__(mod_name)
            ver = getattr(m, "__version__", "?")
            result["modules"][mod_name] = f"✅ {ver}"
        except ImportError:
            result["modules"][mod_name] = "❌ MISSING"

    # Проверка ffmpeg
    import subprocess as sp
    try:
        r = sp.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            result["ffmpeg"] = "✅ " + r.stdout.split("\n")[0]
    except FileNotFoundError:
        result["ffmpeg"] = "❌ ffmpeg not in PATH"
    except Exception as e:
        result["ffmpeg"] = f"❌ {e}"

    # Тест extract_frame на тестовом файле (если есть)
    try:
        from app.services.video_screenshots import extract_frame
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(b"")  # пустой файл
            tmp_path = Path(tmp.name)
        result["test_extract"] = "ready (call synthesize to test)"
        tmp_path.unlink()
    except Exception as e:
        result["test_extract"] = f"❌ {e}"

    return result
