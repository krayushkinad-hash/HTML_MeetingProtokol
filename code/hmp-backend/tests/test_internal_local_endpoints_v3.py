"""Coverage tests for app/routers/transcribe/local.py — v3 supplement.

Дополняет tests/test_internal_local_endpoints.py (v1) новыми ветками:

  * POST /transcribe/cancel/{task_id}            — happy path, not_found, invalid uuid
  * POST /transcribe/resume/{task_id}            — paused happy path, audio_hash mismatch,
                                                  protocol без audio, невалидный JSON сегментов,
                                                  missing audio file on disk
  * POST /transcribe/run                         — разные модели + language,
                                                  audio file path не существует на диске
  * GET  /transcribe/status/{task_id}            — in-memory dict hit, DB fallback разные статусы
  * _estimated_completion helper (через /run)

Цель: поднять coverage local.py с ~37% до 60%+.
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Shared fixtures — повторяют паттерн из v1, чтобы не зависеть от v1-imports
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_whisper(monkeypatch):
    """Mock faster_whisper.WhisperModel + transcription_service.transcribe.

    Также мокаем update_task_status_in_db чтобы BG-task из /run и /resume
    не блокировал тесты через долгие коммиты.
    """
    from app.services import transcription
    from app.services import task_status

    fake_model = MagicMock(name="FakeWhisperModel")
    monkeypatch.setattr("faster_whisper.WhisperModel", fake_model, raising=False)

    status_obj = MagicMock()
    status_obj.status = "completed"
    status_obj.error_message = None
    mock_transcribe = AsyncMock(return_value=status_obj)
    monkeypatch.setattr(
        transcription.transcription_service, "transcribe", mock_transcribe
    )
    # Default: in-memory status is None (forces DB fallback)
    monkeypatch.setattr(
        transcription.transcription_service,
        "get_status",
        MagicMock(return_value=None),
    )
    # No-op BG-task finalizer (для failed/completed/cancelled веток в _runner)
    monkeypatch.setattr(
        task_status,
        "update_task_status_in_db",
        AsyncMock(return_value=None),
    )
    # Перехватываем ТОЛЬКО create_task из app/routers/transcribe/local.py,
    # не трогая глобальный asyncio.create_task (иначе asyncpg сломается).
    import traceback
    from app.routers.transcribe import local as local_module
    _real_create_task = local_module.asyncio.create_task

    def _safe_create_task(coro):
        # Проверяем стек — только если вызов из local.py
        stack = traceback.extract_stack()
        local_called = any(
            "transcribe/local.py" in frame.filename for frame in stack[-6:]
        )
        if local_called:
            # Не запускаем реальный BG-task — закрываем корутину и создаём no-op
            try:
                coro.close()
            except Exception:
                pass
            async def _noop():
                return None
            return _real_create_task(_noop())
        return _real_create_task(coro)

    # Подменяем имя `asyncio` в local.py через setattr на объект-обёртку
    class _AsyncioProxy:
        def __getattr__(self, name):
            if name == "create_task":
                return _safe_create_task
            return getattr(local_module.asyncio, name)
    monkeypatch.setattr(local_module, "asyncio", _AsyncioProxy())
    return {
        "transcribe": mock_transcribe,
        "get_status": transcription.transcription_service.get_status,
    }


@pytest_asyncio.fixture
async def my_protocol(db_session):
    from app.db.models import Protocol
    from datetime import date as _date

    p = Protocol(
        id=uuid.uuid4(),
        title="v3 Test Protocol",
        date=_date.today(),
        status="loaded",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def my_audio_file(db_session, my_protocol, tmp_path):
    from app.db.models import AudioFile

    fake_audio = tmp_path / "v3_audio.wav"
    fake_audio.write_bytes(b"RIFF" + b"\x00" * 200)

    af = AudioFile(
        id=uuid.uuid4(),
        file_path=str(fake_audio),
        filename="v3_audio.wav",
        extension="wav",
        size_bytes=204,
        mime_type="audio/wav",
        duration_sec=300,  # 5 минут → проверяем 0.3× realtime ветку ETA
    )
    db_session.add(af)
    await db_session.commit()
    await db_session.refresh(af)

    my_protocol.audio_file_id = af.id
    await db_session.commit()
    await db_session.refresh(my_protocol)
    return af


@pytest_asyncio.fixture
async def my_missing_audio_file(db_session, my_protocol, tmp_path):
    """AudioFile row указывает на путь, которого нет на диске (для 422)."""
    from app.db.models import AudioFile

    af = AudioFile(
        id=uuid.uuid4(),
        file_path=str(tmp_path / "ghost.wav"),  # не существует
        filename="ghost.wav",
        extension="wav",
        size_bytes=0,
        mime_type="audio/wav",
        duration_sec=60,
    )
    db_session.add(af)
    await db_session.commit()
    await db_session.refresh(af)

    my_protocol.audio_file_id = af.id
    await db_session.commit()
    await db_session.refresh(my_protocol)
    return af


@pytest_asyncio.fixture
async def my_paused_task(db_session, my_protocol, my_audio_file):
    from app.db.models import TranscriptionTask

    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="paused",
        progress=42.0,
        current_chunk=10,
        paused_at=datetime.now(timezone.utc),
        last_processed_sec=120.0,
        audio_hash=None,
        segments_so_far_json=None,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


@pytest_asyncio.fixture
async def my_paused_task_with_segments(db_session, my_protocol, my_audio_file):
    """Paused task с валидным segments_so_far_json."""
    from app.db.models import TranscriptionTask

    segs = [{"start": 0.0, "end": 1.0, "text": "hello"}, {"start": 1.0, "end": 2.0, "text": "world"}]
    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="paused",
        progress=10.0,
        current_chunk=2,
        paused_at=datetime.now(timezone.utc),
        last_processed_sec=2.0,
        audio_hash=None,
        segments_so_far_json=json.dumps(segs),
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


@pytest_asyncio.fixture
async def my_paused_task_corrupt_json(db_session, my_protocol, my_audio_file):
    """Paused task с НЕвалидным segments_so_far_json → except → already_done=[]."""
    from app.db.models import TranscriptionTask

    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="paused",
        progress=10.0,
        paused_at=datetime.now(timezone.utc),
        last_processed_sec=2.0,
        segments_so_far_json="{not valid json",
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


@pytest_asyncio.fixture
async def my_running_task(db_session, my_protocol):
    from app.db.models import TranscriptionTask
    from app.services import transcription_progress as tp

    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="running",
        progress=25.0,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    # Регистрируем в legacy _jobs dict чтобы cancel_job его нашёл
    tp._jobs[str(t.id)] = {
        "task_id": str(t.id),
        "protocol_id": str(my_protocol.id),
        "status": "running",
        "progress": 25.0,
        "message": "running",
        "segments_count": 0,
        "updated_at": 0.0,
    }
    yield t
    tp._jobs.pop(str(t.id), None)


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_active_tasks():
    """Очищаем реестр BG-задач, _jobs dict и transcription_service._tasks
    до/после каждого теста для изоляции.

    create_task в local.py замокан через _AsyncioProxy (в mock_whisper),
    поэтому реальные задачи не запускаются. Но /run и /resume всё равно
    пишут в _tasks[in-memory status] — нужно чистить.
    """
    from app.services.active_tasks import _active_transcription_tasks
    from app.services import transcription_progress as tp
    from app.services import transcription

    _active_transcription_tasks.clear()
    tp._jobs.clear()
    tp._pending_db_cancels.clear()
    transcription.transcription_service._tasks.clear()  # noqa: SLF001
    yield
    _active_transcription_tasks.clear()
    tp._jobs.clear()
    tp._pending_db_cancels.clear()
    transcription.transcription_service._tasks.clear()  # noqa: SLF001


# ===========================================================================
# POST /transcribe/cancel/{task_id}  — НОВОЕ в v3 (нет в v1)
# ===========================================================================


@pytest.mark.asyncio
async def test_cancel_not_found_returns_status_not_found(client, mock_whisper):
    """Cancel для несуществующего task_id → status='not_found', HTTP 200."""
    r = await client.post(f"/api/v1/hmp/transcribe/cancel/{uuid.uuid4()}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "not_found"
    assert "не найдена" in body["message"].lower()


@pytest.mark.asyncio
async def test_cancel_invalid_uuid(client, mock_whisper):
    """Cancel с мусором вместо UUID → cancel_job возвращает False → not_found."""
    r = await client.post("/api/v1/hmp/transcribe/cancel/not-a-uuid")
    assert r.status_code == 200
    assert r.json()["status"] == "not_found"


@pytest.mark.asyncio
async def test_cancel_success_running_task(client, mock_whisper, my_running_task, db_session):
    """Cancel реального running task → status='cancelled', DB обновлена."""
    r = await client.post(f"/api/v1/hmp/transcribe/cancel/{my_running_task.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cancelled"
    assert body["task_id"] == str(my_running_task.id)

    # Проверяем, что DB обновлена: статус cancelled, finished_at заполнен
    await db_session.refresh(my_running_task)
    assert my_running_task.status == "cancelled"
    assert my_running_task.error_message == "Отменено пользователем"
    assert my_running_task.finished_at is not None


@pytest.mark.asyncio
async def test_cancel_already_completed_task(client, mock_whisper, my_running_task, db_session):
    """Cancel уже завершённой задачи → cancel_job=True, но в БД 'already terminal'."""
    from sqlalchemy import update
    from app.db.models import TranscriptionTask

    await db_session.execute(
        update(TranscriptionTask)
        .where(TranscriptionTask.id == my_running_task.id)
        .values(status="completed")
    )
    await db_session.commit()

    r = await client.post(f"/api/v1/hmp/transcribe/cancel/{my_running_task.id}")
    # endpoint всё равно возвращает "cancelled" — это OK
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


# ===========================================================================
# POST /transcribe/resume/{task_id} — happy path и edge cases
# ===========================================================================


@pytest.mark.asyncio
async def test_resume_200_paused_task_happy_path(client, mock_whisper, my_paused_task):
    """Resume paused task → 200, status='running', BG-task зарегистрирована."""
    from app.services.active_tasks import _active_transcription_tasks

    r = await client.post(f"/api/v1/hmp/transcribe/resume/{my_paused_task.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "running"
    assert body["task_id"] == str(my_paused_task.id)
    assert body["resume_from_sec"] == my_paused_task.last_processed_sec
    assert body["previously_done_segments"] == 0
    assert "возобновлена" in body["message"].lower()

    # BG-task должна быть зарегистрирована
    assert str(my_paused_task.id) in _active_transcription_tasks


@pytest.mark.asyncio
async def test_resume_with_segments_so_far_json(
    client, mock_whisper, my_paused_task_with_segments
):
    """Resume с валидным segments_so_far_json → previously_done_segments=2."""
    r = await client.post(
        f"/api/v1/hmp/transcribe/resume/{my_paused_task_with_segments.id}"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "running"
    assert body["previously_done_segments"] == 2


@pytest.mark.asyncio
async def test_resume_with_corrupt_json_segments(
    client, mock_whisper, my_paused_task_corrupt_json
):
    """Resume с битым JSON → except → already_done=[], segments=0."""
    r = await client.post(
        f"/api/v1/hmp/transcribe/resume/{my_paused_task_corrupt_json.id}"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "running"
    # Битый JSON даёт пустой список
    assert body["previously_done_segments"] == 0


@pytest.mark.asyncio
async def test_resume_protocol_without_audio(client, mock_whisper, my_paused_task, db_session):
    """Resume task, у которого протокол больше не имеет audio_file_id → 400."""
    from sqlalchemy import update
    from app.db.models import Protocol

    await db_session.execute(
        update(Protocol)
        .where(Protocol.id == my_paused_task.protocol_id)
        .values(audio_file_id=None)
    )
    await db_session.commit()

    r = await client.post(f"/api/v1/hmp/transcribe/resume/{my_paused_task.id}")
    assert r.status_code == 400
    assert "аудиоф" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_resume_audio_hash_changed_retranscribes_from_start(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """Если audio_hash в БД != hash файла на диске → reset last_processed_sec=0."""
    from app.db.models import TranscriptionTask

    # В БД кладём ЗАВЕДОМО НЕПРАВИЛЬНЫЙ hash, отличный от реального
    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="paused",
        progress=50.0,
        paused_at=datetime.now(timezone.utc),
        last_processed_sec=120.0,
        audio_hash="stale_hash_that_doesnt_match",
        segments_so_far_json=None,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    r = await client.post(f"/api/v1/hmp/transcribe/resume/{t.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "running"
    # После audio mismatch last_processed_sec обнуляется
    assert body["resume_from_sec"] == 0.0


# ---------------------------------------------------------------------------
# POST /transcribe/run — дополнительные ветки
# ---------------------------------------------------------------------------
# Примечание: исходный код не проверяет существование файла на диске
# (E150: hash вычисляется молча с warning, если файла нет).
# Поэтому ветка "audio_file row exists, но path отсутствует" НЕ даёт 422.

@pytest.mark.asyncio
async def test_run_202_with_large_v3_model_and_long_audio(
    client, mock_whisper, my_protocol, my_audio_file
):
    """Run с model='large-v3' + язык 'en' → 202, ETA рассчитан по 0.3× формуле."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={
            "protocol_id": str(my_protocol.id),
            "model": "large-v3",
            "language": "en",
            "beam_size": 5,
            "compute_type": "float16",
        },
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    eta = datetime.fromisoformat(body["estimated_completion"].replace("Z", "+00:00"))
    if eta.tzinfo is None:
        eta = eta.replace(tzinfo=timezone.utc)
    assert eta > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_run_202_with_medium_model(client, mock_whisper, my_protocol, my_audio_file):
    """Run с model='medium' и language='ru' → 202."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={
            "protocol_id": str(my_protocol.id),
            "model": "medium",
            "language": "ru",
        },
    )
    assert r.status_code == 202
    assert r.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_run_422_invalid_compute_type(client, mock_whisper, my_protocol, my_audio_file):
    """Невалидный compute_type → 422 (Pydantic Literal validation)."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={
            "protocol_id": str(my_protocol.id),
            "compute_type": "invalid_type_xyz",
        },
    )
    assert r.status_code == 422


# ===========================================================================
# GET /transcribe/status/{task_id} — in-memory hit + DB fallback разные статусы
# ===========================================================================


@pytest.mark.asyncio
async def test_status_200_from_in_memory_service(
    client, mock_whisper, my_protocol
):
    """Если transcription_service.get_status возвращает объект — используем его."""
    from app.services.transcription import transcription_service
    from app.schemas import TranscriptionStatus

    fake = TranscriptionStatus(
        task_id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="running",
        progress_percent=42,
        message="processing chunk 5/10",
    )
    transcription_service.get_status = MagicMock(return_value=fake)  # type: ignore[assignment]

    r = await client.get(f"/api/v1/hmp/transcribe/status/{fake.task_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "running"
    assert body["progress_percent"] == 42
    assert body["message"] == "processing chunk 5/10"


@pytest.mark.asyncio
async def test_status_200_db_fallback_with_error_message(
    client, mock_whisper, my_protocol, db_session
):
    """DB fallback: task с error_message и status='failed'."""
    from app.db.models import TranscriptionTask

    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="failed",
        progress=33.3,
        error_message="CUDA OOM",
        current_step="failed at chunk 7",
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    r = await client.get(f"/api/v1/hmp/transcribe/status/{t.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    assert body["error_message"] == "CUDA OOM"
    assert body["progress_percent"] == 33


@pytest.mark.asyncio
async def test_status_200_db_fallback_completed_with_null_progress(
    client, mock_whisper, my_protocol, db_session
):
    """DB fallback: task.status='completed', progress=NULL → progress_percent=0."""
    from app.db.models import TranscriptionTask

    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="completed",
        progress=None,  # важно: None → ветка `int(task.progress or 0)`
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    r = await client.get(f"/api/v1/hmp/transcribe/status/{t.id}")
    assert r.status_code == 200
    assert r.json()["progress_percent"] == 0
    assert r.json()["status"] == "completed"


# ===========================================================================
# GET /transcribe/health — проверить active_tasks счётчик
# ===========================================================================


@pytest.mark.asyncio
async def test_health_reports_active_tasks_count(client, mock_whisper):
    """Health возвращает active_tasks = len(transcription_service._tasks)."""
    from app.services.transcription import transcription_service
    from app.schemas import TranscriptionStatus

    # Засоряем in-memory dict
    for _ in range(3):
        fake_id = uuid.uuid4()
        transcription_service._tasks[fake_id] = TranscriptionStatus(  # noqa: SLF001
            task_id=fake_id,
            protocol_id=uuid.uuid4(),
            status="running",
            progress_percent=10,
        )

    r = await client.get("/api/v1/hmp/transcribe/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["active_tasks"] == 3
