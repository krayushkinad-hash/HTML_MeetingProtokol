"""Round-1 coverage tests for app/routers/transcribe/progress.py.

Target: 50%+ coverage on 121 statements.

Strategy: pure unit tests against module helpers + light HTTP tests through
the FastAPI app (covers both endpoints + 404/422 cases).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


API_PREFIX = "/api/v1/hmp"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_pending_cancels():
    """Reset transcription_progress pending-cancel set between tests."""
    from app.services import transcription_progress as tp
    from app.services.active_tasks import _active_transcription_tasks

    tp._pending_db_cancels.clear()
    _active_transcription_tasks.clear()
    yield
    tp._pending_db_cancels.clear()
    _active_transcription_tasks.clear()


def _make_status(
    task_id: uuid.UUID | None = None,
    protocol_id: uuid.UUID | None = None,
    status: str = "running",
    progress_percent: int = 42,
    current_chunk: int = 7,
    peak_rss_mb: float = 512.0,
    message: str | None = "Working...",
    error_message: str | None = None,
    estimated_completion: datetime | None = None,
):
    """Build a SimpleNamespace that mimics TranscriptionStatus."""
    return SimpleNamespace(
        id=task_id or uuid.uuid4(),
        protocol_id=protocol_id or uuid.uuid4(),
        status=status,
        progress_percent=progress_percent,
        current_chunk=current_chunk,
        peak_rss_mb=peak_rss_mb,
        message=message,
        error_message=error_message,
        estimated_completion=estimated_completion,
    )


# ---------------------------------------------------------------------------
# _serialize_task_status
# ---------------------------------------------------------------------------


def test_serialize_task_status_full_attributes():
    from app.routers.transcribe.progress import _serialize_task_status

    task_id = uuid.uuid4()
    proto_id = uuid.uuid4()
    eta = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    s = _make_status(
        task_id=task_id,
        protocol_id=proto_id,
        status="running",
        progress_percent=55,
        current_chunk=3,
        message="Halfway",
    )
    # Inject estimated_completion (not on SimpleNamespace by default)
    s.estimated_completion = eta

    out = _serialize_task_status(str(task_id), s)
    assert out["id"] == str(task_id)
    assert out["task_id"] == str(task_id)
    assert out["protocol_id"] == str(proto_id)
    assert out["status"] == "running"
    assert out["progress"] == 55
    assert out["progress_percent"] == 55
    assert out["segments_count"] == 3
    assert out["peak_rss_mb"] == 512.0
    assert out["message"] == "Halfway"
    assert out["estimated_completion"] == eta.isoformat()


def test_serialize_task_status_fallback_message():
    """If both message and error_message are None, default to status-based text."""
    from app.routers.transcribe.progress import _serialize_task_status

    s = _make_status(message=None, error_message=None)
    s.estimated_completion = None
    out = _serialize_task_status("tid", s)
    assert "Транскрипция:" in out["message"]
    assert out["status"] == s.status


def test_serialize_task_status_uses_error_message_when_message_is_none():
    from app.routers.transcribe.progress import _serialize_task_status

    s = _make_status(message=None, error_message="boom")
    s.estimated_completion = None
    out = _serialize_task_status("tid", s)
    assert out["message"] == "boom"


def test_serialize_task_status_handles_missing_attributes_gracefully():
    """If status_obj is malformed, fallback dict is returned."""
    from app.routers.transcribe.progress import _serialize_task_status

    class Broken:
        id = "x"

        @property
        def protocol_id(self):
            raise RuntimeError("boom")

    out = _serialize_task_status("task-x", Broken())
    assert out["task_id"] == "task-x"
    assert out["status"] == "unknown"
    assert out["progress"] == 0
    assert out["message"] == "Ошибка сериализации"


# ---------------------------------------------------------------------------
# get_transcription_progress endpoint (in-memory + DB branches)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_progress_in_memory_hit_returns_serialized_status():
    """When transcription_service has an in-memory status, _serialize is used."""
    from app.routers.transcribe import progress as progress_mod

    task_id = uuid.uuid4()
    proto_id = uuid.uuid4()
    status = _make_status(
        task_id=task_id,
        protocol_id=proto_id,
        status="running",
        progress_percent=33,
    )
    status.estimated_completion = None

    with patch.object(
        progress_mod.transcription_service,
        "get_status",
        return_value=status,
    ):
        result = await progress_mod.get_transcription_progress(
            str(task_id), db=AsyncMock()
        )

    assert result["task_id"] == str(task_id)
    assert result["status"] == "running"
    assert result["progress"] == 33
    assert result["protocol_id"] == str(proto_id)


@pytest.mark.asyncio
async def test_get_progress_in_memory_serialize_failure_falls_back_to_db():
    """If _serialize_task_status raises, endpoint still continues to DB branch."""
    from app.routers.transcribe import progress as progress_mod
    from app.db.models import TranscriptionTask, Utterance

    task_id = uuid.uuid4()
    proto_id = uuid.uuid4()

    # Build a mock TranscriptionTask returned by db.get()
    db_task = MagicMock()
    db_task.id = task_id
    db_task.protocol_id = proto_id
    db_task.status = "completed"
    db_task.progress = 1.0
    db_task.error_message = None
    db_task.current_step = "Done"

    db = AsyncMock()
    db.get = AsyncMock(return_value=db_task)

    # Count result mock
    count_res = MagicMock()
    count_res.scalar.return_value = 4

    def execute_side_effect(stmt):
        return count_res

    db.execute.side_effect = execute_side_effect

    # Make serialize_task_status blow up
    with patch.object(
        progress_mod.transcription_service,
        "get_status",
        return_value=_make_status(),
    ), patch.object(
        progress_mod, "_serialize_task_status", side_effect=RuntimeError("boom")
    ):
        result = await progress_mod.get_transcription_progress(str(task_id), db=db)

    assert result["status"] == "completed"
    assert result["segments_count"] == 4


@pytest.mark.asyncio
async def test_get_progress_get_status_raises_returns_none_then_db_fallback():
    """Exception in transcription_service.get_status → DB fallback path."""
    from app.routers.transcribe import progress as progress_mod
    from app.db.models import TranscriptionTask, Utterance

    task_id = uuid.uuid4()
    proto_id = uuid.uuid4()

    db_task = MagicMock()
    db_task.id = task_id
    db_task.protocol_id = proto_id
    db_task.status = "running"
    db_task.progress = 0.5
    db_task.error_message = None
    db_task.current_step = "Step X"

    db = AsyncMock()
    db.get = AsyncMock(return_value=db_task)

    count_res = MagicMock()
    count_res.scalar.return_value = 0

    def exec_side(stmt):
        return count_res

    db.execute.side_effect = exec_side

    with patch.object(
        progress_mod.transcription_service,
        "get_status",
        side_effect=RuntimeError("kaboom"),
    ):
        result = await progress_mod.get_transcription_progress(str(task_id), db=db)

    assert result["task_id"] == str(task_id)
    assert result["status"] == "running"
    assert result["message"] == "Step X"


@pytest.mark.asyncio
async def test_get_progress_db_exception_returns_unknown():
    """If db.get raises, endpoint returns the 'unknown' fallback dict."""
    from app.routers.transcribe import progress as progress_mod

    db = AsyncMock()
    db.get = AsyncMock(side_effect=RuntimeError("db-down"))

    with patch.object(
        progress_mod.transcription_service,
        "get_status",
        return_value=None,
    ):
        result = await progress_mod.get_transcription_progress("nonexistent", db=db)

    assert result["task_id"] == "nonexistent"
    assert result["status"] == "unknown"
    assert result["progress"] == 0
    assert "не найдена" in result["message"]


@pytest.mark.asyncio
async def test_get_progress_unknown_task_returns_unknown_payload():
    """No in-memory, no DB row → unknown payload."""
    from app.routers.transcribe import progress as progress_mod

    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    with patch.object(
        progress_mod.transcription_service,
        "get_status",
        return_value=None,
    ):
        result = await progress_mod.get_transcription_progress("ghost", db=db)

    assert result["status"] == "unknown"
    assert result["task_id"] == "ghost"
    assert result["progress"] == 0


# ---------------------------------------------------------------------------
# _get_progress_internal — protocol not found / no active task / pending cancels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_progress_internal_protocol_not_found():
    from app.routers.transcribe.progress import _get_progress_internal
    from app.db.models import Protocol

    db = AsyncMock()
    proto_result = MagicMock()
    proto_result.scalar_one_or_none.return_value = None
    db.execute.return_value = proto_result

    proto_id = uuid.uuid4()
    result = await _get_progress_internal(proto_id, db)

    assert result["status"] == "unknown"
    assert result["protocol_id"] == str(proto_id)
    assert "не найден" in result["message"]


@pytest.mark.asyncio
async def test_get_progress_internal_no_active_task_falls_back_to_idle():
    """Protocol exists, no active task → status from protocol (idle fallback)."""
    from app.routers.transcribe.progress import _get_progress_internal

    proto_id = uuid.uuid4()
    proto = MagicMock()
    proto.status = "loaded"

    proto_res = MagicMock()
    proto_res.scalar_one_or_none.side_effect = [proto, None]
    db = AsyncMock()
    db.execute.return_value = proto_res

    result = await _get_progress_internal(proto_id, db)

    assert result["status"] == "loaded"
    assert result["progress"] == 0
    assert "loaded" in result["message"]


@pytest.mark.asyncio
async def test_get_progress_internal_stuck_protocol_reset():
    """Protocol with status='transcribing' and no active task gets reset to 'loaded'."""
    from app.routers.transcribe.progress import _get_progress_internal

    proto_id = uuid.uuid4()
    proto = MagicMock()
    proto.status = "transcribing"

    proto_res = MagicMock()
    proto_res.scalar_one_or_none.side_effect = [proto, None]
    db = AsyncMock()
    db.execute.return_value = proto_res
    db.commit = AsyncMock()

    result = await _get_progress_internal(proto_id, db)

    assert proto.status == "loaded"
    assert db.commit.await_count >= 1
    assert "прервана" in result["message"]


@pytest.mark.asyncio
async def test_get_progress_internal_stuck_protocol_reset_fails_continues():
    """If commit on stuck-protocol reset fails, no exception propagates."""
    from app.routers.transcribe.progress import _get_progress_internal

    proto_id = uuid.uuid4()
    proto = MagicMock()
    proto.status = "transcribing"

    proto_res = MagicMock()
    proto_res.scalar_one_or_none.side_effect = [proto, None]
    db = AsyncMock()
    db.execute.return_value = proto_res
    db.commit = AsyncMock(side_effect=RuntimeError("commit-fail"))
    db.rollback = AsyncMock()

    result = await _get_progress_internal(proto_id, db)

    assert result is not None
    assert db.rollback.await_count >= 1


@pytest.mark.asyncio
async def test_get_progress_internal_with_active_task_alive():
    """Active task that is in registry → returned with task_id and progress."""
    from app.routers.transcribe.progress import _get_progress_internal
    from app.services.active_tasks import _active_transcription_tasks
    import asyncio

    proto_id = uuid.uuid4()
    task_id = uuid.uuid4()
    proto = MagicMock()
    proto.status = "transcribing"

    task = MagicMock()
    task.id = task_id
    task.status = "running"
    task.progress = 0.5
    task.error_message = None
    task.current_step = "Working..."
    task.current_chunk = 12
    task.started_at = datetime.now(timezone.utc)

    proto_res = MagicMock()
    proto_res.scalar_one_or_none.side_effect = [proto, task]
    db = AsyncMock()
    db.execute.return_value = proto_res
    db.commit = AsyncMock()

    # Register a live task so is_task_alive returns True
    async def _noop():
        await asyncio.sleep(0)
        return None

    bg = asyncio.create_task(_noop())
    _active_transcription_tasks[str(task_id)] = bg
    try:
        result = await _get_progress_internal(proto_id, db)
    finally:
        _active_transcription_tasks.pop(str(task_id), None)
        bg.cancel()

    assert result["task_id"] == str(task_id)
    assert result["status"] == "running"
    assert result["progress"] == 0.5
    assert result["segments_count"] == 12


@pytest.mark.asyncio
async def test_get_progress_internal_pending_cancel_applied_to_queued_task():
    """Pending DB cancel is applied when DB row exists with status in queued/running/starting."""
    from app.routers.transcribe import progress as progress_mod
    from app.services import transcription_progress as tp

    proto_id = uuid.uuid4()
    task_id = uuid.uuid4()

    db_task = MagicMock()
    db_task.status = "queued"
    db_task.error_message = None
    db_task.finished_at = None

    db = AsyncMock()
    db.get = AsyncMock(return_value=db_task)
    db.commit = AsyncMock()

    tp._pending_db_cancels.add(str(task_id))

    # Protocol branch: nothing found, so we go to the "no active task" branch
    proto = MagicMock()
    proto.status = "loaded"

    proto_res = MagicMock()
    proto_res.scalar_one_or_none.side_effect = [proto, None]

    # The first execute() in pending-cancel loop is the inner one; override
    def exec_side(stmt):
        return proto_res

    db.execute.side_effect = exec_side

    result = await progress_mod._get_progress_internal(proto_id, db)

    assert db_task.status == "cancelled"
    assert db_task.error_message == "Отменено пользователем"
    assert db_task.finished_at is not None
    # Pending set is drained
    assert str(task_id) not in tp._pending_db_cancels


@pytest.mark.asyncio
async def test_get_progress_internal_pending_cancel_invalid_uuid_logged():
    """Invalid UUID in pending cancels is logged and skipped (not raised)."""
    from app.routers.transcribe import progress as progress_mod
    from app.services import transcription_progress as tp

    proto_id = uuid.uuid4()
    tp._pending_db_cancels.add("not-a-uuid")

    proto = MagicMock()
    proto.status = "loaded"
    proto_res = MagicMock()
    proto_res.scalar_one_or_none.side_effect = [proto, None]
    db = AsyncMock()
    db.execute.return_value = proto_res

    result = await progress_mod._get_progress_internal(proto_id, db)
    assert result["status"] == "loaded"


# ---------------------------------------------------------------------------
# HTTP endpoint smoke + 404/422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_progress_unknown_task_returns_unknown(client):
    r = await client.get(f"{API_PREFIX}/transcribe/progress/ghost-id-xyz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "unknown"


@pytest.mark.asyncio
async def test_http_progress_invalid_uuid_for_protocol_returns_422(client):
    r = await client.get(f"{API_PREFIX}/transcribe/progress-by-protocol/not-a-uuid")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_http_progress_by_protocol_returns_unknown_for_missing(client):
    r = await client.get(
        f"{API_PREFIX}/transcribe/progress-by-protocol/{uuid.uuid4()}"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "unknown"
    assert "не найден" in body["message"]