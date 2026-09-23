"""Protocol CRUD endpoints (US-001, US-010, US-011)."""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import delete as sql_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging_config import get_logger
from app.db.models import AudioFile, Protocol, Speaker, Tag, Utterance
from app.db.session import get_db
from app.schemas import (
    AudioFileResponse,
    FromUrlRequest,
    ProtocolListItem,
    ProtocolResponse,
    ProtocolUpdate,
)

logger = get_logger(__name__)
router = APIRouter()


@router.post("/protocols", response_model=ProtocolResponse, status_code=status.HTTP_201_CREATED, summary="Create protocol (upload file)")
async def create_protocol(
    file: UploadFile = File(..., description="Audio/video file (mp3/wav/mp4/mkv)"),
    title: str = Form(..., min_length=1, max_length=255),
    date: str = Form(..., description="YYYY-MM-DD"),
    location: str | None = Form(None),
    chair: str | None = Form(None),
    agenda: str | None = Form(None),
    # E218: добавлены параметры language и folder_id
    language: str = Form("ru", description="Язык протокола"),
    folder_id: uuid.UUID | None = Form(None, description="ID папки"),
    db: AsyncSession = Depends(get_db),
) -> ProtocolResponse:
    """Upload audio file and create protocol (US-001, API §4.1).

    File is streamed to disk in chunks of 8 MB (NFR §QG-7).
    """
    from datetime import datetime as dt
    from datetime import date as date_cls

    # Validate file size
    if file.size and file.size > settings.cloud_max_file_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Файл слишком большой. Максимум: {settings.cloud_max_file_size_mb} МБ",
        )

    # Generate protocol ID
    protocol_id = uuid.uuid4()

    # Stream save to disk (chunk ≤8 MB)
    extension = Path(file.filename or "unknown").suffix.lstrip(".")
    protocols_path = settings.protocols_path / str(protocol_id)
    protocols_path.mkdir(parents=True, exist_ok=True)

    # US-070: Use real filename (sanitized) instead of "source.{ext}"
    # so UI shows the same name as the file on disk
    from datetime import datetime
    original_filename = file.filename or f"unknown.{extension}"
    # Sanitize filename (remove invalid Windows chars)
    sanitized_filename = "".join(c for c in original_filename if c.isalnum() or c in "._- ")
    if not sanitized_filename or sanitized_filename.startswith("."):
        sanitized_filename = f"audio_{datetime.now():%Y%m%d_%H%M%S}.{extension or 'mp4'}"

    audio_path = protocols_path / sanitized_filename

    # If file already exists, add timestamp suffix
    if audio_path.exists():
        stem = audio_path.stem
        suffix = audio_path.suffix
        audio_path = protocols_path / f"{stem}_{datetime.now():%Y%m%d_%H%M%S}{suffix}"

    # Legacy cleanup: if old "source.{ext}" exists, remove it
    legacy_audio_path = protocols_path / f"source.{extension}"
    if legacy_audio_path.exists() and legacy_audio_path != audio_path:
        try:
            legacy_audio_path.unlink()
        except Exception:
            pass

    chunk_size = settings.video_range_chunk_size_mb * 1024 * 1024
    total_bytes = 0
    sha256_hash = None
    try:
        import hashlib

        sha256_hash = hashlib.sha256()
        with audio_path.open("wb") as f:
            while chunk := await file.read(chunk_size):
                f.write(chunk)
                sha256_hash.update(chunk)
                total_bytes += len(chunk)
    except Exception as e:
        # Cleanup on error
        if audio_path.exists():
            audio_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка сохранения файла: {e}",
        )

    # Create AudioFile record
    audio_file = AudioFile(
        file_path=str(audio_path),
        filename=file.filename or f"unknown.{extension}",
        extension=extension,
        size_bytes=total_bytes,
        mime_type=file.content_type,
        source="local",
        checksum_sha256=sha256_hash.hexdigest() if sha256_hash else None,
    )
    db.add(audio_file)
    await db.flush()

    # Create Protocol
    protocol = Protocol(
        id=protocol_id,
        title=title,
        date=dt.strptime(date, "%Y-%m-%d").date() if isinstance(date, str) else date,
        location=location,
        chair=chair,
        agenda=agenda,
        audio_file_id=audio_file.id,
        status="loaded",
        # E218: передаём language и folder_id из формы
        language=language,
        folder_id=folder_id,
    )
    db.add(protocol)
    await db.commit()
    await db.refresh(protocol)

    logger.info(
        "protocol_created",
        protocol_id=str(protocol.id),
        file_size=total_bytes,
        filename=file.filename,
    )

    return ProtocolResponse(
        id=protocol.id,
        title=protocol.title,
        date=protocol.date,
        location=protocol.location,
        chair=protocol.chair,
        agenda=protocol.agenda,
        duration_sec=protocol.duration_sec,
        wer_quality=protocol.wer_quality,
        status=protocol.status,
        audio_file=AudioFileResponse.model_validate(audio_file),
        created_at=protocol.created_at,
        updated_at=protocol.updated_at,
    )


@router.post(
    "/protocols/from-url",
    response_model=ProtocolResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create protocol from URL (US-002, US-073)",
)
async def create_protocol_from_url(
    body: FromUrlRequest,
    db: AsyncSession = Depends(get_db),
) -> ProtocolResponse:
    """Download audio/video from URL and create protocol.

    US-002: Импорт протокола по ссылке (YouTube/Telemost/Direct link).
    US-073: Полная реализация endpoint.

    File is downloaded as stream and saved to disk in chunks.
    """
    from datetime import datetime as dt
    import httpx

    url = body.url.strip()
    if not url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="URL не может быть пустым",
        )

    if not url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="URL должен начинаться с http:// или https://",
        )

    # Generate protocol ID
    protocol_id = uuid.uuid4()
    protocols_path = settings.protocols_path / str(protocol_id)
    protocols_path.mkdir(parents=True, exist_ok=True)

    title = body.title or url

    # Try to download file (streaming)
    chunk_size = settings.video_range_chunk_size_mb * 1024 * 1024
    total_bytes = 0
    sha256_hash = None
    extension = None
    mime_type = None

    try:
        import hashlib

        sha256_hash = hashlib.sha256()

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            follow_redirects=True,
        ) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Не удалось скачать: HTTP {response.status_code}",
                    )

                # Detect content-type
                mime_type = response.headers.get("content-type", "").split(";")[0].strip()

                # Determine extension from URL or content-type
                parsed_url_path = url.split("?")[0]
                if "." in parsed_url_path.split("/")[-1]:
                    extension = parsed_url_path.rsplit(".", 1)[-1].lower()
                elif mime_type:
                    mime_to_ext = {
                        "audio/mpeg": "mp3",
                        "audio/mp4": "m4a",
                        "audio/wav": "wav",
                        "audio/x-wav": "wav",
                        "audio/ogg": "ogg",
                        "audio/webm": "webm",  # E173: webm audio
                        "video/mp4": "mp4",
                        "video/webm": "webm",
                        "video/x-matroska": "mkv",
                    }
                    extension = mime_to_ext.get(mime_type, "mp4")
                else:
                    extension = "mp4"
                # E173: webm fallback если URL не даёт ни расширения ни MIME
                if extension == "mp4" and not mime_type:
                    # Попробуем угадать по сигнатуре
                    pass

                # Generate filename
                filename_base = "".join(c for c in title if c.isalnum() or c in "._- ")[:50] or "download"
                sanitized_filename = f"{filename_base}.{extension}"
                audio_path = protocols_path / sanitized_filename

                # Check size from Content-Length header
                content_length = response.headers.get("content-length")
                if content_length:
                    size_mb = int(content_length) / 1024 / 1024
                    if size_mb > settings.cloud_max_file_size_mb:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"Файл слишком большой ({size_mb:.1f} МБ). Максимум: {settings.cloud_max_file_size_mb} МБ",
                        )

                # Stream to disk
                with audio_path.open("wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size):
                        f.write(chunk)
                        sha256_hash.update(chunk)
                        total_bytes += len(chunk)

                        if total_bytes > settings.cloud_max_file_size_mb * 1024 * 1024:
                            f.close()
                            audio_path.unlink(missing_ok=True)
                            raise HTTPException(
                                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                detail=f"Файл превысил {settings.cloud_max_file_size_mb} МБ во время загрузки",
                            )

    except HTTPException:
        raise
    except Exception as e:
        # Cleanup on error
        if protocols_path.exists():
            import shutil
            shutil.rmtree(protocols_path, ignore_errors=True)
        logger.error("from_url_download_failed", url=url, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ошибка скачивания: {str(e)[:200]}",
        )

    # Parse date
    try:
        protocol_date = dt.strptime(body.date, "%Y-%m-%d").date() if body.date else dt.now().date()
    except ValueError:
        protocol_date = dt.now().date()

    # Create AudioFile
    audio_file = AudioFile(
        file_path=str(audio_path),
        filename=sanitized_filename,
        extension=extension or "mp4",
        size_bytes=total_bytes,
        mime_type=mime_type or "video/mp4",
        source="url",
        source_url=url,
        checksum_sha256=sha256_hash.hexdigest() if sha256_hash else None,
    )
    db.add(audio_file)
    await db.flush()

    # Create Protocol
    protocol = Protocol(
        id=protocol_id,
        title=title,
        date=protocol_date,
        location=body.location,
        chair=body.chair,
        audio_file_id=audio_file.id,
        status="loaded",
    )
    db.add(protocol)
    await db.commit()
    await db.refresh(protocol)

    logger.info(
        "protocol_created_from_url",
        protocol_id=str(protocol.id),
        url=url,
        size_bytes=total_bytes,
    )

    return ProtocolResponse(
        id=protocol.id,
        title=protocol.title,
        date=protocol.date,
        location=protocol.location,
        chair=protocol.chair,
        duration_sec=protocol.duration_sec,
        wer_quality=protocol.wer_quality,
        status=protocol.status,
        audio_file=AudioFileResponse.model_validate(audio_file),
        created_at=protocol.created_at,
        updated_at=protocol.updated_at,
    )


@router.get("/protocols", response_model=dict, summary="List protocols")
async def list_protocols(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    sort: str = Query("-date"),
    status_filter: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List protocols with pagination (API §4.2)."""
    # TODO: Implement full search + filtering
    query = select(Protocol).where(Protocol.deleted_at.is_(None))
    if status_filter:
        query = query.where(Protocol.status == status_filter)

    # Sort
    if sort == "-date":
        query = query.order_by(Protocol.date.desc())
    elif sort == "-created_at":
        query = query.order_by(Protocol.created_at.desc())
    elif sort == "title":
        query = query.order_by(Protocol.title)

    # Total count
    from sqlalchemy import func

    total_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(total_query)
    total = total_result.scalar() or 0

    # Paginate
    query = query.offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    protocols = result.scalars().all()

    items = [
        ProtocolListItem(
            id=p.id,
            title=p.title,
            date=p.date,
            status=p.status,
            duration_sec=p.duration_sec,
            wer_quality=p.wer_quality,
            speakers_count=0,
            utterances_count=0,
            tags=[],
            folder_id=p.folder_id,
            created_at=p.created_at,
        )
        for p in protocols
    ]

    return {"total": total, "page": page, "limit": limit, "items": items}


@router.get("/protocols/{protocol_id}", response_model=ProtocolResponse, summary="Get protocol")
async def get_protocol(
    protocol_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ProtocolResponse:
    """Get full protocol data (API §4.3)."""
    query = (
        select(Protocol)
        .options(selectinload(Protocol.audio_file))
        .where(Protocol.id == protocol_id)
    )
    result = await db.execute(query)
    protocol = result.scalar_one_or_none()

    if not protocol:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Протокол не найден",
        )

    return ProtocolResponse(
        id=protocol.id,
        title=protocol.title,
        date=protocol.date,
        location=protocol.location,
        chair=protocol.chair,
        agenda=protocol.agenda,
        duration_sec=protocol.duration_sec,
        wer_quality=protocol.wer_quality,
        status=protocol.status,
        audio_file=AudioFileResponse.model_validate(protocol.audio_file)
        if protocol.audio_file
        else None,
        created_at=protocol.created_at,
        updated_at=protocol.updated_at,
    )


@router.patch("/protocols/{protocol_id}", response_model=ProtocolResponse, summary="Update protocol")
async def update_protocol(
    protocol_id: uuid.UUID,
    body: ProtocolUpdate,
    db: AsyncSession = Depends(get_db),
) -> ProtocolResponse:
    """Update protocol metadata.

    E217: используем select + selectinload чтобы избежать MissingGreenlet
    при model_validate(protocol) с audio_file (lazy-load).
    """
    from sqlalchemy.orm import selectinload
    query = (
        select(Protocol)
        .options(selectinload(Protocol.audio_file))
        .where(Protocol.id == protocol_id)
    )
    protocol = (await db.execute(query)).scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Протокол не найден")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(protocol, field, value)

    await db.commit()
    await db.refresh(protocol)
    return ProtocolResponse.model_validate(protocol)


@router.delete("/protocols/{protocol_id}", status_code=status.HTTP_200_OK, summary="Soft-delete protocol")
async def delete_protocol(
    protocol_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict | None:
    """Soft delete protocol (sets deleted_at)."""
    from datetime import datetime, timezone

    protocol = await db.get(Protocol, protocol_id)
    if not protocol:
        raise HTTPException(status_code=404, detail="Протокол не найден")

    protocol.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("protocol_soft_deleted", protocol_id=str(protocol_id))
    return {"status": "soft_deleted", "protocol_id": str(protocol_id)}


# ============================================================================
# DELETE /protocols/{protocol_id}/permanent
# ============================================================================


@router.delete(
    "/protocols/{protocol_id}/permanent",
    status_code=status.HTTP_200_OK,
    summary="Permanently delete protocol and all related data",
)
async def hard_delete_protocol(
    protocol_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Permanently delete protocol AND all related data.

    Deletes:
    - Utterances (cascade)
    - Speakers (cascade)
    - Tags, ActionItems, Decisions (cascade)
    - Summary, TranscriptionTasks (cascade)
    - Screenshots + files
    - AudioFile + file on disk

    USE WITH CAUTION - cannot be undone!
    """
    from sqlalchemy import delete as sql_delete
    from pathlib import Path as PathLib

    from app.db.models import (
        Utterance, Speaker, Tag, ActionItem, Decision,
        Summary, TranscriptionTask, Screenshot, AudioFile,
        ProtocolVersion,
    )

    protocol = await db.get(Protocol, protocol_id)
    if not protocol:
        raise HTTPException(status_code=404, detail="Протокол не найден")

    deleted_counts = {}

    # Count and delete utterances
    utterances_result = await db.execute(
        select(func.count(Utterance.id)).where(Utterance.protocol_id == protocol_id)
    )
    deleted_counts["utterances"] = utterances_result.scalar() or 0
    await db.execute(sql_delete(Utterance).where(Utterance.protocol_id == protocol_id))

    # Speakers
    speakers_result = await db.execute(
        select(func.count(Speaker.id)).where(Speaker.protocol_id == protocol_id)
    )
    deleted_counts["speakers"] = speakers_result.scalar() or 0
    await db.execute(sql_delete(Speaker).where(Speaker.protocol_id == protocol_id))

    # Tags
    tags_result = await db.execute(
        select(func.count(Tag.id)).where(Tag.protocol_id == protocol_id)
    )
    deleted_counts["tags"] = tags_result.scalar() or 0
    await db.execute(sql_delete(Tag).where(Tag.protocol_id == protocol_id))

    # ActionItems
    actions_result = await db.execute(
        select(func.count(ActionItem.id)).where(ActionItem.protocol_id == protocol_id)
    )
    deleted_counts["action_items"] = actions_result.scalar() or 0
    await db.execute(sql_delete(ActionItem).where(ActionItem.protocol_id == protocol_id))

    # Decisions
    decisions_result = await db.execute(
        select(func.count(Decision.id)).where(Decision.protocol_id == protocol_id)
    )
    deleted_counts["decisions"] = decisions_result.scalar() or 0
    await db.execute(sql_delete(Decision).where(Decision.protocol_id == protocol_id))

    # Summary
    summary_result = await db.execute(
        select(func.count(Summary.id)).where(Summary.protocol_id == protocol_id)
    )
    deleted_counts["summaries"] = summary_result.scalar() or 0
    await db.execute(sql_delete(Summary).where(Summary.protocol_id == protocol_id))

    # TranscriptionTasks
    await db.execute(sql_delete(TranscriptionTask).where(TranscriptionTask.protocol_id == protocol_id))

    # ProtocolVersion
    versions_result = await db.execute(
        select(func.count(ProtocolVersion.id)).where(ProtocolVersion.protocol_id == protocol_id)
    )
    deleted_counts["protocol_versions"] = versions_result.scalar() or 0
    await db.execute(sql_delete(ProtocolVersion).where(ProtocolVersion.protocol_id == protocol_id))

    # Screenshots - delete files and records
    screenshots_result = await db.execute(
        select(Screenshot).where(Screenshot.protocol_id == protocol_id)
    )
    screenshots = screenshots_result.scalars().all()
    deleted_counts["screenshots"] = len(screenshots)
    for shot in screenshots:
        try:
            shot_path = PathLib(shot.file_path)
            if shot_path.exists():
                shot_path.unlink()
        except Exception as e:
            logger.warning("screenshot_delete_failed", path=str(shot.file_path), error=str(e))
    await db.execute(sql_delete(Screenshot).where(Screenshot.protocol_id == protocol_id))

    # AudioFile + delete file from disk
    if protocol.audio_file_id:
        audio_result = await db.execute(
            select(AudioFile).where(AudioFile.id == protocol.audio_file_id)
        )
        audio_file = audio_result.scalar_one_or_none()
        if audio_file:
            try:
                audio_path = PathLib(audio_file.file_path)
                if audio_path.exists():
                    audio_path.unlink()
            except Exception as e:
                logger.warning("audio_delete_failed", path=str(audio_file.file_path), error=str(e))
            await db.execute(sql_delete(AudioFile).where(AudioFile.id == protocol.audio_file_id))

    # Remove protocol folder + ALL files inside (US-053 enhanced)
    # Используем shutil.rmtree чтобы удалить папку со всем содержимым
    # (на случай если остались legacy source.{ext} или другие файлы)
    try:
        from shutil import rmtree
        protocol_dir = PathLib(settings.protocols_path) / str(protocol_id)
        if protocol_dir.exists():
            if protocol_dir.is_dir():
                rmtree(protocol_dir, ignore_errors=True)
                logger.info("protocol_folder_deleted", path=str(protocol_dir))
            else:
                # Если на диске файл вместо папки — удалить
                protocol_dir.unlink(missing_ok=True)
    except Exception as e:
        logger.warning("protocol_folder_delete_failed", path=str(protocol_dir), error=str(e))

    # Finally delete protocol
    await db.execute(sql_delete(Protocol).where(Protocol.id == protocol_id))
    await db.commit()

    logger.info("protocol_permanently_deleted",
                protocol_id=str(protocol_id),
                deleted_counts=deleted_counts)
    return {
        "status": "deleted",
        "protocol_id": str(protocol_id),
        "deleted_counts": deleted_counts,
    }


# NOTE: /calendar endpoint lives in app/routers/calendar.py (US-011) to avoid
# route collisions and keep domain boundaries clean (ADR §5.1).
