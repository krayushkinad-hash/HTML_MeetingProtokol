"""Audio file endpoints (US-001, US-002 — API §4.1, §4.2).

Two responsibilities:
  * GET /audio-files/{id}            — metadata only (JSON)
  * GET /audio-files/{id}/video?t=…  — stream audio/video with HTTP Range
                                       support (NFR §3.3 video scrub)

Static-files are also mounted at ``/media/protocols/{id}/source.{ext}`` in
``app.main``; this router exists so the client can resolve an audio-file ID
to a playable URL with optional seek offset.
"""
import mimetypes
import re
import uuid
from datetime import datetime, timezone  # E206: для datetime.now(timezone.utc)
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import (
    FileResponse,
    RedirectResponse,
    Response,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import get_logger
from app.db.models import AudioFile
from app.db.session import get_db
from app.schemas import AudioFileResponse

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Range header parsing (RFC 7233)
# ---------------------------------------------------------------------------

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _parse_range(range_header: str, file_size: int) -> tuple[int, int] | None:
    """Parse a single-range ``Range: bytes=start-end`` header.

    Returns ``(start, end)`` inclusive byte offsets, or ``None`` if the
    header is malformed (in which case the response should be 200 OK with
    the full body — RFC 7233 §3.1).
    """
    match = _RANGE_RE.match(range_header.strip())
    if not match:
        return None
    start_str, end_str = match.group(1), match.group(2)

    if not start_str and not end_str:
        return None

    if not start_str:
        # suffix-byte-range: bytes=-N → last N bytes
        length = int(end_str)
        if length <= 0 or length > file_size:
            return None
        return file_size - length, file_size - 1

    start = int(start_str)
    end = int(end_str) if end_str else file_size - 1
    if start > end or start >= file_size:
        return None
    end = min(end, file_size - 1)
    return start, end


def _guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "application/octet-stream"


# ---------------------------------------------------------------------------
# GET /media/protocols/{protocol_id}/source.{ext}
# ---------------------------------------------------------------------------


@router.get(
    "/media/protocols/{protocol_id}/source.{ext}",
    summary="Stream source file by protocol_id (legacy URL)",
)
async def stream_source_by_protocol(
    protocol_id: uuid.UUID,
    ext: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Stream source media file by protocol_id (legacy path used by frontend).

    URL pattern: /api/v1/hmp/media/protocols/{uuid}/source.{ext}
    """
    from fastapi.responses import FileResponse
    from app.db.models import Protocol

    # Get protocol
    result = await db.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )
    protocol = result.scalar_one_or_none()
    if not protocol or not protocol.audio_file_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл не найден",
        )

    # Get audio file
    audio_result = await db.execute(
        select(AudioFile).where(AudioFile.id == protocol.audio_file_id)
    )
    audio_file = audio_result.scalar_one_or_none()
    if not audio_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл не найден",
        )

    # Check file exists
    file_path = Path(audio_file.file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Файл не найден на диске: {file_path}",
        )

    # E180-fix: НЕ передаём filename= — иначе Content-Disposition: attachment
    # ломает стриминг в <video>/<audio>
    return FileResponse(
        path=str(file_path),
        media_type=audio_file.mime_type or _guess_mime(file_path),
        headers={"Accept-Ranges": "bytes"},
    )


# ---------------------------------------------------------------------------
# POST /audio-files/{id}/open-folder (US-069)
# ---------------------------------------------------------------------------


@router.post(
    "/audio-files/{audio_file_id}/open-folder",
    summary="Open folder containing the audio/video file (US-069)",
)
async def open_audio_folder(
    audio_file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Open OS file manager at the folder containing the audio file.

    US-069: Allows user to quickly find the file in Explorer/Finder.
    Works cross-platform: Windows (explorer), Linux (xdg-open), macOS (open).

    Returns command that was executed + folder path for client to verify.
    Does NOT require the file to exist (e.g. for deletion confirmation).
    """
    import platform
    import subprocess

    # Get audio file record
    result = await db.execute(
        select(AudioFile).where(AudioFile.id == audio_file_id)
    )
    audio_file = result.scalar_one_or_none()
    if not audio_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл не найден в БД",
        )

    if not audio_file.file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Путь к файлу не сохранён",
        )

    file_path = Path(audio_file.file_path)
    folder = file_path.parent
    file_exists = file_path.exists()
    folder_exists = folder.exists()

    # Determine command by platform
    os_name = platform.system().lower()
    command = None
    error = None

    try:
        if os_name == "windows":
            if file_exists:
                # explorer /select,path — открывает папку с выделением файла
                command = ["explorer", "/select,", str(file_path)]
            else:
                # Открываем папку без выделения
                command = ["explorer", str(folder)]
            subprocess.Popen(command, shell=True)

        elif os_name == "darwin":
            # macOS: open -R file_path — открывает Finder с выделением
            command = ["open", "-R", str(file_path)]
            subprocess.Popen(command)

        else:  # Linux / Astra
            # Linux: xdg-open открывает папку
            command = ["xdg-open", str(folder)]
            subprocess.Popen(command)

        logger.info(
            "open_folder",
            audio_file_id=str(audio_file_id),
            command=command,
            file_exists=file_exists,
            folder_exists=folder_exists,
        )

    except Exception as e:
        error = str(e)
        logger.error(
            "open_folder_failed",
            audio_file_id=str(audio_file_id),
            error=error,
        )

    return {
        "os": os_name,
        "folder": str(folder),
        "file_path": str(file_path),
        "file_exists": file_exists,
        "folder_exists": folder_exists,
        "command": command,
        "error": error,
    }


# ---------------------------------------------------------------------------
# GET /audio-files/{id}
# ---------------------------------------------------------------------------

@router.get(
    "/audio-files/{audio_file_id}",
    response_model=AudioFileResponse,
    summary="Get audio file metadata (US-001)",
)
async def get_audio_file(
    audio_file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> AudioFileResponse:
    """Return metadata for a single audio file."""
    row = await db.execute(
        select(AudioFile).where(AudioFile.id == audio_file_id)
    )
    audio: AudioFile | None = row.scalar_one_or_none()
    if not audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Аудио-файл {audio_file_id} не найден",
        )

    return AudioFileResponse.model_validate(audio)


# ---------------------------------------------------------------------------
# GET /audio-files/{id}/video?t=<seconds>
# ---------------------------------------------------------------------------

@router.get(
    "/audio-files/{audio_file_id}/video",
    summary="Stream audio/video with HTTP Range support (US-002)",
)
async def stream_audio_file(
    audio_file_id: uuid.UUID,
    request: Request,
    t: float | None = Query(None, ge=0, description="Начальная позиция (секунды)"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Stream the file with ``Accept-Ranges: bytes``.

    The audio-file row may belong to any protocol; we follow
    ``AudioFile.file_path`` directly. If ``?t=<seconds>`` is supplied we seek
    to that byte offset using the file's sample rate / bitrate approximation
    when available, otherwise we redirect with the ``Range`` header forwarded.

    For the first cut we keep this thin: we serve the full file (with Range
    support) when the file is local, and we return a 302 redirect to the
    static mount when the file lives outside our managed tree.
    """
    row = await db.execute(
        select(AudioFile).where(AudioFile.id == audio_file_id)
    )
    audio: AudioFile | None = row.scalar_one_or_none()
    if not audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Аудио-файл {audio_file_id} не найден",
        )

    file_path = Path(audio.file_path)
    if not file_path.exists():
        # Fall back to the static mount path
        static_url = f"/media/protocols/{audio_file_id}/source.{audio.extension}"
        logger.warning(
            "audio_file_missing_on_disk",
            audio_file_id=str(audio_file_id),
            static_url=static_url,
        )
        return RedirectResponse(url=static_url, status_code=status.HTTP_302_FOUND)

    file_size = file_path.stat().st_size
    mime = audio.mime_type or _guess_mime(file_path)
    range_header = request.headers.get("range")

    # --- Pure seek (no Range): redirect to static mount with byte offset ----
    if t is not None and range_header is None:
        # Approximate byte offset from seconds (best-effort).
        # Without a known bitrate we cannot compute exactly — redirect to
        # the static mount which itself supports Range via StaticFiles.
        static_url = f"/media/protocols/{audio_file_id}/source.{audio.extension}"
        return RedirectResponse(url=static_url, status_code=status.HTTP_302_FOUND)

    # --- Range request: stream partial content ----------------------------
    if range_header:
        rng = _parse_range(range_header, file_size)
        if rng is None:
            # Malformed Range — serve full file (RFC 7233 §3.1)
            return FileResponse(
                path=str(file_path),
                media_type=mime,
                filename=audio.filename,
            )
        start, end = rng
        length = end - start + 1

        def iterator(chunk_size: int = 1024 * 1024):
            with file_path.open("rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(chunk_size, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Cache-Control": "public, max-age=3600",
        }
        logger.info(
            "audio_stream_partial",
            audio_file_id=str(audio_file_id),
            start=start,
            end=end,
            length=length,
        )
        return Response(
            content=b"".join(iterator()),
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type=mime,
            headers=headers,
        )

    # --- Full file -------------------------------------------------------
    return FileResponse(
        path=str(file_path),
        media_type=mime,
        headers={"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=3600"},
    )



# ----------------------------------------------------------------------------
# E181: POST /audio-files/{id}/transcode — перекодировка webm для браузеров
# ----------------------------------------------------------------------------


@router.post(
    "/audio-files/{audio_file_id}/transcode",
    summary="Transcode webm file to fix browser playback (E181)",
)
async def transcode_audio_file(
    audio_file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Перекодирует .webm файл через ffmpeg для правильного воспроизведения.

    Используется когда файл записан OBS/MediaRecorder без proper Cues
    и Chrome не может делать seek (PIPELINE_ERROR_READ).

    Использует -c:v copy -c:a copy (без перекодирования потоков),
    только пересобирает контейнер с Cues в начале.
    """
    row = await db.execute(select(AudioFile).where(AudioFile.id == audio_file_id))
    audio: AudioFile | None = row.scalar_one_or_none()
    if not audio:
        raise HTTPException(404, "Аудио файл не найден")

    file_path = Path(audio.file_path)
    if not file_path.exists():
        raise HTTPException(404, "Файл не найден на диске")

    # Используем shutil для поиска ffmpeg
    import shutil
    import subprocess
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        # Пробуем стандартные пути
        for path in [
            "C:/ffmpeg/bin/ffmpeg.exe",
            "C:/Program Files/ffmpeg/bin/ffmpeg.exe",
        ]:
            if Path(path).exists():
                ffmpeg_bin = path
                break
    if not ffmpeg_bin:
        raise HTTPException(500, "ffmpeg не найден. Установите ffmpeg или добавьте в PATH")

    # Output = temp файл
    output_path = file_path.with_suffix(".transcoded.webm")

    try:
        # E181: -c copy = без перекодирования, только пересборка контейнера
        result = subprocess.run(
            [
                ffmpeg_bin, "-y",
                "-i", str(file_path),
                "-c", "copy",
                "-movflags", "+faststart",
                str(output_path),
            ],
            capture_output=True,
            timeout=600,
        )
        if result.returncode != 0:
            logger.error(
                "transcode_failed",
                file=str(file_path),
                stderr=result.stderr.decode("utf-8", errors="ignore")[:500],
            )
            raise HTTPException(500, "ffmpeg не смог перекодировать файл")

        # Заменяем оригинал
        output_path.replace(file_path)
        audio.updated_at = datetime.now(timezone.utc)
        await db.commit()

        return {
            "status": "ok",
            "transcoded_file": str(file_path),
            "note": "Контейнер пересобран с faststart. Потоки не перекодировались.",
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "ffmpeg timeout (>10 мин)")
    except Exception as e:
        # Cleanup temp
        if output_path.exists():
            output_path.unlink()
        raise HTTPException(500, f"Ошибка транскодирования: {e}")