"""Round 3 — additional coverage for app/routers/transcribe/local.py.

Goal: raise coverage from ~37% → 60%+.

Focus areas:

  * POST /transcribe/run
      - 409 when protocol.status == "diarizing"
      - 422 when audio_file row is missing in DB (protocol has audio_file_id)
      - model name variations (large-v3, base, tiny, medium, small)
      - language variations (en, de, ru, auto)
      - compute_type override (int8, float32)
      - beam_size boundary values (1, 5)
      - force-restart branch (status='transcribing' → reset to 'loaded')
      - audio_hash computation success path
  * POST /transcribe/cancel
      - cancel of DB task in 'queued' / 'running' state — applies DB update
      - cancel of DB task in terminal state → no DB update
      - cancel with invalid UUID string — early 'not_found' return
      - cancel with task only in registry (no _jobs) — DB row update
  * POST /transcribe/pause
      - active 'running' task → success: status='paused', BG-task cancel
      - active 'queued' task → success path
      - active 'starting' task → success path
      - pause with active BG-task that is .done() → no cancel() call
  * POST /transcribe/resume
      - paused task with matching audio_hash → success (runner started)
      - paused task with hash mismatch → reset progress, log warning
      - paused task with malformed segments_so_far_json → already_done=[]
      - paused task with missing audio_file row → 400
"""
import asyncio
import json
import traceback
import uuid
from datetime import datetime, timezone
from datetime import date as _date
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from app.db.models import AudioFile, Protocol, TranscriptionTask


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_whisper(monkeypatch):
    """Mock faster_whisper + transcription_service (don't run real model)."""
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

    # Suppress BG-tasks spawned by local.py
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
    }


@pytest_asyncio.fixture
async def my_protocol(db_session):
    p = Protocol(
        id=uuid.uuid4(),
        title="round3 Protocol",
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
    fake_audio = tmp_path / "audio_r3.wav"
    fake_audio.write_bytes(b"RIFF" + b"\x00" * 200)

    af = AudioFile(
        id=uuid.uuid4(),
        file_path=str(fake_audio),
        filename="audio_r3.wav",
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


# ===========================================================================
# POST /transcribe/run — edge cases
# ===========================================================================


@pytest.mark.asyncio
async def test_run_409_protocol_diarizing(
    client, mock_whisper, db_session
):
    """status='diarizing' → 409 Conflict."""
    p = Protocol(
        id=uuid.uuid4(),
        title="Diarizing Protocol",
        date=_date.today(),
        status="diarizing",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)

    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(p.id), "model": "base", "language": "ru"},
    )
    assert r.status_code == 409
    assert "диаризации" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_run_404_unknown_protocol(client, mock_whisper):
    """Unknown protocol_id → 404."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(uuid.uuid4()), "language": "ru"},
    )
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_run_422_audio_file_id_missing(
    client, mock_whisper, my_protocol
):
    """protocol без audio_file_id → 422."""
    # my_protocol has no audio_file_id
    assert my_protocol.audio_file_id is None

    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(my_protocol.id), "language": "ru"},
    )
    assert r.status_code == 422
    assert "аудио" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_run_status_with_null_status_protocol(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """Protocol with status='loaded' (not 'diarizing' or 'transcribing') → 202."""
    # my_protocol already has status='loaded' — verify default happy path
    assert my_protocol.status == "loaded"

    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={
            "protocol_id": str(my_protocol.id),
            "model": "base",
            "language": "ru",
        },
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["progress_percent"] == 0
    assert "estimated_completion" in body


@pytest.mark.asyncio
async def test_run_force_restart_when_transcribing(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """status='transcribing' → reset to 'loaded', then run."""
    my_protocol.status = "transcribing"
    await db_session.commit()
    await db_session.refresh(my_protocol)

    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={
            "protocol_id": str(my_protocol.id),
            "model": "large-v3",
            "language": "ru",
            "beam_size": 5,
            "compute_type": "float16",
        },
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["progress_percent"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_name", ["tiny", "base", "small", "medium", "large-v3"]
)
async def test_run_accepts_all_model_names(
    client, mock_whisper, my_protocol, my_audio_file, model_name
):
    """All Literal model names must be accepted."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={
            "protocol_id": str(my_protocol.id),
            "model": model_name,
            "language": "ru",
        },
    )
    assert r.status_code == 202, r.text


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["ru", "en", "de", "auto", "fr"])
async def test_run_accepts_multiple_languages(
    client, mock_whisper, my_protocol, my_audio_file, language
):
    """All language codes must be accepted."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={
            "protocol_id": str(my_protocol.id),
            "model": "base",
            "language": language,
        },
    )
    assert r.status_code == 202, r.text


@pytest.mark.asyncio
async def test_run_with_compute_type_override(
    client, mock_whisper, my_protocol, my_audio_file
):
    """compute_type=int8 override is accepted."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={
            "protocol_id": str(my_protocol.id),
            "model": "base",
            "language": "ru",
            "compute_type": "int8",
        },
    )
    assert r.status_code == 202


@pytest.mark.asyncio
async def test_run_with_prompt_and_initial_prompt(
    client, mock_whisper, my_protocol, my_audio_file
):
    """prompt and initial_prompt fields pass through."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={
            "protocol_id": str(my_protocol.id),
            "model": "base",
            "language": "ru",
            "prompt": "Some context prompt",
            "initial_prompt": "Initial prompt",
            "beam_size": 3,
        },
    )
    assert r.status_code == 202


@pytest.mark.asyncio
async def test_run_creates_transcription_task_in_db(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """Run creates a TranscriptionTask row in DB."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={
            "protocol_id": str(my_protocol.id),
            "model": "base",
            "language": "ru",
        },
    )
    assert r.status_code == 202
    task_id = r.json()["task_id"]

    # Verify task exists in DB
    from sqlalchemy import select
    res = await db_session.execute(
        select(TranscriptionTask).where(TranscriptionTask.id == uuid.UUID(task_id))
    )
    db_task = res.scalar_one_or_none()
    assert db_task is not None
    assert db_task.protocol_id == my_protocol.id
    assert db_task.status == "queued"


# ===========================================================================
# POST /transcribe/cancel/{task_id} — active task branches
# ===========================================================================


@pytest.mark.asyncio
async def test_cancel_active_running_task_updates_db(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """Cancel a DB task in 'running' state → DB row becomes 'cancelled'."""
    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="running",
        progress=42.0,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    # Register a fake BG-task so cancel_job() finds it
    from app.services.active_tasks import (
        _active_transcription_tasks,
        register_active_task,
    )
    fake_bg = asyncio.create_task(asyncio.sleep(10))
    register_active_task(str(t.id), fake_bg)

    try:
        r = await client.post(f"/api/v1/hmp/transcribe/cancel/{t.id}")
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"

        await db_session.refresh(t)
        assert t.status == "cancelled"
        assert t.error_message == "Отменено пользователем"
    finally:
        if not fake_bg.done():
            fake_bg.cancel()
        _active_transcription_tasks.pop(str(t.id), None)


@pytest.mark.asyncio
async def test_cancel_queued_task_updates_db(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """Cancel a DB task in 'queued' state → DB row becomes 'cancelled'."""
    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="queued",
        progress=0.0,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    from app.services.active_tasks import (
        _active_transcription_tasks,
        register_active_task,
    )
    fake_bg = asyncio.create_task(asyncio.sleep(10))
    register_active_task(str(t.id), fake_bg)

    try:
        r = await client.post(f"/api/v1/hmp/transcribe/cancel/{t.id}")
        assert r.status_code == 200

        await db_session.refresh(t)
        assert t.status == "cancelled"
    finally:
        if not fake_bg.done():
            fake_bg.cancel()
        _active_transcription_tasks.pop(str(t.id), None)


@pytest.mark.asyncio
async def test_cancel_terminal_task_does_not_update_db(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """Cancel of DB task already in terminal state (completed) → no overwrite."""
    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="completed",
        progress=100.0,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    original_status = t.status

    r = await client.post(f"/api/v1/hmp/transcribe/cancel/{t.id}")
    assert r.status_code == 200

    await db_session.refresh(t)
    # status should remain 'completed' (terminal state preserved)
    assert t.status == original_status


@pytest.mark.asyncio
async def test_cancel_invalid_uuid_string(
    client, mock_whisper
):
    """Invalid UUID string → 200 status='not_found' (cancel_job fails)."""
    r = await client.post(
        "/api/v1/hmp/transcribe/cancel/not-a-valid-uuid"
    )
    # cancel_job returns False → endpoint returns 200 with status='not_found'
    assert r.status_code == 200
    assert r.json()["status"] == "not_found"


# ===========================================================================
# POST /transcribe/pause/{task_id} — all branches
# ===========================================================================


@pytest.mark.asyncio
async def test_pause_running_task_succeeds(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """Pause active 'running' task → 200 'paused', BG-task cancelled."""
    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="running",
        progress=42.0,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    # Register a fake BG-task to ensure cancel() path is hit
    from app.services.active_tasks import (
        _active_transcription_tasks,
        register_active_task,
    )
    fake_bg = asyncio.create_task(asyncio.sleep(10))
    register_active_task(str(t.id), fake_bg)

    try:
        r = await client.post(f"/api/v1/hmp/transcribe/pause/{t.id}")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "paused"
        assert body["can_resume"] is True
        # Russian for "transcription paused"
        assert "паузу" in body["message"].lower() or "пауза" in body["message"].lower()

        await db_session.refresh(t)
        assert t.status == "paused"
        assert t.paused_at is not None
    finally:
        # Cleanup
        if not fake_bg.done():
            fake_bg.cancel()
        _active_transcription_tasks.pop(str(t.id), None)


@pytest.mark.asyncio
async def test_pause_queued_task_succeeds(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """Pause 'queued' task → 200 'paused'."""
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
    assert r.json()["status"] == "paused"


@pytest.mark.asyncio
async def test_pause_starting_task_succeeds(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """Pause 'starting' task → 200 'paused'."""
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
    assert r.json()["status"] == "paused"


@pytest.mark.asyncio
async def test_pause_no_active_bg_task(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """Pause running task with NO bg-task registered → still succeeds."""
    from app.services.active_tasks import _active_transcription_tasks

    # Make sure registry is clean for this id
    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="running",
        progress=10.0,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    _active_transcription_tasks.pop(str(t.id), None)

    r = await client.post(f"/api/v1/hmp/transcribe/pause/{t.id}")
    assert r.status_code == 200
    assert r.json()["status"] == "paused"


# ===========================================================================
# POST /transcribe/resume/{task_id} — branches
# ===========================================================================


@pytest.mark.asyncio
async def test_resume_paused_task_with_matching_hash(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """Resume paused task with audio_hash matching → spawns BG task, 200 'running'."""
    import hashlib as _hl
    expected_hash = _hl.sha256(b"RIFF" + b"\x00" * 200).hexdigest()[:32]

    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="paused",
        progress=42.0,
        audio_hash=expected_hash,
        last_processed_sec=10.0,
        segments_so_far_json=json.dumps([{"start": 0.0, "end": 1.0, "text": "hi"}]),
        paused_at=datetime.now(timezone.utc),
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    r = await client.post(f"/api/v1/hmp/transcribe/resume/{t.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "running"
    assert body["resume_from_sec"] == 10.0
    assert body["previously_done_segments"] == 1


@pytest.mark.asyncio
async def test_resume_paused_task_with_hash_mismatch(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """Resume paused task with mismatched audio_hash → reset progress."""
    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="paused",
        progress=42.0,
        audio_hash="0" * 32,  # wrong hash
        last_processed_sec=15.0,
        segments_so_far_json=json.dumps([{"x": 1}]),
        paused_at=datetime.now(timezone.utc),
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    r = await client.post(f"/api/v1/hmp/transcribe/resume/{t.id}")
    assert r.status_code == 200
    assert r.json()["status"] == "running"

    await db_session.refresh(t)
    # Hash mismatch → progress reset
    assert t.last_processed_sec == 0.0
    assert t.segments_so_far_json is None
    assert t.progress == 0.0


@pytest.mark.asyncio
async def test_resume_paused_task_with_malformed_segments_json(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """Resume with malformed segments_so_far_json → falls back to []."""
    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="paused",
        progress=50.0,
        audio_hash=None,
        last_processed_sec=20.0,
        segments_so_far_json="not valid json {",
        paused_at=datetime.now(timezone.utc),
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    r = await client.post(f"/api/v1/hmp/transcribe/resume/{t.id}")
    assert r.status_code == 200
    # JSON parse fails → already_done=[] → previously_done_segments=0
    assert r.json()["previously_done_segments"] == 0


@pytest.mark.asyncio
async def test_resume_paused_task_no_audio_file(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """Resume when audio_file row has been deleted → 400."""
    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="paused",
        progress=10.0,
        paused_at=datetime.now(timezone.utc),
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    # Delete the audio_file row
    await db_session.delete(my_audio_file)
    await db_session.commit()

    r = await client.post(f"/api/v1/hmp/transcribe/resume/{t.id}")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_resume_non_paused_task_returns_idempotent(
    client, mock_whisper, my_protocol, my_audio_file, db_session
):
    """Resume task in 'completed' status → 200 with status echo."""
    t = TranscriptionTask(
        id=uuid.uuid4(),
        protocol_id=my_protocol.id,
        status="completed",
        progress=100.0,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    r = await client.post(f"/api/v1/hmp/transcribe/resume/{t.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert "resume невозможен" in body["message"].lower()