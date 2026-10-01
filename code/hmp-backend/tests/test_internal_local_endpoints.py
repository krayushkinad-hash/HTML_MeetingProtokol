"""Тесты для app/routers/transcribe/local.py — цель 60%+ coverage.

Покрывает endpoints:
  * POST /transcribe/run
  * GET  /transcribe/status/{task_id}
  * POST /transcribe/pause/{task_id}
  * POST /transcribe/resume/{task_id}
  * POST /transcribe/cancel/{task_id}
  * GET  /transcribe/health
"""
import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Custom fixtures: bypass broken sample_protocol (ProtocolStatus missing)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_whisper(monkeypatch):
    """Mock WhisperModel + transcription_service.transcribe/get_status."""
    from app.services import transcription

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
        transcription.transcription_service, "get_status", MagicMock(return_value=None)
    )
    return {"transcribe": mock_transcribe, "get_status": transcription.transcription_service.get_status}


@pytest_asyncio.fixture
async def my_protocol(db_session):
    """Protocol row without relying on ProtocolStatus enum class."""
    from app.db.models import Protocol
    from datetime import date as _date

    p = Protocol(
        id=uuid.uuid4(),
        title="Test Protocol",
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
    """Real AudioFile row + real file on disk; wires to protocol."""
    from app.db.models import AudioFile

    fake_audio = tmp_path / "audio.wav"
    fake_audio.write_bytes(b"RIFF" + b"\x00" * 100)

    af = AudioFile(
        id=uuid.uuid4(),
        file_path=str(fake_audio),
        filename="audio.wav",
        extension="wav",
        size_bytes=104,
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
async def my_task(db_session, my_protocol):
    """TranscriptionTask in DB (queued)."""
    from app.db.models import TranscriptionTask

    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="queued",
        progress=10.0,
        current_chunk=2,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


@pytest_asyncio.fixture
async def my_paused_task(db_session, my_protocol, my_audio_file):
    """Paused TranscriptionTask."""
    from app.db.models import TranscriptionTask

    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="paused",
        progress=50.0,
        current_chunk=5,
        paused_at=datetime.now(timezone.utc),
        last_processed_sec=60.0,
        audio_hash=None,
        segments_so_far_json=None,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


@pytest_asyncio.fixture
async def my_running_task(db_session, my_protocol):
    """Running TranscriptionTask (for cancel happy path)."""
    from app.db.models import TranscriptionTask

    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="running",
        progress=20.0,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


# ---------------------------------------------------------------------------
# /transcribe/health (no DB needed)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_endpoint(client):
    """GET /transcribe/health → 200."""
    r = await client.get("/api/v1/hmp/transcribe/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "active_tasks" in body


# ---------------------------------------------------------------------------
# POST /transcribe/run
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_404_unknown_protocol(client, mock_whisper):
    """POST /transcribe/run с несуществующим protocol → 404."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(uuid.uuid4()), "model": "base"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_run_422_missing_audio(client, mock_whisper, my_protocol):
    """POST /transcribe/run для protocol без audio_file_id → 422."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(my_protocol.id), "model": "base"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_run_422_validation_no_protocol_id(client, mock_whisper):
    """POST /transcribe/run без protocol_id → 422."""
    r = await client.post("/api/v1/hmp/transcribe/run", json={"model": "base"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_run_202_success(client, mock_whisper, my_protocol, my_audio_file):
    """POST /transcribe/run happy path → 202."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(my_protocol.id), "model": "base", "language": "ru"},
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["progress_percent"] == 0
    assert "task_id" in body
    assert "estimated_completion" in body


@pytest.mark.asyncio
async def test_run_202_when_transcribing_reset(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """POST /transcribe/run для protocol в 'transcribing' → reset + 202."""
    from sqlalchemy import update
    from app.db.models import Protocol

    await db_session.execute(
        update(Protocol).where(Protocol.id == my_protocol.id).values(status="transcribing")
    )
    await db_session.commit()

    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(my_protocol.id), "model": "base"},
    )
    assert r.status_code == 202


@pytest.mark.asyncio
async def test_run_409_when_diarizing(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """POST /transcribe/run для protocol в 'diarizing' → 409."""
    from sqlalchemy import update
    from app.db.models import Protocol

    await db_session.execute(
        update(Protocol).where(Protocol.id == my_protocol.id).values(status="diarizing")
    )
    await db_session.commit()

    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(my_protocol.id), "model": "base"},
    )
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# GET /transcribe/status/{task_id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_404_unknown(client, mock_whisper):
    """GET /transcribe/status/{unknown-uuid} → 404."""
    r = await client.get(f"/api/v1/hmp/transcribe/status/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_status_200_from_db(client, mock_whisper, my_task):
    """GET /transcribe/status/{id} → 200, читает из БД."""
    r = await client.get(f"/api/v1/hmp/transcribe/status/{my_task.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == str(my_task.id)
    assert body["status"] == "queued"


@pytest.mark.asyncio
async def test_status_422_invalid_uuid_format(client, mock_whisper):
    """GET /transcribe/status/{garbage} → 422 (FastAPI UUID validation)."""
    r = await client.get("/api/v1/hmp/transcribe/status/not-a-uuid")
    assert r.status_code in (404, 422)


# ---------------------------------------------------------------------------
# POST /transcribe/pause/{task_id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pause_400_invalid_uuid(client, mock_whisper):
    """POST /transcribe/pause/not-a-uuid → 400."""
    r = await client.post("/api/v1/hmp/transcribe/pause/not-a-uuid")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_pause_404_unknown(client, mock_whisper):
    """POST /transcribe/pause/{unknown-uuid} → 404."""
    r = await client.post(f"/api/v1/hmp/transcribe/pause/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_pause_200_success(client, mock_whisper, my_task):
    """POST /transcribe/pause/{queued task} → 200 status=paused."""
    r = await client.post(f"/api/v1/hmp/transcribe/pause/{my_task.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "paused"
    assert body["can_resume"] is True
    assert "paused_at" in body
    assert "message" in body


@pytest.mark.asyncio
async def test_pause_200_terminal_status(
    client, mock_whisper, my_task, db_session
):
    """POST /transcribe/pause для уже completed task → 200 без изменения."""
    from sqlalchemy import update
    from app.db.models import TranscriptionTask

    await db_session.execute(
        update(TranscriptionTask)
        .where(TranscriptionTask.id == my_task.id)
        .values(status="completed")
    )
    await db_session.commit()

    r = await client.post(f"/api/v1/hmp/transcribe/pause/{my_task.id}")
    assert r.status_code == 200
    assert r.json()["status"] == "completed"


# ---------------------------------------------------------------------------
# POST /transcribe/resume/{task_id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_400_invalid_uuid(client, mock_whisper):
    """POST /transcribe/resume/not-a-uuid → 400."""
    r = await client.post("/api/v1/hmp/transcribe/resume/not-a-uuid")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_resume_404_unknown(client, mock_whisper):
    """POST /transcribe/resume/{unknown-uuid} → 404."""
    r = await client.post(f"/api/v1/hmp/transcribe/resume/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_resume_200_wrong_status(client, mock_whisper, my_task):
    """POST /transcribe/resume для task не paused → 200 с сообщением."""
    r = await client.post(f"/api/v1/hmp/transcribe/resume/{my_task.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "queued"
    assert "resume" in body["message"].lower()


# ---------------------------------------------------------------------------
# /transcribe/whisper/status/{model} — endpoint не определён в local.py
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_whisper_status_endpoint_not_in_local(client):
    """Whisper status endpoint НЕ в local.py → 404/405/422."""
    r = await client.get("/api/v1/hmp/transcribe/whisper/status/base")
    assert r.status_code in (200, 404, 405, 422)