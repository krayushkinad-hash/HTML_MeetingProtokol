"""Remote Whisper proxy endpoints (E264, E284).

Two endpoints:

  * ``POST /transcribe/remote``         — proxy transcription via remote server
                                          (avoiding Mixed Content issues when
                                          the local backend is HTTPS but the
                                          remote Whisper server is plain HTTP).
  * ``POST /transcribe/remote/test-upload`` — debugging helper that accepts
                                          a raw upload (no protocol_id) and
                                          forwards it to the remote server,
                                          returning the remote response.

Both endpoints share the same multipart construction helpers
(``_make_multipart_body``, ``_do_multipart_request``).
"""
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.logging_config import get_logger
from app.db.models import AudioFile, Protocol, Utterance
from app.db.session import get_db

logger = get_logger(__name__)

router = APIRouter()


def _make_multipart_body(
    file_bytes: bytes, file_name: str, extra_fields: dict
) -> tuple[bytes, str]:
    """Собирает multipart/form-data body."""
    boundary = "----HMPBoundary" + uuid.uuid4().hex
    CRLF = "\r\n"
    body_parts = []
    for key, value in extra_fields.items():
        body_parts.append("--" + boundary + CRLF)
        body_parts.append(
            'Content-Disposition: form-data; name="' + key + '"' + CRLF + CRLF
        )
        body_parts.append(str(value) + CRLF)
    body_parts.append("--" + boundary + CRLF)
    body_parts.append(
        'Content-Disposition: form-data; name="file"; filename="'
        + file_name
        + '"'
        + CRLF
    )
    body_parts.append("Content-Type: audio/mpeg" + CRLF + CRLF)
    body_parts.append(file_bytes.decode("latin-1"))
    body_parts.append(CRLF + "--" + boundary + "--" + CRLF)
    body = "".join(body_parts).encode("latin-1")
    return body, boundary


def _do_multipart_request(
    url: str, body: bytes, boundary: str, timeout_sec: float = 3600.0
) -> tuple[bytes, int]:
    """Sync HTTP POST с multipart body. Возвращает (data, status).

    E280: Если первый запрос даёт 404 и URL не имеет path — пробуем добавить /transcribe
    """
    # Если URL заканчивается на / — отбросить слеш
    base_url = url.rstrip("/")

    urls_to_try = [url]
    # E280: если URL — просто http://host:port без path, добавить /transcribe
    parsed = urllib.parse.urlparse(url)
    if parsed.path in ("", "/"):
        urls_to_try.append(base_url + "/transcribe")

    for try_url in urls_to_try:
        req = urllib.request.Request(
            try_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "multipart/form-data; boundary=" + boundary
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                return resp.read(), resp.status
        except urllib.error.HTTPError as e:
            if e.code == 404 and len(urls_to_try) > 1:
                # попробуем следующий вариант
                continue
            return e.read(), e.code
    return b"", 404


@router.post("/remote")
async def transcribe_via_remote(
    protocol_id: str = Form(...),  # принимаем строкой, валидируем uuid вручную
    target_url: str = Form(...),
    target_path: str = Form("/transcribe"),
    model: str = Form("base"),
    language: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """E264: транскрибирует через remote Whisper-сервер.

    Workflow:
    1. Найти AudioFile в БД
    2. Прочитать аудио с диска
    3. POST multipart на {target_url}{target_path}
    4. Сохранить segments в БД
    5. Вернуть статистику
    """
    # E271: валидируем UUID вручную (Pydantic Form не парсит UUID строку автоматически)
    try:
        protocol_uuid = uuid.UUID(str(protocol_id))
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid protocol_id format, expected UUID")

    # E279: AudioFile не имеет protocol_id напрямую — идём через Protocol
    proto_row = await db.execute(
        select(Protocol).where(Protocol.id == protocol_uuid)
    )
    protocol = proto_row.scalar_one_or_none()
    if not protocol:
        raise HTTPException(404, "Protocol not found: " + str(protocol_id))
    if not protocol.audio_file_id:
        raise HTTPException(400, "Protocol has no audio file attached")

    af_row = await db.execute(
        select(AudioFile).where(AudioFile.id == protocol.audio_file_id)
    )
    audio = af_row.scalar_one_or_none()
    if not audio:
        raise HTTPException(404, "AudioFile not found")

    logger.info(
        "transcribe_via_remote_called",
        protocol_id=protocol_id,
        target_url=target_url,
    )

    file_path = Path(audio.file_path)
    if not file_path.exists():
        raise HTTPException(404, "Audio file missing on disk: " + str(file_path))

    audio_bytes = file_path.read_bytes()
    audio_ext = file_path.suffix.lstrip(".") or "m4a"

    try:
        body, boundary = _make_multipart_body(
            audio_bytes,
            "audio." + audio_ext,
            {"model": model, "language": language or "ru", "beam_size": "1"},
        )

        # E282: собираем URL правильно с защитой от мусорного target_path
        # 1. base_url — без trailing slash
        base_url = target_url.rstrip("/")
        # 2. target_path валидируем — если содержит /api/v1/hmp, это неверный путь
        raw_path = (target_path or "").strip()
        if raw_path and ("/api/v1/hmp" in raw_path or "/api/" in raw_path):
            logger.warning(
                "transcribe_via_remote_bad_path",
                path=raw_path,
                hint="ignoring",
            )
            raw_path = ""
        # 3. Если path пустой или мусорный — используем /transcribe
        if not raw_path or raw_path == "/":
            effective_path = "/transcribe"
        elif not raw_path.startswith("/"):
            effective_path = "/" + raw_path
        else:
            effective_path = raw_path
        final_url = base_url + effective_path
        logger.info(
            "transcribe_via_remote_posting",
            url=final_url,
            file_size=len(audio_bytes),
        )

        data, status = await run_in_threadpool(
            _do_multipart_request,
            final_url,
            body,
            boundary,
            3600.0,
        )
        if status >= 400:
            raise HTTPException(
                status_code=502,
                detail="Remote "
                + str(status)
                + ": "
                + data[:200].decode("utf-8", errors="replace"),
            )
        result = json.loads(data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, "Failed to reach remote: " + str(e))

    segments = result.get("segments", [])
    created_count = 0
    for seg in segments:
        text_seg = seg.get("text", "").strip()
        if not text_seg:
            continue
        db.add(
            Utterance(
                protocol_id=protocol_uuid,  # E272: используем распарсенный uuid, а не строку
                start_sec=Decimal(str(round(seg.get("start", 0), 3))),
                end_sec=Decimal(str(round(seg.get("end", 0), 3))),
                text=text_seg,
            )
        )
        created_count += 1

    proto = await db.get(Protocol, protocol_uuid)  # E272: uuid объект
    if proto:
        proto.status = "ready"
    await db.commit()

    return {
        "task_id": str(protocol_id),
        "segments_created": created_count,
        "text": result.get("text", ""),
        "language": result.get("language"),
    }


# E284: тестовый endpoint для кнопки ТЕСТ — принимает файл напрямую (без protocol_id)
# и шлёт на remote Whisper, возвращает ответ
@router.post("/remote/test-upload")
async def remote_test_upload(
    file: UploadFile = File(...),
    target_url: str = Form("http://195.133.77.76:8000"),
    target_path: str = Form("/transcribe"),
    model: str = Form("base"),
    language: str = Form("ru"),
):
    """E284: тестовая отправка файла на remote Whisper.

    Workflow:
    1. Получить файл через multipart upload
    2. Сохранить во временный файл (чтобы bytes-like объект превратить в файл)
    3. POST multipart на {target_url}{target_path}
    4. Вернуть результат
    """
    # Сохраняем во временный файл
    suffix = os.path.splitext(file.filename or "audio")[1] or ".mp3"
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(tmp_fd, "wb") as tmp:
            shutil.copyfileobj(file.file, tmp)

        # Читаем в байты
        with open(tmp_path, "rb") as f:
            audio_bytes = f.read()
        audio_size = len(audio_bytes)

        # Собираем multipart body
        body, boundary = _make_multipart_body(
            audio_bytes,
            file.filename or ("audio" + suffix),
            {"model": model, "language": language, "beam_size": "1"},
        )

        # Строим URL (E282 логика)
        base_url = target_url.rstrip("/")
        effective_path = (target_path or "").strip()
        if effective_path and (
            "/api/v1/hmp" in effective_path or "/api/" in effective_path
        ):
            effective_path = ""
        if not effective_path or effective_path == "/":
            effective_path = "/transcribe"
        elif not effective_path.startswith("/"):
            effective_path = "/" + effective_path
        final_url = base_url + effective_path

        logger.info(
            "remote_test_upload_posting",
            url=final_url,
            file_size=audio_size,
            model=model,
            language=language,
        )

        # Отправляем на remote через threadpool
        data, status = await run_in_threadpool(
            _do_multipart_request, final_url, body, boundary, 3600.0
        )

        if status >= 400:
            return {
                "status": status,
                "remote_url": final_url,
                "file_size_bytes": audio_size,
                "filename": file.filename,
                "model": model,
                "language": language,
                "remote_response": data[:2000].decode("utf-8", errors="replace"),
                "error": f"Remote returned {status}",
            }

        result = json.loads(data)
        return {
            "status": "ok",
            "remote_url": final_url,
            "file_size_bytes": audio_size,
            "filename": file.filename,
            "model": model,
            "language": language,
            "remote_text_preview": result.get("text", "")[:500],
            "segments_count": len(result.get("segments", [])),
            "remote_language": result.get("language"),
            "remote_duration_sec": result.get("duration_sec"),
            "first_segment": (
                result.get("segments", [{}])[0] if result.get("segments") else None
            ),
        }
    finally:
        # Удаляем временный файл
        try:
            os.unlink(tmp_path)
        except Exception:
            pass