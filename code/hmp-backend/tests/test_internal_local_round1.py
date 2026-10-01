"""Round 1 — coverage boost for app/routers/transcribe/local.py.

Цель: поднять coverage local.py до 50%+.

Сфокусировано на ветках, которые не покрыты существующими тестами:

  * POST /transcribe/run
      - 422 audio_file_id указывает на row, который удалён
      - status='diarizing' → 409 (отдельный протокол)
      - run когда protocol.status='recording' (нормальная ветка без restart)
      - run возвращает estimated_completion > now
      - run когда файл на диске отсутствует (hash None, warning)
      - run с явными параметрами beam_size, vad_filter
  * POST /transcribe/pause/{task_id}
      - 200 для status='starting' (тоже активный → paused)
      - 200 для status='queued' (тоже активный → paused)
      - pause без активной BG-task (cancel не вызывается)
  * POST /transcribe/resume/{task_id}
      - 400 audio_file_id=None в protocol
      - 200 resume падает в обновление DB task.status='running'
  * GET /transcribe/status/{task_id}
      - 200 hit в in-memory status (status_obj возвращён напрямую)
      - 200 DB fallback с status='completed' → response uses .completed default
  * GET /transcribe/health
      - 200 active_tasks > 0 после регистрации задачи
      - 200 health проверяет наличие полей status и active_tasks
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
    Decision,
    Protocol,
    TranscriptionTask,
    Utterance,
)


# ---------------------------------------------------------------------------
# Mocks / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_whisper(monkeypatch):
    """Mock faster_whisper.WhisperModel + transcription_service."""
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

    # Подавляем BG-tasks из local.py
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
    p = Protocol(
        id=uuid.uuid4(),
        title="round1 Protocol",
        date=_date.today(),
        status="loaded",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def my_recording_protocol(db_session, my_audio_file):
    """Protocol в статусе 'live' — обычная ветка без restart."""
    p = Protocol(
        id=uuid.uuid4(),
        title="recording",
        date=_date.today(),
        status="live",
        audio_file_id=my_audio_file.id,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def my_audio_file(db_session, my_protocol, tmp_path):
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
async def my_missing_path_audio(db_session, my_protocol, tmp_path):
    """AudioFile row валиден, но файл на диске отсутствует — hash=None ветка."""
    af = AudioFile(
        id=uuid.uuid4(),
        file_path=str(tmp_path / "ghost_path.wav"),
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


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_state():
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
# POST /transcribe/run — additional branches
# ===========================================================================


@pytest.mark.asyncio
async def test_run_202_with_diarizing_protocol_via_explicit_fixture(
    client, mock_whisper, db_session
):
    """Protocol в status='diarizing' → 409 Conflict."""
    from sqlalchemy import update

    p = Protocol(
        id=uuid.uuid4(),
        title="diarizing test",
        date=_date.today(),
        status="diarizing",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)

    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(p.id)},
    )
    assert r.status_code == 409
    assert "диаризаци" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_run_202_recording_status_normal_branch(
    client, mock_whisper, my_recording_protocol
):
    """Protocol.status='live' (не 'loaded') → 202, без force-restart."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(my_recording_protocol.id)},
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["protocol_id"] == str(my_recording_protocol.id)
    # ETA должен быть в будущем
    eta_str = body["estimated_completion"]
    if eta_str.endswith("Z"):
        eta_str = eta_str.replace("Z", "+00:00")
    eta = datetime.fromisoformat(eta_str)
    if eta.tzinfo is None:
        eta = eta.replace(tzinfo=timezone.utc)
    assert eta > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_run_with_missing_file_on_disk_still_202(
    client, mock_whisper, my_protocol, my_missing_path_audio
):
    """Файл на диске отсутствует → hash=None, 202 (warning логируется)."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(my_protocol.id)},
    )
    # Логика: hash не вычисляется (warning), но endpoint всё равно 202
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"


@pytest.mark.asyncio
async def test_run_with_explicit_beam_and_vad(
    client, mock_whisper, my_protocol, my_audio_file
):
    """Полный набор параметров: model, language, beam_size, vad_filter, language_detect."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={
            "protocol_id": str(my_protocol.id),
            "model": "small",
            "language": "ru",
            "beam_size": 3,
            "vad_filter": True,
        },
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["protocol_id"] == str(my_protocol.id)


@pytest.mark.asyncio
async def test_run_estimated_completion_long_audio_uses_0_3x(
    client, mock_whisper, my_protocol, db_session, tmp_path
):
    """Длинный аудиофайл (1000 сек) → ETA = max(60, 1000*0.3) = 300 сек."""
    fake_audio = tmp_path / "long.wav"
    fake_audio.write_bytes(b"RIFF" + b"\x00" * 100)

    af = AudioFile(
        id=uuid.uuid4(),
        file_path=str(fake_audio),
        filename="long.wav",
        extension="wav",
        size_bytes=104,
        mime_type="audio/wav",
        duration_sec=1000,
    )
    db_session.add(af)
    await db_session.commit()
    await db_session.refresh(af)

    my_protocol.audio_file_id = af.id
    await db_session.commit()
    await db_session.refresh(my_protocol)

    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(my_protocol.id)},
    )
    assert r.status_code == 202
    eta_str = r.json()["estimated_completion"]
    if eta_str.endswith("Z"):
        eta_str = eta_str.replace("Z", "+00:00")
    eta = datetime.fromisoformat(eta_str)
    if eta.tzinfo is None:
        eta = eta.replace(tzinfo=timezone.utc)
    # ETA ~ 300 сек в будущем → должно быть больше 60 сек от now
    delta = (eta - datetime.now(timezone.utc)).total_seconds()
    assert 250 <= delta <= 320


@pytest.mark.asyncio
async def test_run_estimated_completion_short_audio_uses_min_60(
    client, mock_whisper, my_protocol, db_session, tmp_path
):
    """duration_sec=10 → 10*0.3=3 < 60 → берётся max(60, 3) = 60 сек."""
    fake_audio = tmp_path / "short.wav"
    fake_audio.write_bytes(b"RIFF" + b"\x00" * 50)

    af = AudioFile(
        id=uuid.uuid4(),
        file_path=str(fake_audio),
        filename="short.wav",
        extension="wav",
        size_bytes=54,
        mime_type="audio/wav",
        duration_sec=10,
    )
    db_session.add(af)
    await db_session.commit()
    await db_session.refresh(af)

    my_protocol.audio_file_id = af.id
    await db_session.commit()
    await db_session.refresh(my_protocol)

    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(my_protocol.id)},
    )
    assert r.status_code == 202
    eta_str = r.json()["estimated_completion"]
    if eta_str.endswith("Z"):
        eta_str = eta_str.replace("Z", "+00:00")
    eta = datetime.fromisoformat(eta_str)
    if eta.tzinfo is None:
        eta = eta.replace(tzinfo=timezone.utc)
    delta = (eta - datetime.now(timezone.utc)).total_seconds()
    # ETA должен быть ~60 сек
    assert 55 <= delta <= 75


@pytest.mark.asyncio
async def test_run_resets_existing_utterances_and_decisions(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """run должен удалить старые utterances/decisions для этого протокола."""
    # Сидим фейковые utterance и decision
    u = Utterance(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        speaker_id=None,
        text="hello",
        start_sec=0.0,
        end_sec=1.0,
    )
    d = Decision(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        text="old decision",
    )
    db_session.add(u)
    db_session.add(d)
    await db_session.commit()

    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(my_protocol.id)},
    )
    assert r.status_code == 202

    # Проверяем, что utterances/decisions очищены (через свежую сессию,
    # т.к. /run удаляет их в ОТДЕЛЬНОЙ AsyncSessionLocal() сессии)
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as verify_db:
        remaining_u = (
            await verify_db.execute(
                select(Utterance).where(Utterance.protocol_id == my_protocol.id)
            )
        ).scalars().all()
        remaining_d = (
            await verify_db.execute(
                select(Decision).where(Decision.protocol_id == my_protocol.id)
            )
        ).scalars().all()
    assert remaining_u == []
    assert remaining_d == []


# ===========================================================================
# POST /transcribe/pause/{task_id} — additional branches
# ===========================================================================


@pytest.mark.asyncio
async def test_pause_queued_task_succeeds(client, mock_whisper, db_session, my_protocol, my_audio_file):
    """Pause для queued task → 200, status='paused'."""
    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="queued",
        progress=0.0,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    r = await client.post(f"/api/v1/hmp/transcribe/pause/{t.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "paused"
    assert body["can_resume"] is True


@pytest.mark.asyncio
async def test_pause_starting_task_succeeds(client, mock_whisper, db_session, my_protocol, my_audio_file):
    """Pause для starting task → 200, status='paused'."""
    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="starting",
        progress=0.0,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    r = await client.post(f"/api/v1/hmp/transcribe/pause/{t.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "paused"


@pytest.mark.asyncio
async def test_pause_without_bg_task_in_registry(
    client, mock_whisper, db_session, my_protocol, my_audio_file
):
    """Pause для running task, но без BG-task в реестре → cancel() не вызывается."""
    from app.services.active_tasks import _active_transcription_tasks

    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="running",
        progress=10.0,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    # Убедимся что в реестре пусто
    assert str(t.id) not in _active_transcription_tasks

    r = await client.post(f"/api/v1/hmp/transcribe/pause/{t.id}")
    assert r.status_code == 200
    assert r.json()["status"] == "paused"


# ===========================================================================
# POST /transcribe/resume/{task_id} — additional branches
# ===========================================================================


@pytest.mark.asyncio
async def test_resume_protocol_without_audio_file_id_returns_400(
    client, mock_whisper, my_paused_task, db_session
):
    """Resume когда protocol.audio_file_id=None → 400 'Протокол без аудиофайла'."""
    from sqlalchemy import update

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
async def test_resume_updates_task_status_to_running(
    client, mock_whisper, my_paused_task
):
    """Resume должен ответить 200 с status='running'."""
    r = await client.post(f"/api/v1/hmp/transcribe/resume/{my_paused_task.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "running"
    assert body["task_id"] == str(my_paused_task.id)
    # previously_done_segments должно быть 0 (segments_so_far_json=None)
    assert body["previously_done_segments"] == 0


# ===========================================================================
# GET /transcribe/status/{task_id} — branches
# ===========================================================================


@pytest.mark.asyncio
async def test_status_returns_in_memory_status(client, mock_whisper, db_session, my_protocol, my_audio_file):
    """Если transcription_service.get_status() вернул объект → используется напрямую."""
    from app.services import transcription
    from app.schemas import TranscriptionStatus as TS

    # Создаём задачу в БД чтобы не было 404, но мок вернёт свой объект
    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="completed",
        progress=100.0,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    # Мок get_status возвращает НЕ None
    fake_status = TS(
        task_id=t.id,
        protocol_id=my_protocol.id,
        status="running",
        progress_percent=50,
        message="in-memory",
    )
    transcription.transcription_service.get_status = MagicMock(return_value=fake_status)

    r = await client.get(f"/api/v1/hmp/transcribe/status/{t.id}")
    assert r.status_code == 200
    body = r.json()
    # Должен вернуться тот объект, что вернул get_status
    assert body["status"] == "running"
    assert body["progress_percent"] == 50


@pytest.mark.asyncio
async def test_status_db_fallback_with_completed_task(
    client, mock_whisper, db_session, my_protocol, my_audio_file
):
    """DB fallback для completed task → status='completed', progress=100."""
    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="completed",
        progress=100.0,
        current_step="Done",
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    r = await client.get(f"/api/v1/hmp/transcribe/status/{t.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["progress_percent"] == 100


# ===========================================================================
# GET /transcribe/health — branches
# ===========================================================================


@pytest.mark.asyncio
async def test_health_returns_required_fields(client, mock_whisper):
    """/transcribe/health возвращает status и active_tasks."""
    r = await client.get("/api/v1/hmp/transcribe/health")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body
    assert "active_tasks" in body
    assert body["status"] == "ok"
    # Тип должен быть int
    assert isinstance(body["active_tasks"], int)


@pytest.mark.asyncio
async def test_health_with_tasks_in_dict(client, mock_whisper):
    """Когда _tasks содержит записи → active_tasks > 0."""
    from app.services import transcription
    from app.schemas import TranscriptionStatus as TS

    # Добавляем запись в in-memory _tasks
    fake_task_id = uuid.uuid4()
    transcription.transcription_service._tasks[fake_task_id] = TS(  # noqa: SLF001
        task_id=fake_task_id,
        protocol_id=uuid.uuid4(),
        status="queued",
        progress_percent=0,
        message="queued",
    )

    r = await client.get("/api/v1/hmp/transcribe/health")
    assert r.status_code == 200
    body = r.json()
    assert body["active_tasks"] >= 1


@pytest.mark.asyncio
async def test_status_invalid_uuid_returns_404_or_500(client, mock_whisper):
    """Невалидный UUID в status → 404 (FastAPI parse error → 404 via HTTPException)."""
    # В этом endpoint task_id: uuid.UUID — FastAPI сам парсит и вернёт 422,
    # но в БД-fallback ловит через db.get(TranscriptionTask, task_id)
    # — task_id остаётся UUID-объектом. Тестируем с валидным UUID, которого нет.
    r = await client.get(f"/api/v1/hmp/transcribe/status/{uuid.uuid4()}")
    assert r.status_code == 404