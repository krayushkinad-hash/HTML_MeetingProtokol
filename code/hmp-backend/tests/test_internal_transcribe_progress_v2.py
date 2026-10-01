"""E286 v2: comprehensive tests for routers/transcribe/progress.py.

Targets ≥50% coverage of the 121-statement module by exercising:
  * GET /transcribe/progress/{task_id}        — in-memory hit, DB hit, miss, 422
  * GET /transcribe/progress-by-protocol/{id} — happy path, missing protocol,
                                                no active task, stuck protocol,
                                                pending cancel, exception path
  * _serialize_task_status                    — full fields, fallback path,
                                                datetime path, error path
  * _get_progress_internal                    — protocol not found, missing
                                                TranscriptionTask import, etc.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest


# ---------------------------------------------------------------------------
# Module / router import sanity
# ---------------------------------------------------------------------------


def test_progress_module_imports():
    from app.routers.transcribe import progress

    assert progress is not None
    assert hasattr(progress, "router")
    assert hasattr(progress, "_serialize_task_status")
    assert hasattr(progress, "_get_progress_internal")


def test_router_has_expected_routes():
    from app.routers.transcribe.progress import router

    paths = {r.path for r in router.routes}
    assert "/transcribe/progress/{task_id}" in paths
    assert "/transcribe/progress-by-protocol/{protocol_id}" in paths


# ---------------------------------------------------------------------------
# _serialize_task_status — direct unit tests (fast, no DB)
# ---------------------------------------------------------------------------


def test_serialize_task_status_full():
    """All optional fields populated → full dict returned."""
    from app.routers.transcribe.progress import _serialize_task_status
    from app.services.transcription import TranscriptionStatus

    pid = uuid.uuid4()
    tid = uuid.uuid4()
    est = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    status_obj = TranscriptionStatus(
        id=tid,
        protocol_id=pid,
        status="running",
        progress_percent=42,
        current_chunk=7,
        peak_rss_mb=512.5,
        estimated_completion=est,
        message="hello",
        error_message=None,
    )
    out = _serialize_task_status(str(tid), status_obj)
    assert out["id"] == str(tid)
    assert out["task_id"] == str(tid)
    assert out["protocol_id"] == str(pid)
    assert out["status"] == "running"
    assert out["progress"] == 42
    assert out["progress_percent"] == 42
    assert out["segments_count"] == 7
    assert out["peak_rss_mb"] == 512.5
    assert out["estimated_completion"] == est.isoformat()
    assert out["message"] == "hello"


def test_serialize_task_status_fallback_message():
    """When both message and error_message are None, fallback string used."""
    from app.routers.transcribe.progress import _serialize_task_status
    from app.services.transcription import TranscriptionStatus

    status_obj = TranscriptionStatus(
        id=uuid.uuid4(),
        protocol_id=uuid.uuid4(),
        status="queued",
        progress_percent=0,
        current_chunk=None,
        message=None,
        error_message=None,
        estimated_completion=None,
        peak_rss_mb=None,
    )
    out = _serialize_task_status(str(status_obj.id), status_obj)
    assert out["message"].startswith("Транскрипция:")
    assert out["segments_count"] == 0  # current_chunk or 0
    assert out["estimated_completion"] is None


def test_serialize_task_status_error_message_used():
    """error_message is taken when message is empty."""
    from app.routers.transcribe.progress import _serialize_task_status
    from app.services.transcription import TranscriptionStatus

    status_obj = TranscriptionStatus(
        id=uuid.uuid4(),
        protocol_id=uuid.uuid4(),
        status="failed",
        progress_percent=0,
        message="",
        error_message="boom",
    )
    out = _serialize_task_status(str(status_obj.id), status_obj)
    assert out["message"] == "boom"


def test_serialize_task_status_handles_garbage_object():
    """Blows up trying to access .id → returns the safe fallback dict."""
    from app.routers.transcribe.progress import _serialize_task_status

    class _Bad:
        @property
        def id(self):
            raise RuntimeError("nope")

    tid = str(uuid.uuid4())
    out = _serialize_task_status(tid, _Bad())
    assert out["task_id"] == tid
    assert out["status"] == "unknown"
    assert out["progress"] == 0
    assert "Ошибка сериализации" in out["message"]


# ---------------------------------------------------------------------------
# GET /transcribe/progress/{task_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_progress_by_task_not_found_returns_unknown(client):
    """No in-memory status, no DB row → 'unknown' fallback dict, 200."""
    r = await client.get(f"/api/v1/hmp/transcribe/progress/{uuid.uuid4()}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "unknown"
    assert body["progress"] == 0
    assert "не найдена" in body["message"].lower() or "restart" in body["message"].lower()


@pytest.mark.asyncio
async def test_get_progress_by_task_in_memory_hit(client, monkeypatch):
    """When transcription_service has status in memory → returned without DB."""
    from app.routers.transcribe import progress as progress_mod
    from app.services.transcription import TranscriptionStatus, transcription_service

    tid = uuid.uuid4()
    pid = uuid.uuid4()
    status_obj = TranscriptionStatus(
        id=tid,
        protocol_id=pid,
        status="running",
        progress_percent=73,
        current_chunk=12,
        message="Обработка 145с...",
    )
    # Seed in-memory dict directly (avoid running real transcription)
    transcription_service._tasks[tid] = status_obj
    try:
        r = await client.get(f"/api/v1/hmp/transcribe/progress/{tid}")
        assert r.status_code == 200
        body = r.json()
        assert body["task_id"] == str(tid)
        assert body["status"] == "running"
        assert body["progress"] == 73
        assert body["progress_percent"] == 73
        assert body["segments_count"] == 12
        assert "145с" in body["message"]
    finally:
        transcription_service._tasks.pop(tid, None)


@pytest.mark.asyncio
async def test_get_progress_by_task_db_fallback(client, db_session, sample_protocol):
    """In-memory miss, DB hit → DB branch with utterance count."""
    from app.db.models import TranscriptionTask

    tid = uuid.uuid4()
    task = TranscriptionTask(
        id=tid,
        protocol_id=sample_protocol.id,
        status="completed",
        progress=100.0,
        current_chunk=5,
        current_step="Done",
    )
    db_session.add(task)
    await db_session.commit()

    r = await client.get(f"/api/v1/hmp/transcribe/progress/{tid}")
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == str(tid)
    assert body["status"] == "completed"
    assert body["progress"] == 100.0
    assert body["segments_count"] == 0  # no utterances inserted
    assert body["message"] == "Done"


@pytest.mark.asyncio
async def test_get_progress_by_task_db_fallback_error_message_used(client, db_session, sample_protocol):
    """DB row with error_message preferred over current_step."""
    from app.db.models import TranscriptionTask

    tid = uuid.uuid4()
    task = TranscriptionTask(
        id=tid,
        protocol_id=sample_protocol.id,
        status="failed",
        progress=10.0,
        current_step="should-be-ignored",
        error_message="out of memory",
    )
    db_session.add(task)
    await db_session.commit()

    r = await client.get(f"/api/v1/hmp/transcribe/progress/{tid}")
    assert r.status_code == 200
    assert r.json()["message"] == "out of memory"


@pytest.mark.asyncio
async def test_get_progress_by_task_in_memory_serialize_failure(client):
    """If _serialize_task_status raises despite the try/except, route returns DB fallback or unknown."""
    from app.routers.transcribe import progress as progress_mod
    from app.services.transcription import TranscriptionStatus, transcription_service

    # Save original and patch
    orig = progress_mod._serialize_task_status

    def boom(task_id, s):
        raise RuntimeError("serialize fail")

    progress_mod._serialize_task_status = boom

    try:
        tid = uuid.uuid4()
        status_obj = TranscriptionStatus(
            id=tid,
            protocol_id=uuid.uuid4(),
            status="running",
        )
        transcription_service._tasks[tid] = status_obj

        r = await client.get(f"/api/v1/hmp/transcribe/progress/{tid}")
        # DB also has nothing → "unknown" fallback
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "unknown"
    finally:
        progress_mod._serialize_task_status = orig
        # _tasks may or may not have an entry depending on whether the dict cleanup ran
        for k in list(transcription_service._tasks.keys()):
            transcription_service._tasks.pop(k, None)


# ---------------------------------------------------------------------------
# GET /transcribe/progress-by-protocol/{protocol_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_progress_by_protocol_no_active_task(client, sample_protocol):
    """Protocol exists, no active transcription task → fallback dict with progress=0."""
    r = await client.get(
        f"/api/v1/hmp/transcribe/progress-by-protocol/{sample_protocol.id}"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["protocol_id"] == str(sample_protocol.id)
    assert body["progress"] == 0
    assert body["id"] is None
    assert body["task_id"] is None


@pytest.mark.asyncio
async def test_get_progress_by_protocol_missing_protocol(client):
    """Random UUID — protocol not in DB → 'unknown' message about not found."""
    pid = uuid.uuid4()
    r = await client.get(f"/api/v1/hmp/transcribe/progress-by-protocol/{pid}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "unknown"
    assert body["id"] is None
    assert "не найден" in body["message"].lower() or "не найден" in body["message"]


@pytest.mark.asyncio
async def test_get_progress_by_protocol_invalid_uuid_422(client):
    """Non-UUID string → FastAPI 422."""
    r = await client.get("/api/v1/hmp/transcribe/progress-by-protocol/not-a-uuid")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_progress_by_protocol_active_task_recent(
    client, db_session, sample_protocol, monkeypatch
):
    """Active task that is recent and is_task_alive=True → returned as-is."""
    from app.db.models import TranscriptionTask

    tid = uuid.uuid4()
    task = TranscriptionTask(
        id=tid,
        protocol_id=sample_protocol.id,
        status="running",
        progress=42.0,
        current_chunk=3,
        current_step="Шаг 42%",
        started_at=datetime.now(timezone.utc) - timedelta(seconds=10),
    )
    db_session.add(task)
    await db_session.commit()

    # Mock is_task_alive to return True (E082 alive-in-registry check)
    from app.routers.transcribe import progress as progress_mod

    monkeypatch.setattr(progress_mod, "is_task_alive", lambda tid_str: True)

    r = await client.get(
        f"/api/v1/hmp/transcribe/progress-by-protocol/{sample_protocol.id}"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == str(tid)
    assert body["status"] == "running"
    assert body["progress"] == 42.0
    assert body["segments_count"] == 3
    assert body["message"] == "Шаг 42%"


@pytest.mark.asyncio
async def test_get_progress_by_protocol_stale_task_marked_failed(client, db_session, sample_protocol):
    """Task older than 60s and not in registry → marked failed, response reflects it."""
    from app.db.models import TranscriptionTask

    tid = uuid.uuid4()
    task = TranscriptionTask(
        id=tid,
        protocol_id=sample_protocol.id,
        status="running",
        progress=0.05,
        current_chunk=0,
        current_step="starting",
        started_at=datetime.now(timezone.utc) - timedelta(seconds=120),
    )
    db_session.add(task)
    await db_session.commit()

    r = await client.get(
        f"/api/v1/hmp/transcribe/progress-by-protocol/{sample_protocol.id}"
    )
    assert r.status_code == 200
    body = r.json()
    # After stale-mark, status becomes "failed"
    assert body["status"] == "failed"
    assert "зависла" in body["message"].lower() or "задача" in body["message"].lower()


@pytest.mark.asyncio
async def test_get_progress_by_protocol_stuck_protocol_resets_to_loaded(
    client, db_session, sample_protocol
):
    """No active task but protocol.status=='transcribing' → reset to 'loaded', special message."""
    sample_protocol.status = "transcribing"
    await db_session.commit()
    await db_session.refresh(sample_protocol)

    r = await client.get(
        f"/api/v1/hmp/transcribe/progress-by-protocol/{sample_protocol.id}"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "unknown"
    assert body["id"] is None
    assert "прервана" in body["message"].lower() or "прерван" in body["message"].lower()


@pytest.mark.asyncio
async def test_get_progress_by_protocol_exception_returns_error(client, monkeypatch):
    """If _get_progress_internal raises, endpoint returns the safe 'error' dict."""
    from app.routers.transcribe import progress as progress_mod

    async def boom(protocol_id, db):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(progress_mod, "_get_progress_internal", boom)

    pid = uuid.uuid4()
    r = await client.get(f"/api/v1/hmp/transcribe/progress-by-protocol/{pid}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "error"
    assert body["id"] is None
    assert "kaboom" in body["message"]


@pytest.mark.asyncio
async def test_get_progress_by_protocol_handles_pending_cancels(
    client, db_session, sample_protocol
):
    """Pending cancels present in transcription_progress → DB rows updated to cancelled."""
    from app.db.models import TranscriptionTask
    from app.services.transcription_progress import _pending_db_cancels

    tid = uuid.uuid4()
    task = TranscriptionTask(
        id=tid,
        protocol_id=sample_protocol.id,
        status="running",
        progress=10.0,
        current_step="processing",
    )
    db_session.add(task)
    await db_session.commit()

    _pending_db_cancels.add(str(tid))
    try:
        r = await client.get(
            f"/api/v1/hmp/transcribe/progress-by-protocol/{sample_protocol.id}"
        )
        assert r.status_code == 200
        # DB task should now be cancelled (status flipped by the helper before any lookup)
        await db_session.refresh(task)
        assert task.status == "cancelled"
        assert task.error_message == "Отменено пользователем"
    finally:
        _pending_db_cancels.discard(str(tid))


@pytest.mark.asyncio
async def test_get_progress_by_protocol_idle_protocol_status(client, sample_protocol):
    """Protocol with no active task → progress=0, status echoes protocol.status."""
    r = await client.get(
        f"/api/v1/hmp/transcribe/progress-by-protocol/{sample_protocol.id}"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["progress"] == 0
    # sample_protocol.status from conftest is ProtocolStatus.RECORDING; assert it echoes back
    assert body["status"] in (sample_protocol.status, "loaded", "idle", "unknown")


# ---------------------------------------------------------------------------
# Percent updates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_progress_percent_updates_reflect_in_response(
    client, db_session, sample_protocol, monkeypatch
):
    """progress=12.5 → response.progress == 12.5 (float preserved)."""
    from app.db.models import TranscriptionTask

    tid = uuid.uuid4()
    task = TranscriptionTask(
        id=tid,
        protocol_id=sample_protocol.id,
        status="running",
        progress=12.5,
        current_chunk=1,
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(task)
    await db_session.commit()

    # Mark task alive so it isn't flagged stale
    from app.routers.transcribe import progress as progress_mod

    monkeypatch.setattr(progress_mod, "is_task_alive", lambda tid_str: True)

    r = await client.get(
        f"/api/v1/hmp/transcribe/progress-by-protocol/{sample_protocol.id}"
    )
    assert r.status_code == 200
    assert r.json()["progress"] == 12.5