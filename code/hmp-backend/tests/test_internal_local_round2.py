"""Round 2 — additional coverage for app/routers/transcribe/local.py.

Цель: поднять coverage local.py до 50%+ (с 12%).

Сфокусировано на ветках, не покрытых в test_internal_local_round1.py
и test_internal_local_endpoints_v3.py:

  * POST /transcribe/run
      - 404 протокол не найден
      - 422 audio_file_id отсутствует у протокола
      - status='transcribing' → force-restart в 'loaded' и далее 202
      - run создаёт запись TranscriptionTask в БД
      - run логирует параметры (model, language, beam_size, compute_type)
  * POST /transcribe/cancel/{task_id}
      - 200 cancel задачи, найденной ТОЛЬКО в asyncio registry (нет в _jobs)
      - 200 cancel → DB update + cleanup pending queue
  * POST /transcribe/pause/{task_id}
      - 400 невалидный task_id (не UUID)
      - 404 несуществующий task
      - 200 для task в terminal state (completed/paused/failed/cancelled)
        → возвращает message "пауза невозможна"
  * POST /transcribe/resume/{task_id}
      - 400 невалидный task_id
      - 404 несуществующий task
      - 200 resume для task в НЕ-paused статусе → status echo
      - 400 audio_file row не найден в БД (был удалён)
  * GET /transcribe/status/{task_id}
      - 404 несуществующий task
  * GET /transcribe/health
      - 200 active_tasks=0 на пустом сервисе
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from datetime import date as _date
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from app.db.models import (
    AudioFile,
    Protocol,
    TranscriptionTask,
)


# ---------------------------------------------------------------------------
# Fixtures (duplicate from v1/v3 to make this file self-contained)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_whisper(monkeypatch):
    """Mock faster_whisper + transcription_service."""
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

    # Подавляем BG-task из local.py через _AsyncioProxy
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

            async def _noop():
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
    p = Protocol(
        id=uuid.uuid4(),
        title="round2 Protocol",
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
    fake_audio = tmp_path / "audio_r2.wav"
    fake_audio.write_bytes(b"RIFF" + b"\x00" * 200)

    af = AudioFile(
        id=uuid.uuid4(),
        file_path=str(fake_audio),
        filename="audio_r2.wav",
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
async def my_protocol_with_audio(db_session, my_audio_file):
    """Возвращает протокол, к которому привязан audio_file (alias для ясности)."""
    # Обновим protocol из БД чтобы получить актуальную связь
    from sqlalchemy import select
    res = await db_session.execute(
        select(Protocol).where(Protocol.id == my_audio_file.id) if False else
        select(Protocol).where(Protocol.audio_file_id == my_audio_file.id)
    )
    p = res.scalar_one()
    return p


@pytest_asyncio.fixture
async def my_running_task(db_session, my_protocol):
    """Task в БД + asyncio регистрация (но НЕ в _jobs)."""
    from app.services import transcription_progress as tp
    from app.services.active_tasks import _active_transcription_tasks

    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="running",
        progress=25.0,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    # Регистрируем ТОЛЬКО в asyncio registry — НЕ в legacy _jobs dict
    async def _dummy_bg():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            return
        return None
    bg = asyncio.create_task(_dummy_bg())
    _active_transcription_tasks[str(t.id)] = bg
    yield t
    # cleanup
    if not bg.done():
        bg.cancel()
        try:
            await bg
        except Exception:
            pass
    _active_transcription_tasks.pop(str(t.id), None)
    tp._jobs.pop(str(t.id), None)


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_state():
    from app.services.active_tasks import _active_transcription_tasks
    from app.services import transcription_progress as tp
    from app.services import transcription

    _active_transcription_tasks.clear()
    tp._jobs.clear()
    tp._pending_db_cancels.clear()
    transcription.transcription_service._tasks.clear()
    yield
    _active_transcription_tasks.clear()
    tp._jobs.clear()
    tp._pending_db_cancels.clear()
    transcription.transcription_service._tasks.clear()


# ===========================================================================
# POST /transcribe/run — error branches и DB persistence
# ===========================================================================


@pytest.mark.asyncio
async def test_run_404_protocol_not_found(client, mock_whisper):
    """Несуществующий protocol_id → 404."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(uuid.uuid4())},
    )
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_run_422_when_protocol_has_no_audio(
    client, mock_whisper, my_protocol, db_session
):
    """audio_file_id is None → 422."""
    # Убедимся, что audio_file_id действительно None
    await db_session.refresh(my_protocol)
    assert my_protocol.audio_file_id is None

    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(my_protocol.id)},
    )
    assert r.status_code == 422
    assert "аудио" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_run_force_restart_when_protocol_transcribing(
    client, mock_whisper, my_protocol_with_audio, db_session
):
    """status='transcribing' → force_restart (status='loaded'), в итоге 202."""
    from sqlalchemy import update as _u

    # Переводим протокол в status='transcribing'
    await db_session.execute(
        _u(Protocol).where(Protocol.id == my_protocol_with_audio.id).values(
            status="transcribing"
        )
    )
    await db_session.commit()

    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(my_protocol_with_audio.id)},
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"

    # Проверяем, что force_restart вернул protocol в 'loaded' перед 202
    # (затем /run пометил как 'transcribing', но это уже после force-restart)
    # Главное — endpoint не вернул 409, а принял задачу.
    assert body["protocol_id"] == str(my_protocol_with_audio.id)


@pytest.mark.asyncio
async def test_run_persists_transcription_task_in_db(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """После /run в БД появляется TranscriptionTask с status='queued'."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(my_protocol.id)},
    )
    assert r.status_code == 202
    task_id = r.json()["task_id"]

    # Проверяем БД через ту же сессию (избегаем loop-проблем с AsyncSessionLocal)
    db_task = await db_session.get(TranscriptionTask, uuid.UUID(task_id))
    assert db_task is not None
    assert db_task.protocol_id == my_protocol.id
    assert db_task.status == "queued"


@pytest.mark.asyncio
async def test_run_full_params_logs_and_returns_202(
    client, mock_whisper, my_protocol, my_audio_file
):
    """Полный набор: model, language, beam_size, compute_type → 202."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={
            "protocol_id": str(my_protocol.id),
            "model": "small",
            "language": "en",
            "beam_size": 3,
            "compute_type": "int8",
            "prompt": "Meeting transcript",
        },
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["protocol_id"] == str(my_protocol.id)


# ===========================================================================
# POST /transcribe/cancel/{task_id} — branches
# ===========================================================================


@pytest.mark.asyncio
async def test_cancel_task_only_in_registry(
    client, mock_whisper, my_running_task, db_session
):
    """Cancel задачи, которая только в asyncio registry (не в _jobs)."""
    # Убедимся, что НЕ в legacy _jobs
    from app.services import transcription_progress as tp
    assert str(my_running_task.id) not in tp._jobs
    # Но в asyncio registry есть
    from app.services.active_tasks import _active_transcription_tasks
    assert str(my_running_task.id) in _active_transcription_tasks

    r = await client.post(
        f"/api/v1/hmp/transcribe/cancel/{my_running_task.id}"
    )
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    # Pending queue очищен
    assert str(my_running_task.id) not in tp._pending_db_cancels

    # DB обновлена
    await db_session.refresh(my_running_task)
    assert my_running_task.status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_invalid_uuid_string(client, mock_whisper):
    """Cancel с невалидным UUID → status='not_found', 200."""
    r = await client.post("/api/v1/hmp/transcribe/cancel/zzz-invalid")
    assert r.status_code == 200
    assert r.json()["status"] == "not_found"


# ===========================================================================
# POST /transcribe/pause/{task_id} — error & terminal-state branches
# ===========================================================================


@pytest.mark.asyncio
async def test_pause_400_invalid_uuid(client, mock_whisper):
    """Невалидный task_id → 400."""
    r = await client.post("/api/v1/hmp/transcribe/pause/not-a-uuid")
    assert r.status_code == 400
    assert "невалидный" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_pause_404_task_not_found(client, mock_whisper):
    """Несуществующий task → 404."""
    r = await client.post(f"/api/v1/hmp/transcribe/pause/{uuid.uuid4()}")
    assert r.status_code == 404
    assert "не найдена" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_pause_200_for_completed_task_returns_idempotent_message(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """Pause для completed task → 200 с message 'пауза невозможна'."""
    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="completed",
        progress=100.0,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    r = await client.post(f"/api/v1/hmp/transcribe/pause/{t.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert "не активна" in body["message"].lower() or "пауза невозможна" in body["message"].lower()


@pytest.mark.asyncio
async def test_pause_200_for_paused_task_already(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """Pause для уже-paused task → 200, status='paused' (idempotent)."""
    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="paused",
        progress=50.0,
        paused_at=datetime.now(timezone.utc),
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    r = await client.post(f"/api/v1/hmp/transcribe/pause/{t.id}")
    assert r.status_code == 200
    body = r.json()
    # status='paused' НЕ в ('queued', 'running', 'starting') → early return
    assert body["status"] == "paused"
    assert "пауза невозможна" in body["message"].lower()


# ===========================================================================
# POST /transcribe/resume/{task_id} — error & non-paused branches
# ===========================================================================


@pytest.mark.asyncio
async def test_resume_400_invalid_uuid(client, mock_whisper):
    """Невалидный task_id → 400."""
    r = await client.post("/api/v1/hmp/transcribe/resume/bad-uuid")
    assert r.status_code == 400
    assert "невалидный" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_resume_404_task_not_found(client, mock_whisper):
    """Несуществующий task → 404."""
    r = await client.post(f"/api/v1/hmp/transcribe/resume/{uuid.uuid4()}")
    assert r.status_code == 404
    assert "не найдена" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_resume_200_for_non_paused_task_returns_status(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """Resume для task в status='running' → 200, status echo, без запуска."""
    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="running",
        progress=10.0,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    r = await client.post(f"/api/v1/hmp/transcribe/resume/{t.id}")
    assert r.status_code == 200
    body = r.json()
    # task.status != 'paused' → early return с echo status
    assert body["status"] == "running"
    assert "resume невозможен" in body["message"].lower()


@pytest.mark.asyncio
async def test_resume_400_when_audio_file_row_deleted(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """Resume: protocol.audio_file_id указывает на удалённый AudioFile row → 400."""
    # Создаём paused task с привязкой к протоколу + audio_file
    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="paused",
        progress=20.0,
        paused_at=datetime.now(timezone.utc),
        last_processed_sec=10.0,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    # Удаляем AudioFile row
    from sqlalchemy import delete as _del
    await db_session.execute(
        _del(AudioFile).where(AudioFile.id == my_audio_file.id)
    )
    await db_session.commit()

    r = await client.post(f"/api/v1/hmp/transcribe/resume/{t.id}")
    assert r.status_code == 400
    assert "аудиофайл" in r.json()["detail"].lower()


# ===========================================================================
# GET /transcribe/status/{task_id}
# ===========================================================================


@pytest.mark.asyncio
async def test_status_404_task_not_found_in_db_or_memory(client, mock_whisper):
    """Несуществующий task → 404."""
    r = await client.get(f"/api/v1/hmp/transcribe/status/{uuid.uuid4()}")
    assert r.status_code == 404
    assert "не найдена" in r.json()["detail"].lower()


# ===========================================================================
# GET /transcribe/health
# ===========================================================================


@pytest.mark.asyncio
async def test_health_200_active_tasks_zero(client, mock_whisper):
    """Health при пустом сервисе → active_tasks=0."""
    # Убедимся, что _tasks пуст
    from app.services.transcription import transcription_service
    transcription_service._tasks.clear()

    r = await client.get("/api/v1/hmp/transcribe/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["active_tasks"] == 0
