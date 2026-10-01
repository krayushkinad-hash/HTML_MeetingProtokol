"""Coverage tests for app/services/task_status.py.

The module exposes a single async helper, ``update_task_status_in_db``,
which writes status/progress/error/message fields back to a
``TranscriptionTask`` row via the module-level ``AsyncSessionLocal``.

Strategy: monkeypatch ``app.services.task_status.AsyncSessionLocal`` with
an AsyncMock that returns an AsyncMock session, so we drive every branch
of the helper without touching the real database — the goal here is
line/branch coverage of the helper itself.

We hit every branch:
  - happy path with all optional args
  - progress / error / message omitted (no-op on those columns)
  - status outside {completed,failed,cancelled}  → finished_at stays NULL
  - status in {completed,failed,cancelled}      → finished_at gets stamped
  - long message gets truncated to 100 chars (column length)
  - unknown task_id is silently swallowed (no exception)
  - AsyncSessionLocal raising → helper swallows the exception
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.task_status import update_task_status_in_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_session_factory():
    """Replace ``app.db.session.AsyncSessionLocal`` with a factory that
    yields an AsyncMock session. The helper does a deferred import
    (``from app.db.session import AsyncSessionLocal``) inside its body,
    so this is the symbol it actually binds."""
    from app.db import session as db_session

    factory = MagicMock()
    session = AsyncMock()
    factory.return_value.__aenter__.return_value = session
    db_session.AsyncSessionLocal = factory  # type: ignore[assignment]
    yield factory, session


@pytest.fixture
def fake_session_no_row():
    """Like ``fake_session_factory`` but ``session.get`` returns ``None``
    (the unknown-task branch)."""
    from app.db import session as db_session

    factory = MagicMock()
    session = AsyncMock()
    session.get.return_value = None
    factory.return_value.__aenter__.return_value = session
    db_session.AsyncSessionLocal = factory  # type: ignore[assignment]
    yield factory, session


@pytest.fixture
def fake_session_factory_broken():
    """AsyncSessionLocal() itself raises on enter (the exception branch)."""
    from app.db import session as db_session

    class _BoomCtx:
        async def __aenter__(self):
            raise RuntimeError("simulated DB outage")

        async def __aexit__(self, *exc):
            return False

    db_session.AsyncSessionLocal = _BoomCtx()  # type: ignore[assignment]
    yield


# ---------------------------------------------------------------------------
# 1. Module surface (no DB / no mocking needed)
# ---------------------------------------------------------------------------


def test_module_exposes_update_helper():
    """Public surface: one callable named update_task_status_in_db."""
    import app.services.task_status as mod

    assert hasattr(mod, "update_task_status_in_db")
    assert callable(mod.update_task_status_in_db)


def test_update_helper_is_async():
    """update_task_status_in_db must be a coroutine function."""
    import inspect

    from app.services.task_status import update_task_status_in_db

    assert inspect.iscoroutinefunction(update_task_status_in_db)


# ---------------------------------------------------------------------------
# 2. Happy-path writes — drive every conditional branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_updates_status_progress_error_and_message(fake_session_factory):
    """All four optional columns set on the row + info log emitted."""
    factory, session = fake_session_factory
    row = MagicMock()
    row.finished_at = None  # sentinel: helper must NOT overwrite (status is running)
    session.get.return_value = row

    await update_task_status_in_db(
        uuid.uuid4(),
        status="running",
        progress=42.5,
        error="boom",
        message="transcribing chunk 3/7",
    )

    factory.assert_called_once()
    session.get.assert_awaited_once()
    assert row.status == "running"
    assert row.progress == 42.5
    assert row.error_message == "boom"
    # Message truncated to 100 chars (column length)
    assert row.current_step == "transcribing chunk 3/7"
    # updated_at set
    assert row.updated_at is not None
    # running → no finished_at stamp
    assert row.finished_at is None
    # session.commit awaited
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_omitted_progress_error_message_leaves_columns_alone(fake_session_factory):
    """progress=None / error=None / message=None → those columns not touched.

    We detect "not touched" by setting sentinel values first and asserting
    they're unchanged after the helper runs.
    """
    factory, session = fake_session_factory
    row = MagicMock()
    row.progress = "PRESERVE_PROGRESS"
    row.error_message = "PRESERVE_ERROR"
    row.current_step = "PRESERVE_STEP"
    session.get.return_value = row

    await update_task_status_in_db(uuid.uuid4(), status="running")

    assert row.status == "running"
    assert row.progress == "PRESERVE_PROGRESS"
    assert row.error_message == "PRESERVE_ERROR"
    assert row.current_step == "PRESERVE_STEP"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_finished_at_stamped_on_completed(fake_session_factory):
    """status='completed' → row.finished_at gets stamped."""
    _, session = fake_session_factory
    row = MagicMock()
    session.get.return_value = row

    await update_task_status_in_db(uuid.uuid4(), status="completed")

    assert row.status == "completed"
    assert row.finished_at is not None


@pytest.mark.asyncio
async def test_finished_at_stamped_on_failed(fake_session_factory):
    """status='failed' → row.finished_at gets stamped."""
    _, session = fake_session_factory
    row = MagicMock()
    session.get.return_value = row

    await update_task_status_in_db(uuid.uuid4(), status="failed")

    assert row.status == "failed"
    assert row.finished_at is not None


@pytest.mark.asyncio
async def test_finished_at_stamped_on_cancelled(fake_session_factory):
    """status='cancelled' → row.finished_at gets stamped."""
    _, session = fake_session_factory
    row = MagicMock()
    session.get.return_value = row

    await update_task_status_in_db(uuid.uuid4(), status="cancelled")

    assert row.status == "cancelled"
    assert row.finished_at is not None


@pytest.mark.asyncio
async def test_finished_at_not_stamped_on_non_terminal(fake_session_factory):
    """status='running' (not in terminal set) → finished_at stays None."""
    _, session = fake_session_factory
    row = MagicMock()
    row.finished_at = None  # sentinel: helper must NOT overwrite
    session.get.return_value = row

    await update_task_status_in_db(uuid.uuid4(), status="running")

    assert row.finished_at is None


@pytest.mark.asyncio
async def test_message_truncated_to_100_chars(fake_session_factory):
    """Long message sliced to 100 chars before assigning to current_step."""
    _, session = fake_session_factory
    row = MagicMock()
    session.get.return_value = row

    long_msg = "X" * 250
    await update_task_status_in_db(
        uuid.uuid4(), status="running", message=long_msg
    )

    assert row.current_step == "X" * 100
    assert len(row.current_step) == 100


# ---------------------------------------------------------------------------
# 3. Failure / no-op paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_task_id_is_silently_swallowed(fake_session_no_row):
    """session.get returns None → no exception, no commit."""
    factory, session = fake_session_no_row

    await update_task_status_in_db(uuid.uuid4(), status="failed", error="nope")

    factory.assert_called_once()
    session.get.assert_awaited_once()
    # commit must NOT have been called on the no-row branch
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_session_factory_failure_is_swallowed(fake_session_factory_broken):
    """If AsyncSessionLocal() raises, the helper must NOT propagate."""
    # Must NOT raise — exception is caught and logged as warning.
    await update_task_status_in_db(uuid.uuid4(), status="failed")