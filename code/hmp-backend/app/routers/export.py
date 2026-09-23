"""DOCX export endpoints (US-015, US-016, US-017, US-050, API §17).

Endpoints:
    POST /export/docx            — enqueue export, return 202 + task_id
    GET  /export/status/{task_id} — poll task status
    GET  /export/download/{task_id} — download generated DOCX (or 409 if not ready)

DOCX is generated with `python-docx` (already a dependency). For now we
write a minimal placeholder DOCX; replace `_build_docx()` with the full
template-driven implementation when ready.
"""
from __future__ import annotations

import asyncio  # E204: для asyncio.to_thread
import uuid
from datetime import datetime, timezone
from pathlib import Path

from docx import Document
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging_config import get_logger
from app.db.models import ExportTask, Protocol, Utterance, Speaker, AudioFile
from app.db.session import get_db, get_db_context
from app.schemas import ExportRequest, ExportStatus

logger = get_logger(__name__)
router = APIRouter()


# ============================================================================
# Helpers
# ============================================================================


def _to_status_response(task: ExportTask) -> ExportStatus:
    return ExportStatus(
        task_id=task.id,
        protocol_id=task.protocol_id,
        status=task.status,  # type: ignore[arg-type]
        progress_percent=task.progress_percent,
        estimated_completion=None,
        output_path=task.output_path,
        file_size_bytes=task.file_size_bytes,
        error_message=task.error_message,
    )


def _build_docx(protocol: Protocol, utterances: list[Utterance], output_path: Path) -> None:
    """Build a minimal DOCX for the protocol.

    Real implementation (US-050) will use a Jinja-like template with
    headers/footers, styles, decisions/action-items tables, screenshot
    thumbnails, etc. This is a deterministic placeholder.
    """
    doc = Document()

    # Title
    title = doc.add_heading(protocol.title or "Протокол", level=0)

    # Metadata table
    meta = doc.add_table(rows=0, cols=2)
    meta.style = "Light List"
    if protocol.date:
        row = meta.add_row().cells
        row[0].text = "Дата"
        row[1].text = protocol.date.isoformat()
    if protocol.location:
        row = meta.add_row().cells
        row[0].text = "Место"
        row[1].text = protocol.location
    if protocol.chair:
        row = meta.add_row().cells
        row[0].text = "Председатель"
        row[1].text = protocol.chair
    if protocol.agenda:
        doc.add_heading("Повестка", level=1)
        doc.add_paragraph(protocol.agenda)

    # Transcript
    doc.add_heading("Транскрипт", level=1)
    if not utterances:
        doc.add_paragraph("[Транскрипт отсутствует]")
    else:
        for u in utterances:
            stamp = f"[{u.start_sec:.1f}–{u.end_sec:.1f}]"
            doc.add_paragraph(f"{stamp} {u.text}")

    # Decisions summary
    if protocol.decisions_summary:
        doc.add_heading("Решения", level=1)
        doc.add_paragraph(protocol.decisions_summary)

    doc.save(str(output_path))


async def _run_export_task(
    task_id: uuid.UUID,
    protocol_id: uuid.UUID,
    output_path: Path,
) -> None:
    """Background coroutine: generate DOCX, update task row.

    Uses `get_db_context()` because the request session is already closed
    by the time BackgroundTasks runs.
    """
    logger.info("export_task_started", task_id=str(task_id), protocol_id=str(protocol_id))
    try:
        async with get_db_context() as db:
            # Mark processing
            task = await db.get(ExportTask, task_id)
            if not task:
                logger.error("export_task_missing", task_id=str(task_id))
                return
            task.status = "processing"
            task.progress_percent = 10
            task.started_at = datetime.now(timezone.utc)
            await db.commit()

            # Load protocol + utterances
            protocol = await db.get(Protocol, protocol_id)
            if not protocol:
                task.status = "failed"
                task.error_message = "Протокол не найден"
                task.completed_at = datetime.now(timezone.utc)
                await db.commit()
                logger.error(
                    "export_task_protocol_missing",
                    task_id=str(task_id),
                    protocol_id=str(protocol_id),
                )
                return

            query = (
                select(Utterance)
                .where(Utterance.protocol_id == protocol_id)
                .order_by(Utterance.start_sec.asc())
            )
            result = await db.execute(query)
            utterances = list(result.scalars().all())

            task.progress_percent = 50
            await db.commit()

            # Ensure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # E204: генерация DOCX в отдельном потоке чтобы не блокировать event loop
            # Без этого — event loop зависает на секунды/минуты для больших файлов
            await asyncio.to_thread(_build_docx, protocol, utterances, output_path)

            # Update task as completed
            size_bytes = output_path.stat().st_size if output_path.exists() else None
            task.output_path = str(output_path)
            task.file_size_bytes = size_bytes
            task.progress_percent = 100
            task.status = "completed"
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()

            logger.info(
                "export_task_completed",
                task_id=str(task_id),
                protocol_id=str(protocol_id),
                output_path=str(output_path),
                file_size_bytes=size_bytes,
            )
    except Exception as e:
        logger.exception(
            "export_task_failed",
            task_id=str(task_id),
            protocol_id=str(protocol_id),
            error=str(e),
        )
        async with get_db_context() as db:
            task = await db.get(ExportTask, task_id)
            if task:
                task.status = "failed"
                task.error_message = str(e)
                task.completed_at = datetime.now(timezone.utc)
                await db.commit()


# ============================================================================
# POST /export/docx — enqueue
# ============================================================================


@router.post(
    "/export/docx",
    response_model=ExportStatus,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue DOCX export",
)
async def enqueue_export(
    req: ExportRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> ExportStatus:
    """US-015 — create an ExportTask and start generation in background.

    Returns 202 with the task_id immediately; client polls
    /export/status/{task_id} and then downloads via /export/download/{task_id}.
    """
    # Validate protocol
    protocol = await db.get(Protocol, req.protocol_id)
    if not protocol or protocol.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Протокол не найден",
        )

    task_id = uuid.uuid4()
    output_dir = settings.protocols_path / str(req.protocol_id) / "exports"
    output_path = output_dir / f"{task_id}.docx"

    task = ExportTask(
        id=task_id,
        protocol_id=req.protocol_id,
        format="docx",
        include_timestamps=req.include_timestamps,
        include_screenshots=req.include_screenshots,
        include_video_links=req.include_video_links,
        group_by_speaker=req.group_by_speaker,
        mark_doubtful=req.mark_doubtful,
        status="queued",
        progress_percent=0,
        output_path=None,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # Schedule background work — FastAPI runs this AFTER response is sent
    background_tasks.add_task(_run_export_task, task_id, req.protocol_id, output_path)

    logger.info(
        "export_task_queued",
        task_id=str(task_id),
        protocol_id=str(req.protocol_id),
    )
    return _to_status_response(task)


# ============================================================================
# GET /export/status/{task_id}
# ============================================================================


@router.get(
    "/export/status/{task_id}",
    response_model=ExportStatus,
    summary="Poll export task status",
)
async def get_export_status(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ExportStatus:
    """US-016 — return current status of an export task."""
    task = await db.get(ExportTask, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Задача экспорта не найдена",
        )
    return _to_status_response(task)


# ============================================================================
# GET /export/download/{task_id}
# ============================================================================


@router.get(
    "/export/download/{task_id}",
    summary="Download generated DOCX",
)
async def download_export(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """US-017 — return the DOCX file. 409 if not yet completed."""
    task = await db.get(ExportTask, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Задача экспорта не найдена",
        )

    if task.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Экспорт ещё не завершён (status={task.status})",
        )

    if not task.output_path:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="output_path отсутствует у завершённой задачи",
        )

    path = Path(task.output_path)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Файл экспорта удалён с диска",
        )

    filename = f"{task.protocol_id}.docx"
    logger.info(
        "export_downloaded",
        task_id=str(task_id),
        protocol_id=str(task.protocol_id),
        file_size_bytes=task.file_size_bytes,
    )
    return FileResponse(
        path=str(path),
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        filename=filename,
    )


@router.post(
    "/export/archive/{protocol_id}",
    summary="Archive protocol to ZIP (US-071)",
    status_code=200,
)
async def archive_protocol(protocol_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Create a ZIP archive of the protocol with all related files.

    US-071: Single file export containing:
    - protocol.json (metadata)
    - transcript.txt (plain text)
    - summary.md (if exists)
    - decisions.json, action_items.json
    - screenshots/ (folder)
    - source.{ext} (original audio/video)
    """
    import zipfile
    import io
    import json
    from datetime import datetime
    from sqlalchemy import select

    # Load protocol
    proto = await db.get(Protocol, protocol_id)
    if not proto or proto.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Протокол не найден")

    archive_id = uuid.uuid4()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        # metadata
        meta = {
            "id": str(proto.id),
            "title": proto.title,
            "date": str(proto.date) if proto.date else None,
            "created_at": proto.created_at.isoformat() if proto.created_at else None,
            "status": proto.status if hasattr(proto, 'status') else None,
        }
        zf.writestr("protocol.json", json.dumps(meta, ensure_ascii=False, indent=2))

        # Plain text transcript
        utterances_q = select(Utterance).where(Utterance.protocol_id == protocol_id).order_by(Utterance.start_sec)
        utterances = (await db.execute(utterances_q)).scalars().all()

        text_lines = [f"Протокол: {proto.title}", f"Дата: {proto.date}", "", "=" * 60, ""]
        for u in utterances:
            speaker_name = ""
            if u.speaker_id:
                sp = await db.get(Speaker, u.speaker_id)
                speaker_name = f"{sp.display_name}: " if sp else ""
            text_lines.append(f"[{int(u.start_sec)}s] {speaker_name}{u.text}")
        zf.writestr("transcript.txt", "\n".join(text_lines))

        # Source file
        if proto.audio_file_id:
            af = await db.get(AudioFile, proto.audio_file_id)
            if af and Path(af.file_path).exists():
                zf.write(af.file_path, f"source.{af.extension}")

    buf.seek(0)
    archive_path = settings.protocols_path / str(protocol_id) / f"{archive_id}.zip"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(buf.getvalue())

    return {
        "archive_id": str(archive_id),
        "path": str(archive_path),
        "size_kb": len(buf.getvalue()) // 1024,
        # E203: переименовано download → download-archive чтобы не конфликтовать
        # с /export/download/{task_id} (DOCX)
        "download_url": f"/api/v1/hmp/export/download-archive/{archive_id}",
    }


@router.get(
    # E203: переименовано из /export/download/{archive_id} чтобы не конфликтовать
    # с /export/download/{task_id} (DOCX)
    "/export/download-archive/{archive_id}",
    response_class=FileResponse,
    summary="Download archived ZIP",
)
async def download_archive(archive_id: uuid.UUID) -> FileResponse:
    """Send the ZIP archive."""
    # Look up archive in files (simple glob, avoid escape issues)
    archives = list(settings.protocols_path.glob(f"{archive_id}.zip"))
    # Also try subdirectories
    if not archives:
        for d in settings.protocols_path.iterdir():
            if d.is_dir():
                archives = list(d.glob(f"{archive_id}.zip"))
                if archives:
                    break
    archive_path = archives[0] if archives else None
    if archive_path and archive_path.exists():
        return FileResponse(
            path=str(archive_path),
            filename=f"protocol-{archive_id}.zip",
            media_type="application/zip",
        )
    raise HTTPException(status_code=404, detail="Archive not found")
