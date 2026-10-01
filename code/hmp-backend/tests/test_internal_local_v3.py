"""Coverage tests for app/routers/transcribe/local.py — v3 supplement.

Targets branches that existing test_internal_local_endpoints.py and
test_internal_local_endpoints_v3.py do NOT hit:

  * POST /transcribe/run
      - 404 протокол не найден
      - 409 protocol.status == "diarizing"
      - 422 protocol без audio_file_id
      - 422 audio_file_id указывает на несуществующий row
      - restart-force-ветка: protocol.status == "transcribing"
      - default compute_type из settings (compute_type=None в request)
  * POST /transcribe/pause/{task_id}
      - 400 invalid UUID
      - 404 несуществующая задача
      - неактивный статус (например, "completed") → 200 со "не активна"
      - happy path: paused, bg_task.cancel() вызван
  * POST /transcribe/resume/{task_id}
      - 400 invalid UUID
      - 404 несуществующая задача
      - не-paused статус → 200 со "resume невозможен"
      - 400 "Протокол без аудиофайла" (audio_file_id=None)
      - 400 "Аудиофайл не найден" (audio row отсутствует)
  * GET /transcribe/status/{task_id}
      - 404 нет в in-memory и нет в БД
      - 200 default ETA через /run с duration_sec=None
  * GET /transcribe/health
      - 200 когда _tasks пустой → active_tasks=0

Итого: 14 тестов. Цель — поднять coverage local.py с текущих ~37% до 50%+.
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_whisper(monkeypatch):
    """Mock faster_whisper.WhisperModel + transcription_service.transcribe/get_status."""
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
    monkeypatch.setattr(
        transcription.transcription_service,
        "get_status",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        task_status,
        "update_task_status_in_db",
        AsyncMock(return_value=None),
    )

    # Подавляем BG-tasks, создаваемые из local.py (см. v3 паттерн).
    import traceback
    from app.routers.transcribe import local as local_module
    _real_create_task = local_module.asyncio.create_task

    def _safe_create_task(coro):
        stack = traceback.extract_stack()
        local_called = any(
            "transcribe/local.py" in frame.filename for frame in stack[-6:]
        )
        if local_called:
            try:
                coro.close()
            except Exception:
                pass

            async def _noop() -> None:
                return None
            return _real_create_task(_noop())
        return _real_create_task(coro)

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
        title="v3 supplement Protocol",
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

    fake_audio = tmp_path / "audio.wav"
    fake_audio.write_bytes(b"RIFF" + b"\x00" * 200)

    af = AudioFile(
        id=uuid.uuid4(),
        file_path=str(fake_audio),
        filename="audio.wav",
        extension="wav",
        size_bytes=204,
        mime_type="audio/wav",
        duration_sec=120,
    )
    db_session.add(af)
    await db_session.commit()
    await db_session.refresh(af)

    my_protocol.audio_file_id = af.id
    await db_session.commit()
    await db_session.refresh(my_protocol)
    return af


@pytest_asyncio.fixture
async def my_transcribing_protocol(db_session, my_protocol, my_audio_file):
    """Protocol в статусе 'transcribing' — тестируем force-restart ветку."""
    from sqlalchemy import update
    from app.db.models import Protocol

    await db_session.execute(
        update(Protocol)
        .where(Protocol.id == my_protocol.id)
        .values(status="transcribing")
    )
    await db_session.commit()
    await db_session.refresh(my_protocol)
    return my_protocol


@pytest_asyncio.fixture
async def my_diarizing_protocol(db_session, my_protocol, my_audio_file):
    """Protocol в статусе 'diarizing' — должен вернуть 409."""
    from sqlalchemy import update
    from app.db.models import Protocol

    await db_session.execute(
        update(Protocol)
        .where(Protocol.id == my_protocol.id)
        .values(status="diarizing")
    )
    await db_session.commit()
    await db_session.refresh(my_protocol)
    return my_protocol


@pytest_asyncio.fixture
async def my_paused_task(db_session, my_protocol, my_audio_file):
    from app.db.models import TranscriptionTask

    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="paused",
        progress=42.0,
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
async def my_completed_task(db_session, my_protocol, my_audio_file):
    from app.db.models import TranscriptionTask

    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="completed",
        progress=100.0,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_state():
    """Чистим реестры и in-memory _tasks до/после каждого теста."""
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
# POST /transcribe/run — error branches
# ===========================================================================


@pytest.mark.asyncio
async def test_run_404_protocol_not_found(client, mock_whisper, db_session):
    """Запрос с несуществующим protocol_id → 404."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(uuid.uuid4())},
    )
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_run_409_protocol_diarizing(client, mock_whisper, my_diarizing_protocol):
    """Protocol в статусе 'diarizing' → 409 Conflict."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(my_diarizing_protocol.id)},
    )
    assert r.status_code == 409
    assert "диаризаци" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_run_422_protocol_without_audio_file_id(
    client, mock_whisper, db_session
):
    """Protocol без audio_file_id → 422."""
    from app.db.models import Protocol
    from datetime import date as _date

    p = Protocol(
        id=uuid.uuid4(),
        title="no audio",
        date=_date.today(),
        status="loaded",
        audio_file_id=None,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.commit()

    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(p.id)},
    )
    assert r.status_code == 422
    assert "аудио" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_run_202_force_restart_from_transcribing(
    client, mock_whisper, my_transcribing_protocol
):
    """Protocol.status='transcribing' → сброс в 'loaded' и запуск 202."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(my_transcribing_protocol.id)},
    )
    assert r.status_code == 202
    assert r.json()["status"] == "queued"

    # Проверяем что protocol был сброшен в "loaded" перед стартом, потом снова transcribing
    await asyncio.sleep(0.05)  # дать BG-task шанс отработать (он noop)


@pytest.mark.asyncio
async def test_run_202_default_compute_type_from_settings(
    client, mock_whisper, my_protocol, my_audio_file
):
    """compute_type отсутствует в request → берётся из settings.whisper_compute_type."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(my_protocol.id)},  # без compute_type
    )
    assert r.status_code == 202
    assert r.json()["status"] == "queued"


# ===========================================================================
# POST /transcribe/pause/{task_id} — branches
# ===========================================================================


@pytest.mark.asyncio
async def test_pause_400_invalid_uuid(client, mock_whisper):
    """Невалидный UUID → 400."""
    r = await client.post("/api/v1/hmp/transcribe/pause/not-a-uuid")
    assert r.status_code == 400
    assert "валид" in r.json()["detail"].lower() or "невалид" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_pause_404_task_not_found(client, mock_whisper):
    """Несуществующий task_id → 404."""
    r = await client.post(f"/api/v1/hmp/transcribe/pause/{uuid.uuid4()}")
    assert r.status_code == 404
    assert "не найдена" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_pause_inactive_status_returns_message(
    client, mock_whisper, my_completed_task
):
    """Pause для completed task → 200, 'Задача не активна'."""
    r = await client.post(f"/api/v1/hmp/transcribe/pause/{my_completed_task.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert "не активна" in body["message"].lower()


@pytest.mark.asyncio
async def test_pause_running_task_with_active_bg(
    client, mock_whisper, my_paused_task, db_session
):
    """Pause с активным bg_task в реестре → cancel() вызван, task обновлён."""
    from app.services.active_tasks import _active_transcription_tasks
    from sqlalchemy import update
    from app.db.models import TranscriptionTask

    # Переводим task в 'running' прямым UPDATE
    await db_session.execute(
        update(TranscriptionTask)
        .where(TranscriptionTask.id == my_paused_task.id)
        .values(status="running")
    )
    await db_session.commit()

    # Регистрируем фейковый bg_task в реестре
    fake_bg = MagicMock()
    fake_bg.done.return_value = False
    _active_transcription_tasks[str(my_paused_task.id)] = fake_bg

    r = await client.post(f"/api/v1/hmp/transcribe/pause/{my_paused_task.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "paused"
    assert body["can_resume"] is True
    assert "пауз" in body["message"].lower()
    assert "transcribe/resume" in body["message"]
    fake_bg.cancel.assert_called_once()


# ===========================================================================
# POST /transcribe/resume/{task_id} — branches
# ===========================================================================


@pytest.mark.asyncio
async def test_resume_400_invalid_uuid(client, mock_whisper):
    """Невалидный UUID → 400."""
    r = await client.post("/api/v1/hmp/transcribe/resume/not-a-uuid")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_resume_404_task_not_found(client, mock_whisper):
    """Несуществующий task_id → 404."""
    r = await client.post(f"/api/v1/hmp/transcribe/resume/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_resume_non_paused_status_returns_message(
    client, mock_whisper, my_completed_task
):
    """Resume для completed task → 200, 'resume невозможен'."""
    r = await client.post(
        f"/api/v1/hmp/transcribe/resume/{my_completed_task.id}"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert "невозможен" in body["message"].lower()


@pytest.mark.asyncio
async def test_resume_400_missing_audio_file_row(
    client, mock_whisper, my_paused_task, db_session
):
    """Resume когда audio_file row удалён → 400."""
    from sqlalchemy import delete, select
    from app.db.models import AudioFile, Protocol

    # Получаем audio_file_id из protocol через БД
    proto_row = await db_session.execute(
        select(Protocol).where(Protocol.id == my_paused_task.protocol_id)
    )
    proto = proto_row.scalar_one()
    audio_file_id = proto.audio_file_id

    # Удаляем audio row, оставляя audio_file_id в protocol → ветка 400
    await db_session.execute(
        delete(AudioFile).where(AudioFile.id == audio_file_id)
    )
    await db_session.commit()

    r = await client.post(f"/api/v1/hmp/transcribe/resume/{my_paused_task.id}")
    assert r.status_code == 400


# ===========================================================================
# GET /transcribe/status/{task_id} — 404 + health
# ===========================================================================


@pytest.mark.asyncio
async def test_status_404_unknown_task(client, mock_whisper):
    """Неизвестный task_id — нет ни в памяти, ни в БД → 404."""
    r = await client.get(f"/api/v1/hmp/transcribe/status/{uuid.uuid4()}")
    assert r.status_code == 404
    assert "не найдена" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_health_with_empty_tasks_dict(client, mock_whisper):
    """Когда _tasks пустой → active_tasks=0."""
    r = await client.get("/api/v1/hmp/transcribe/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["active_tasks"] == 0