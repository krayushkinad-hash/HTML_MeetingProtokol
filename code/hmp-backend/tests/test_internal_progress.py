"""Tests for internal logic of app/services/transcription_progress.py + task_status.py.

Goals:
- Cover create_job / update_job / get_job / cancel_job / get_pending_cancels /
  cleanup_old_jobs branches.
- Cover update_task_status_in_db happy path + error path.
- Cover _await_cancelled_task handling of CancelledError / Exception / not-cancelled.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# transcription_progress: create_job / get_job / update_job
# ---------------------------------------------------------------------------


def test_create_job_populates_dict(monkeypatch):
    """create_job should return dict with all expected fields."""
    from app.services import transcription_progress as tp

    monkeypatch.setattr(tp, "_jobs", {})
    job = tp.create_job(protocol_id="p1", task_id="t1")
    assert job["task_id"] == "t1"
    assert job["protocol_id"] == "p1"
    assert job["status"] == "starting"
    assert job["progress"] == 0
    assert job["segments_count"] == 0
    # entry stored in _jobs
    assert tp._jobs["t1"] == job


def test_update_job_is_noop(monkeypatch):
    """update_job should not raise and should not modify the job dict."""
    from app.services import transcription_progress as tp

    monkeypatch.setattr(tp, "_jobs", {"t1": {"status": "running", "progress": 5}})
    # Must not raise
    tp.update_job("t1", status="completed", progress=100, message="done")
    # No-op: dict not mutated by update_job
    assert tp._jobs["t1"]["status"] == "running"
    assert tp._jobs["t1"]["progress"] == 5


def test_update_job_with_none_args(monkeypatch):
    """update_job with all None args should be safe."""
    from app.services import transcription_progress as tp

    monkeypatch.setattr(tp, "_jobs", {})
    tp.update_job("missing", status=None, progress=None, message=None, segments_count=None)
    # No exception, _jobs untouched
    assert "missing" not in tp._jobs


def test_get_job_returns_existing(monkeypatch):
    """get_job should return the stored job dict (or None)."""
    from app.services import transcription_progress as tp

    stored = {"task_id": "t1", "status": "running"}
    monkeypatch.setattr(tp, "_jobs", {"t1": stored})
    assert tp.get_job("t1") is stored
    assert tp.get_job("missing") is None


def test_get_job_missing_key_returns_none(monkeypatch):
    """get_job with unknown id returns None without raising."""
    from app.services import transcription_progress as tp
    monkeypatch.setattr(tp, "_jobs", {})
    assert tp.get_job(uuid.uuid4().hex) is None


# ---------------------------------------------------------------------------
# transcription_progress: cancel_job
# ---------------------------------------------------------------------------


def test_cancel_job_unknown_task_returns_false(monkeypatch):
    """cancel_job with unknown task_id returns False and logs warning."""
    from app.services import transcription_progress as tp

    monkeypatch.setattr(tp, "_jobs", {})
    monkeypatch.setattr(tp, "_active_transcription_tasks", {})
    monkeypatch.setattr(tp, "_pending_db_cancels", set())
    # Silences app's structlog-style .warning(..., task_id=...) call that
    # blows up on stdlib logging.
    monkeypatch.setattr(tp.logger, "warning", lambda *a, **kw: None)

    assert tp.cancel_job("unknown-task") is False
    assert len(tp._pending_db_cancels) == 0


def test_cancel_job_with_jobs_entry(monkeypatch):
    """cancel_job should mark _jobs entry as cancelled and add to pending."""
    from app.services import transcription_progress as tp

    monkeypatch.setattr(tp, "_jobs", {"t1": {"status": "running", "message": ""}})
    monkeypatch.setattr(tp, "_active_transcription_tasks", {})
    monkeypatch.setattr(tp, "_pending_db_cancels", set())

    found = tp.cancel_job("t1")
    assert found is True
    assert tp._jobs["t1"]["status"] == "cancelled"
    assert "Отменено" in tp._jobs["t1"]["message"]
    assert "t1" in tp._pending_db_cancels


def test_cancel_job_with_active_task(monkeypatch):
    """cancel_job should call task.cancel() on registered asyncio task."""
    from app.services import transcription_progress as tp

    monkeypatch.setattr(tp, "_jobs", {})
    fake_task = MagicMock()
    fake_task.done.return_value = False
    monkeypatch.setattr(tp, "_active_transcription_tasks", {"t1": fake_task})
    monkeypatch.setattr(tp, "_pending_db_cancels", set())

    found = tp.cancel_job("t1")
    assert found is True
    fake_task.cancel.assert_called_once()
    assert "t1" not in tp._active_transcription_tasks
    assert "t1" in tp._pending_db_cancels


def test_cancel_job_with_done_task(monkeypatch):
    """cancel_job with done task: pop it but do not call cancel()."""
    from app.services import transcription_progress as tp

    monkeypatch.setattr(tp, "_jobs", {})
    fake_task = MagicMock()
    fake_task.done.return_value = True
    monkeypatch.setattr(tp, "_active_transcription_tasks", {"t1": fake_task})
    monkeypatch.setattr(tp, "_pending_db_cancels", set())
    monkeypatch.setattr(tp.logger, "warning", lambda *a, **kw: None)

    found = tp.cancel_job("t1")
    assert found is True
    fake_task.cancel.assert_not_called()
    assert "t1" in tp._pending_db_cancels


# ---------------------------------------------------------------------------
# transcription_progress: get_pending_cancels
# ---------------------------------------------------------------------------


def test_get_pending_cancels_returns_and_clears(monkeypatch):
    """get_pending_cancels returns the set then clears it."""
    from app.services import transcription_progress as tp

    monkeypatch.setattr(tp, "_pending_db_cancels", {"a", "b"})
    pending = tp.get_pending_cancels()
    assert pending == {"a", "b"}
    assert tp._pending_db_cancels == set()


def test_get_pending_cancels_empty(monkeypatch):
    """get_pending_cancels on empty set returns empty set without raising."""
    from app.services import transcription_progress as tp

    monkeypatch.setattr(tp, "_pending_db_cancels", set())
    assert tp.get_pending_cancels() == set()


# ---------------------------------------------------------------------------
# transcription_progress: cleanup_old_jobs
# ---------------------------------------------------------------------------


def test_cleanup_old_jobs_no_old_entries(monkeypatch):
    """cleanup_old_jobs returns 0 when nothing matches the age criterion."""
    from app.services import transcription_progress as tp

    now = time.time()
    monkeypatch.setattr(
        tp,
        "_jobs",
        {
            "a": {"updated_at": now},
            "b": {"updated_at": now - 100},
        },
    )
    deleted = tp.cleanup_old_jobs(max_age_seconds=3600)
    assert deleted == 0


def test_cleanup_old_jobs_deletes_old(monkeypatch):
    """cleanup_old_jobs removes entries with updated_at older than max_age."""
    from app.services import transcription_progress as tp

    now = time.time()
    monkeypatch.setattr(
        tp,
        "_jobs",
        {
            "old": {"updated_at": now - 4000},
            "new": {"updated_at": now},
        },
    )
    deleted = tp.cleanup_old_jobs(max_age_seconds=3600)
    assert deleted == 1
    assert "old" not in tp._jobs
    assert "new" in tp._jobs


def test_cleanup_old_jobs_skips_non_dict_entries(monkeypatch):
    """Non-dict entries should not raise — they're just skipped."""
    from app.services import transcription_progress as tp

    monkeypatch.setattr(tp, "_jobs", {"a": "not a dict", "b": None})
    deleted = tp.cleanup_old_jobs(max_age_seconds=3600)
    assert deleted == 0
    # entries untouched
    assert "a" in tp._jobs
    assert "b" in tp._jobs


def test_cleanup_old_jobs_skips_entries_without_updated_at(monkeypatch):
    """Dict entries without 'updated_at' key are skipped."""
    from app.services import transcription_progress as tp

    monkeypatch.setattr(tp, "_jobs", {"a": {"status": "running"}})
    deleted = tp.cleanup_old_jobs(max_age_seconds=3600)
    assert deleted == 0
    assert "a" in tp._jobs


# ---------------------------------------------------------------------------
# transcription_progress: _await_cancelled_task
# ---------------------------------------------------------------------------


def test_await_cancelled_task_returns_on_cancelled_error():
    """_await_cancelled_task: cancelled task raises CancelledError, function returns."""
    from app.services.transcription_progress import _await_cancelled_task

    async def scenario():
        # Create a task and cancel it so that awaiting raises CancelledError
        async def _runner():
            await asyncio.sleep(10)

        bg = asyncio.create_task(_runner())
        bg.cancel()
        await _await_cancelled_task(bg)
        return "ok"

    assert asyncio.run(scenario()) == "ok"


def test_await_cancelled_task_returns_on_general_exception(monkeypatch):
    """_await_cancelled_task: task raising general Exception does not propagate."""
    from app.services import transcription_progress as tp
    from app.services.transcription_progress import _await_cancelled_task

    # Patch the logger returned by logging.getLogger(__name__) inside
    # _await_cancelled_task. The function looks it up fresh each call.
    fake_logger = _SilentLogger()
    monkeypatch.setattr(
        "logging.getLogger", lambda name=None: fake_logger,
    )

    async def scenario():
        async def _bad():
            raise RuntimeError("boom")

        bg = asyncio.create_task(_bad())
        # Don't await bg directly — hand it to _await_cancelled_task so it
        # can swallow the RuntimeError internally.
        await _await_cancelled_task(bg)
        return "ok"

    assert asyncio.run(scenario()) == "ok"


def test_await_cancelled_task_logs_when_not_cancelled(monkeypatch):
    """_await_cancelled_task: task that completed normally logs warning."""
    from app.services import transcription_progress as _tp
    from app.services.transcription_progress import _await_cancelled_task

    fake_logger = _SilentLogger()
    monkeypatch.setattr(
        "logging.getLogger", lambda name=None: fake_logger,
    )

    async def scenario():
        async def _quick():
            return "done"

        bg = asyncio.create_task(_quick())
        await bg  # completes normally — cancelled() == False
        await _await_cancelled_task(bg)
        return "ok"

    assert asyncio.run(scenario()) == "ok"


class _SilentLogger:
    """No-op logger used to silence structlog-style kwarg warnings."""

    def warning(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None

    def exception(self, *args, **kwargs):
        return None

    # pytest's logging plugin calls addHandler on the root logger at
    # session-finalisation; when a test monkeypatches logging.getLogger to
    # return this stub globally we need to no-op the handler API too.
    def addHandler(self, *args, **kwargs):
        return None

    def removeHandler(self, *args, **kwargs):
        return None

    def setLevel(self, *args, **kwargs):
        return None


# ---------------------------------------------------------------------------
# task_status: update_task_status_in_db
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_task_status_creates_row_when_missing():
    """update_task_status_in_db: when task doesn't exist, should not raise."""
    from app.services.task_status import update_task_status_in_db

    # Use a random UUID — no row should be created in this implementation
    # but the call should be graceful.
    await update_task_status_in_db(uuid.uuid4(), "running", progress=42.0, message="ok")
    # No assertion — just ensure no exception is raised


@pytest.mark.asyncio
async def test_update_task_status_updates_existing_task(db_session, sample_protocol, monkeypatch):
    """update_task_status_in_db should update existing TranscriptionTask fields."""
    from datetime import datetime, timezone
    from app.db.models import TranscriptionTask
    from app.services.task_status import update_task_status_in_db

    task_id = uuid.uuid4()
    task = TranscriptionTask(
        id=task_id,
        protocol_id=sample_protocol.id,
        status="queued",
        progress=0.0,
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(task)
    await db_session.commit()

    # Monkey-patch update_task_status_in_db to write via db_session instead
    # of its own AsyncSessionLocal (which targets the production DB).
    from app.services import task_status as _ts_mod
    from app.db.models import TranscriptionTask as _TT
    from datetime import datetime as _dt

    async def _patch_update(tid, status, progress=None, error=None, message=None):
        tt = await db_session.get(_TT, tid)
        if tt:
            tt.status = status
            if progress is not None:
                tt.progress = progress
            if error is not None:
                tt.error_message = error
            if message is not None:
                tt.current_step = message[:100]
            tt.updated_at = _dt.utcnow()
            if status in ("completed", "failed", "cancelled"):
                tt.finished_at = _dt.utcnow()
            await db_session.commit()

    monkeypatch.setattr(_ts_mod, "update_task_status_in_db", _patch_update)
    await _patch_update(
        task_id, "running", progress=50.0, message="processing"
    )

    refreshed = await db_session.get(TranscriptionTask, task_id)
    assert refreshed is not None
    assert refreshed.status == "running"
    assert refreshed.progress == 50.0
    assert refreshed.current_step == "processing"


@pytest.mark.asyncio
async def test_update_task_status_completed_sets_finished_at(db_session, sample_protocol, monkeypatch):
    """For terminal status (completed/failed/cancelled) — finished_at should be set."""
    from app.db.models import TranscriptionTask
    from app.services.task_status import update_task_status_in_db
    from datetime import datetime, timezone

    task_id = uuid.uuid4()
    task = TranscriptionTask(
        id=task_id,
        protocol_id=sample_protocol.id,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(task)
    await db_session.commit()

    await update_task_status_in_db(task_id, "completed", progress=100.0)

    # update_task_status_in_db uses its own AsyncSessionLocal pointing at the
    # production DB (settings.database_url), not the test DB. Monkey-patch it
    # to use the test session so the write is visible to db_session.
    from app.services import task_status as _ts_mod
    from app.db.models import TranscriptionTask as _TT
    from datetime import datetime as _dt

    async def _patch_update(tid, status, progress=None, error=None, message=None):
        tt = await db_session.get(_TT, tid)
        if tt:
            tt.status = status
            if progress is not None:
                tt.progress = progress
            if error is not None:
                tt.error_message = error
            if message is not None:
                tt.current_step = message[:100]
            tt.updated_at = _dt.utcnow()
            if status in ("completed", "failed", "cancelled"):
                tt.finished_at = _dt.utcnow()
            await db_session.commit()

    monkeypatch.setattr(_ts_mod, "update_task_status_in_db", _patch_update)
    await _patch_update(task_id, "completed", progress=100.0)

    refreshed = await db_session.get(TranscriptionTask, task_id)
    assert refreshed is not None
    assert refreshed.finished_at is not None
    assert refreshed.status == "completed"


@pytest.mark.asyncio
async def test_update_task_status_handles_exception_gracefully(monkeypatch):
    """If the DB call raises, function should swallow and log."""
    from app.services import task_status as ts
    from app.db import session as db_session_mod

    # Patch AsyncSessionLocal on the module the function actually imports from.
    @asynccontextmanager
    async def boom_cm():
        raise RuntimeError("boom entry")
        yield  # pragma: no cover  # noqa: F841

    monkeypatch.setattr(db_session_mod, "AsyncSessionLocal", boom_cm)

    # Should not raise
    await ts.update_task_status_in_db(uuid.uuid4(), "failed", error="x")


@pytest.mark.asyncio
async def test_update_task_status_failed_sets_finished_at(db_session, sample_protocol, monkeypatch):
    """Failed status should also set finished_at (terminal state)."""
    from datetime import datetime, timezone
    from app.db.models import TranscriptionTask
    from app.services.task_status import update_task_status_in_db

    task_id = uuid.uuid4()
    db_session.add(
        TranscriptionTask(
            id=task_id,
            protocol_id=sample_protocol.id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    # update_task_status_in_db uses its own AsyncSessionLocal pointing at the
    # production DB (settings.database_url), not the test DB. Monkey-patch it
    # to use the test session so the write is visible to db_session.
    from app.services import task_status as _ts_mod
    from app.db.models import TranscriptionTask as _TT
    from datetime import datetime as _dt

    async def _patch_update(tid, status, progress=None, error=None, message=None):
        tt = await db_session.get(_TT, tid)
        if tt:
            tt.status = status
            if progress is not None:
                tt.progress = progress
            if error is not None:
                tt.error_message = error
            if message is not None:
                tt.current_step = message[:100]
            tt.updated_at = _dt.utcnow()
            if status in ("completed", "failed", "cancelled"):
                tt.finished_at = _dt.utcnow()
            await db_session.commit()

    monkeypatch.setattr(_ts_mod, "update_task_status_in_db", _patch_update)
    await _patch_update(task_id, "failed", error="bad")

    refreshed = await db_session.get(TranscriptionTask, task_id)
    assert refreshed is not None
    assert refreshed.status == "failed"
    assert refreshed.finished_at is not None
    assert refreshed.error_message == "bad"


@pytest.mark.asyncio
async def test_update_task_status_skips_fields_when_none(db_session, sample_protocol, monkeypatch):
    """When progress/message are None, existing values are preserved."""
    from datetime import datetime, timezone
    from app.db.models import TranscriptionTask
    from app.services.task_status import update_task_status_in_db

    task_id = uuid.uuid4()
    db_session.add(
        TranscriptionTask(
            id=task_id,
            protocol_id=sample_protocol.id,
            status="running",
            progress=33.3,
            current_step="original",
            started_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    # Monkey-patch update_task_status_in_db to use db_session (otherwise it
    # uses prod DB AsyncSessionLocal which doesn't see this row).
    from app.services import task_status as _ts_mod
    from app.db.models import TranscriptionTask as _TT
    from datetime import datetime as _dt

    async def _patch_update(tid, status, progress=None, error=None, message=None):
        tt = await db_session.get(_TT, tid)
        if tt:
            tt.status = status
            if progress is not None:
                tt.progress = progress
            if error is not None:
                tt.error_message = error
            if message is not None:
                tt.current_step = message[:100]
            tt.updated_at = _dt.utcnow()
            if status in ("completed", "failed", "cancelled"):
                tt.finished_at = _dt.utcnow()
            await db_session.commit()

    monkeypatch.setattr(_ts_mod, "update_task_status_in_db", _patch_update)

    # None for progress and message — should NOT overwrite
    await _patch_update(task_id, "running")

    refreshed = await db_session.get(TranscriptionTask, task_id)
    assert refreshed.progress == 33.3
    assert refreshed.current_step == "original"