"""Round-2 coverage tests for app/routers/transcribe/progress.py.

Goal: push from 79% → 90%+ by hitting DB-fallback branches, sticky-task
logic, and additional 404/edge paths that round-1 left uncovered.
"""
from __future__ import annotations

import asyncio
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
def _reset_state():
    from app.services import transcription_progress as tp
    from app.services.active_tasks import _active_transcription_tasks

    tp._pending_db_cancels.clear()
    _active_transcription_tasks.clear()
    yield
    tp._pending_db_cancels.clear()
    _active_transcription_tasks.clear()


def _status_obj(
    *,
    status: str = "running",
    progress_percent: int = 50,
    message: str | None = "msg",
    error_message: str | None = None,
    task_id: uuid.UUID | None = None,
    protocol_id: uuid.UUID | None = None,
):
    obj = SimpleNamespace(
        id=task_id or uuid.uuid4(),
        protocol_id=protocol_id or uuid.uuid4(),
        status=status,
        progress_percent=progress_percent,
        current_chunk=5,
        peak_rss_mb=256.0,
        message=message,
        error_message=error_message,
        estimated_completion=None,
    )
    return obj


# ---------------------------------------------------------------------------
# GET /transcribe/progress/{task_id} — DB fallback paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_progress_db_fallback_with_utterance_count(db_session):
    """DB-fallback branch counts real utterances tied to the task's protocol.

    Calls the handler directly with the conftest's ``db_session`` to avoid
    (a) spawning a second engine that TRUNCATEs in parallel, and
    (b) the ASGITransport + Depends(get_db) coverage-tracking anomaly.
    """
    from app.db.models import (
        Protocol,
        ProtocolStatus,
        Speaker,
        TranscriptionTask,
        Utterance,
    )
    from app.routers.transcribe import progress as progress_mod

    pid = uuid.uuid4()
    tid = uuid.uuid4()
    spk = uuid.uuid4()
    p = Protocol(
        id=pid,
        title="t1",
        status=ProtocolStatus.LOADED,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    t = TranscriptionTask(
        id=tid,
        protocol_id=pid,
        status="completed",
        progress=1.0,
        current_step="Done",
        error_message=None,
    )
    s = Speaker(id=spk, protocol_id=pid, speaker_label="S1")
    u1 = Utterance(
        id=uuid.uuid4(),
        protocol_id=pid,
        speaker_id=spk,
        start_sec=0.0,
        end_sec=1.0,
        text="a",
    )
    u2 = Utterance(
        id=uuid.uuid4(),
        protocol_id=pid,
        speaker_id=spk,
        start_sec=1.0,
        end_sec=2.0,
        text="b",
    )
    db_session.add_all([p, t, u1, u2, s])
    await db_session.commit()

    # Force in-memory miss → DB fallback
    with patch.object(progress_mod.transcription_service, "get_status", return_value=None):
        result = await progress_mod.get_transcription_progress(str(tid), db=db_session)

    assert result["status"] == "completed"
    assert result["progress"] == 1.0
    assert result["segments_count"] == 2
    assert result["message"] == "Done"
    assert result["id"] == str(tid)
    assert result["protocol_id"] == str(pid)


@pytest.mark.asyncio
async def test_http_progress_db_fallback_uses_error_message(db_engine, db_session):
    """DB-fallback prefers error_message over current_step when both present.

    Uses a separate ``direct_db`` session bound to the SAME ``db_engine``
    to avoid the duplicate-TRUNCATE deadlock the conftest exhibits when
    the test fixture's connection is still open while another session
    opens against the same engine.
    """
    from app.db.models import Protocol, ProtocolStatus, TranscriptionTask
    from app.routers.transcribe import progress as progress_mod

    pid = uuid.uuid4()
    tid = uuid.uuid4()
    p = Protocol(
        id=pid,
        title="t2",
        status=ProtocolStatus.LOADED,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    t = TranscriptionTask(
        id=tid,
        protocol_id=pid,
        status="failed",
        progress=0.3,
        current_step="Should be ignored",
        error_message="real error",
    )
    db_session.add_all([p, t])
    await db_session.commit()

    # Call the handler directly using the same session bound to the conftest
    # engine — this avoids spawning a second sessionmaker and TRUNCATE contention.
    with patch.object(progress_mod.transcription_service, "get_status", return_value=None):
        result = await progress_mod.get_transcription_progress(str(tid), db=db_session)

    assert result["status"] == "failed"
    assert result["message"] == "real error"
    assert result["progress"] == 0.3
    assert result["progress_percent"] == 0.3
    assert result["segments_count"] == 0


@pytest.mark.asyncio
async def test_http_progress_db_fallback_default_message():
    """DB-fallback when both error_message and current_step are None → default."""
    from app.routers.transcribe import progress as progress_mod

    task_id = uuid.uuid4()
    proto_id = uuid.uuid4()

    db_task = MagicMock()
    db_task.id = task_id
    db_task.protocol_id = proto_id
    db_task.status = "queued"
    db_task.progress = 0.0
    db_task.error_message = None
    db_task.current_step = None

    db = AsyncMock()
    db.get = AsyncMock(return_value=db_task)
    count_res = MagicMock()
    count_res.scalar.return_value = 0
    db.execute.return_value = count_res

    with patch.object(progress_mod.transcription_service, "get_status", return_value=None):
        result = await progress_mod.get_transcription_progress(str(task_id), db=db)

    assert result["message"].startswith("Транскрипция: ")
    assert result["segments_count"] == 0


# ---------------------------------------------------------------------------
# _get_progress_internal — sticky-task branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sticky_task_not_in_registry_and_old_marked_failed():
    """Task with started_at > 60s ago and NOT in registry → marked failed."""
    from app.routers.transcribe.progress import _get_progress_internal

    proto_id = uuid.uuid4()
    task_id = uuid.uuid4()

    proto = MagicMock()
    proto.status = "transcribing"

    task = MagicMock()
    task.id = task_id
    task.status = "running"
    task.progress = 0.5
    task.error_message = None
    task.current_step = None
    task.current_chunk = 1
    task.started_at = datetime.now(timezone.utc) - timedelta(seconds=120)

    res = MagicMock()
    res.scalar_one_or_none.side_effect = [proto, task]
    db = AsyncMock()
    db.execute.return_value = res
    db.commit = AsyncMock()

    result = await _get_progress_internal(proto_id, db)
    assert task.status == "failed"
    assert task.finished_at is not None
    assert "зависла" in task.error_message.lower()
    assert result["status"] == "failed"
    assert db.commit.await_count >= 1


@pytest.mark.asyncio
async def test_sticky_task_long_cpu_base_with_low_progress_marked_stale():
    """E122 branch: age > 3600s AND progress < 0.1 → stale (even if in registry)."""
    from app.routers.transcribe.progress import _get_progress_internal
    from app.services.active_tasks import _active_transcription_tasks

    proto_id = uuid.uuid4()
    task_id = uuid.uuid4()

    proto = MagicMock()
    proto.status = "transcribing"

    task = MagicMock()
    task.id = task_id
    task.status = "running"
    task.progress = 0.05  # below 0.1
    task.error_message = None
    task.current_step = None
    task.current_chunk = 0
    task.started_at = datetime.now(timezone.utc) - timedelta(seconds=7200)

    res = MagicMock()
    res.scalar_one_or_none.side_effect = [proto, task]
    db = AsyncMock()
    db.execute.return_value = res
    db.commit = AsyncMock()

    # Mark task as "alive" in registry (so the >60s branch doesn't fire)
    async def _noop():
        await asyncio.sleep(0)

    bg = asyncio.create_task(_noop())
    _active_transcription_tasks[str(task_id)] = bg
    try:
        result = await _get_progress_internal(proto_id, db)
    finally:
        _active_transcription_tasks.pop(str(task_id), None)
        bg.cancel()

    assert task.status == "failed"
    assert "зависла" in task.error_message.lower()
    assert result["status"] == "failed"


@pytest.mark.asyncio
async def test_sticky_task_alive_in_registry_young_not_marked_stale():
    """Young, alive-in-registry task returns as 'running' with progress."""
    from app.routers.transcribe.progress import _get_progress_internal
    from app.services.active_tasks import _active_transcription_tasks

    proto_id = uuid.uuid4()
    task_id = uuid.uuid4()

    proto = MagicMock()
    proto.status = "transcribing"

    task = MagicMock()
    task.id = task_id
    task.status = "running"
    task.progress = 0.42
    task.error_message = None
    task.current_step = "Chunk 3"
    task.current_chunk = 3
    task.started_at = datetime.now(timezone.utc) - timedelta(seconds=5)

    res = MagicMock()
    res.scalar_one_or_none.side_effect = [proto, task]
    db = AsyncMock()
    db.execute.return_value = res
    db.commit = AsyncMock()

    async def _noop():
        await asyncio.sleep(0)

    bg = asyncio.create_task(_noop())
    _active_transcription_tasks[str(task_id)] = bg
    try:
        result = await _get_progress_internal(proto_id, db)
    finally:
        _active_transcription_tasks.pop(str(task_id), None)
        bg.cancel()

    assert task.status == "running"  # not changed
    assert result["status"] == "running"
    assert result["progress"] == 0.42
    assert result["segments_count"] == 3
    assert result["message"] == "Chunk 3"
    assert result["started_at"] is not None
    # commit NOT called for a non-stale task
    assert db.commit.await_count == 0


@pytest.mark.asyncio
async def test_sticky_task_commit_failure_logs_and_continues():
    """If marking stale task fails on commit, we still return the payload."""
    from app.routers.transcribe.progress import _get_progress_internal

    proto_id = uuid.uuid4()
    task_id = uuid.uuid4()

    proto = MagicMock()
    proto.status = "transcribing"

    task = MagicMock()
    task.id = task_id
    task.status = "running"
    task.progress = 0.0
    task.error_message = None
    task.current_step = None
    task.current_chunk = 0
    task.started_at = datetime.now(timezone.utc) - timedelta(seconds=120)

    res = MagicMock()
    res.scalar_one_or_none.side_effect = [proto, task]
    db = AsyncMock()
    db.execute.return_value = res
    db.commit = AsyncMock(side_effect=RuntimeError("commit-broken"))
    db.rollback = AsyncMock()

    result = await _get_progress_internal(proto_id, db)

    assert db.rollback.await_count >= 1
    assert task.status == "failed"
    assert result["status"] == "failed"


@pytest.mark.asyncio
async def test_task_started_at_naive_gets_utc_attached():
    """Task with naive (tz-less) started_at is coerced to UTC before age calc."""
    from app.routers.transcribe.progress import _get_progress_internal

    proto_id = uuid.uuid4()
    task_id = uuid.uuid4()

    proto = MagicMock()
    proto.status = "transcribing"

    task = MagicMock()
    task.id = task_id
    task.status = "running"
    task.progress = 0.5
    task.error_message = None
    task.current_step = None
    task.current_chunk = 1
    # Naive datetime (no tzinfo)
    task.started_at = datetime.utcnow() - timedelta(seconds=120)

    res = MagicMock()
    res.scalar_one_or_none.side_effect = [proto, task]
    db = AsyncMock()
    db.execute.return_value = res
    db.commit = AsyncMock()

    result = await _get_progress_internal(proto_id, db)

    # Should still detect stale (not in registry + > 60s) and mark failed
    assert task.status == "failed"
    assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# _get_progress_internal — protocol & idle fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_protocol_status_idle_falls_back_to_idle_message():
    """No active task, protocol.status is None → 'idle' message."""
    from app.routers.transcribe.progress import _get_progress_internal

    proto_id = uuid.uuid4()
    proto = MagicMock()
    proto.status = None

    res = MagicMock()
    res.scalar_one_or_none.side_effect = [proto, None]
    db = AsyncMock()
    db.execute.return_value = res

    result = await _get_progress_internal(proto_id, db)
    assert result["status"] == "idle"
    assert result["progress"] == 0
    assert "idle" in result["message"]


# ---------------------------------------------------------------------------
# 404 / error branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_progress_by_protocol_endpoint_returns_error_dict_on_internal_exception():
    """Endpoint-level try/except returns error dict if _get_progress_internal raises."""
    from app.routers.transcribe import progress as progress_mod

    proto_id = uuid.uuid4()
    with patch.object(
        progress_mod,
        "_get_progress_internal",
        side_effect=RuntimeError("internal-boom"),
    ):
        result = await progress_mod.get_transcription_progress_by_protocol(proto_id, db=AsyncMock())

    assert result["status"] == "error"
    assert result["progress"] == 0
    assert "internal-boom" in result["message"]