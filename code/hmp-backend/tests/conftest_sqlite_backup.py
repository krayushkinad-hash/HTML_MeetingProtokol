"""Pytest fixtures for HTML_MeetingProtokol backend tests.

This module provides the entire test infrastructure needed to run tests
WITHOUT requiring PostgreSQL / Redis / Whisper / ffmpeg locally.

Key design decisions:
- SQLite in-memory (shared via StaticPool) for unit tests — fast, isolated.
- All external side effects (subprocess, network, Whisper) are mocked.
- PostgreSQL is ONLY touched by tests marked with @pytest.mark.integration
  (see tests/conftest_db.py) — these auto-skip if no DB is reachable.
- Models use Optional[...] without importing it — we inject it into builtins
  before importing app.db.models (pre-existing bug; do not modify app/).
"""
from __future__ import annotations

import asyncio
import builtins
import sys
import typing
from datetime import date, datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

# ---------------------------------------------------------------------------
# Pre-import shim: app/db/models.py references Optional[...] without importing
# typing.Optional. Pre-existing bug — we work around it here so tests run.
# ---------------------------------------------------------------------------
if not hasattr(builtins, "Optional"):
    builtins.Optional = typing.Optional  # type: ignore[attr-defined]

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Imports of the application — done after the shim above.
# ---------------------------------------------------------------------------
from app.db import session as _db_session_module  # noqa: E402
from app.db.models import (  # noqa: E402
    ActionItem,
    Base,
    Decision,
    Protocol,
    Speaker,
    Tag,
    Utterance,
)
from app.db.session import get_db  # noqa: E402

# ---------------------------------------------------------------------------
# pytest configuration / markers
# ---------------------------------------------------------------------------
def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers (defensive — also declared in pyproject.toml)."""
    config.addinivalue_line("markers", "e2e: end-to-end tests (slow, full stack)")
    config.addinivalue_line("markers", "slow: slow tests (>1s)")
    config.addinivalue_line("markers", "integration: requires PostgreSQL/Redis")


# ---------------------------------------------------------------------------
# Event loop (session-scoped — one loop shared by every async fixture)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def event_loop():
    """Single asyncio loop for the whole test session.

    pytest-asyncio's default creates a per-function loop, which breaks
    session-scoped async fixtures (e.g. db_engine). Keeping a session loop
    alive lets us share it across all tests.
    """
    loop = asyncio.new_event_loop()
    yield loop
    # Cancel any lingering tasks before closing
    try:
        pending = asyncio.all_tasks(loop=loop)
        for task in pending:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    except Exception:
        pass
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Database engine — SQLite in-memory, session-scoped (one engine per session)
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    """SQLite in-memory engine shared across the session.

    StaticPool keeps a single shared connection so the in-memory database
    survives across multiple AsyncSession() open/close cycles.
    """
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
        echo=False,
    )
    # Create all tables once
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Patch app.db.session so any code that imports engine / AsyncSessionLocal
    # also gets our test versions.
    original_engine = _db_session_module.engine
    original_session_local = _db_session_module.AsyncSessionLocal
    _db_session_module.engine = engine
    _db_session_module.AsyncSessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    try:
        yield engine
    finally:
        await engine.dispose()
        _db_session_module.engine = original_engine
        _db_session_module.AsyncSessionLocal = original_session_local


# ---------------------------------------------------------------------------
# Per-test DB session — wraps each test in a SAVEPOINT for full rollback
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Async session that rolls back after each test (full isolation).

    We use a SAVEPOINT instead of dropping/recreating tables so tests run fast.
    """
    async with db_engine.connect() as connection:
        transaction = await connection.begin()
        async_session_factory = async_sessionmaker(
            bind=connection,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        async with async_session_factory() as session:
            try:
                yield session
            finally:
                await transaction.rollback()


# ---------------------------------------------------------------------------
# FastAPI test client — uses ASGITransport (no real server)
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def client(db_session) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient wired to the FastAPI app via ASGI (no network).

    The app's `get_db` dependency is overridden so endpoints get our test
    session instead of trying to talk to PostgreSQL.
    """
    # Import app lazily so the Optional-shim runs first.
    from app.main import app

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        try:
            yield db_session
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        try:
            yield ac
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Explicit dependency-override fixture (some tests want to install their own)
# ---------------------------------------------------------------------------
@pytest.fixture
def override_get_db(db_session):
    """Helper to override get_db outside the `client` fixture.

    Usage:
        def test_x(client, override_get_db):
            override_get_db(my_custom_session)
            ...
    """
    from app.main import app

    def _override(session_factory):
        async def _dep():
            async with session_factory() as s:
                yield s

        app.dependency_overrides[get_db] = _dep
        return app.dependency_overrides[get_db]

    return _override


# ---------------------------------------------------------------------------
# Mock fixtures — disable real Whisper, ffmpeg, subprocess
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_whisper(monkeypatch):
    """Mock `transcription_service.transcribe` so tests don't load models.

    Returns a MagicMock so individual tests can tweak return_value / side_effect.
    """
    from app.services import transcription

    mock = AsyncMock(
        return_value=None,
        name="mock_transcribe",
    )
    monkeypatch.setattr(
        transcription.transcription_service,
        "transcribe",
        mock,
    )
    return mock


@pytest.fixture
def mock_ffmpeg(monkeypatch):
    """Mock `_sp_run` and `_sp_run_async` in video_screenshots.

    Returns a tuple (sync_mock, async_mock) so tests can configure each.
    Both default to returncode=0, empty stdout/stderr.
    """
    from app.services import video_screenshots

    default_result = (0, "", "")

    def _fake_run(cmd, timeout=30):  # noqa: ARG001
        return default_result

    async def _fake_run_async(cmd, timeout=30):  # noqa: ARG001
        return default_result

    sync_mock = MagicMock(side_effect=_fake_run, name="mock_sp_run")
    async_mock = AsyncMock(side_effect=_fake_run_async, name="mock_sp_run_async")

    monkeypatch.setattr(video_screenshots, "_sp_run", sync_mock)
    monkeypatch.setattr(video_screenshots, "_sp_run_async", async_mock)

    return sync_mock, async_mock


# ---------------------------------------------------------------------------
# Factory fixtures — create domain objects persisted in the test session
# ---------------------------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@pytest_asyncio.fixture
async def sample_protocol(db_session) -> Protocol:
    """Create a Protocol row in the test DB."""
    protocol = Protocol(
        id=uuid4(),
        title="Test Meeting",
        date=date(2026, 1, 15),
        location="Test Room",
        chair="Alice",
        agenda="Test agenda",
        duration_sec=3600,
        language="ru",
        status="loaded",
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db_session.add(protocol)
    await db_session.commit()
    await db_session.refresh(protocol)
    return protocol


@pytest_asyncio.fixture
async def sample_speaker(db_session, sample_protocol) -> Speaker:
    """Create a Speaker row tied to sample_protocol."""
    speaker = Speaker(
        id=uuid4(),
        protocol_id=sample_protocol.id,
        speaker_label="SPEAKER_00",
        display_name="Alice",
        color="#3b82f6",
        is_user=False,
        created_at=_utcnow(),
    )
    db_session.add(speaker)
    await db_session.commit()
    await db_session.refresh(speaker)
    return speaker


@pytest_asyncio.fixture
async def sample_utterance(db_session, sample_protocol, sample_speaker) -> Utterance:
    """Create an Utterance row tied to sample_protocol + sample_speaker."""
    utterance = Utterance(
        id=uuid4(),
        protocol_id=sample_protocol.id,
        speaker_id=sample_speaker.id,
        start_sec=0.0,
        end_sec=5.0,
        text="Hello, this is a test utterance.",
        confidence=0.95,
        low_confidence=False,
        important=False,
        is_decision=False,
        corrected_by_llm=False,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db_session.add(utterance)
    await db_session.commit()
    await db_session.refresh(utterance)
    return utterance


@pytest_asyncio.fixture
async def sample_decision(db_session, sample_protocol) -> Decision:
    """Create a Decision row tied to sample_protocol."""
    decision = Decision(
        id=uuid4(),
        protocol_id=sample_protocol.id,
        text="Approve budget for Q1",
        decided_by="Alice",
        priority="high",
        created_at=_utcnow(),
    )
    db_session.add(decision)
    await db_session.commit()
    await db_session.refresh(decision)
    return decision


@pytest_asyncio.fixture
async def sample_action_item(db_session, sample_protocol) -> ActionItem:
    """Create an ActionItem row tied to sample_protocol."""
    item = ActionItem(
        id=uuid4(),
        protocol_id=sample_protocol.id,
        owner="Bob",
        task="Write project plan",
        status="open",
        source="manual",
        created_at=_utcnow(),
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item


@pytest_asyncio.fixture
async def sample_tag(db_session, sample_protocol) -> Tag:
    """Create a Tag row tied to sample_protocol."""
    tag = Tag(
        id=uuid4(),
        protocol_id=sample_protocol.id,
        name="important",
        source="manual",
        color="#ef4444",
        created_at=_utcnow(),
    )
    db_session.add(tag)
    await db_session.commit()
    await db_session.refresh(tag)
    return tag
"""E284: pytest fixtures для тестов HTML_MeetingProtokol.

Минимальная инфраструктура — БД-тесты требуют pytest-postgresql или skip."""
import asyncio
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def event_loop():
    """E284: один event loop на сессию для async тестов."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def test_data_dir(tmp_path) -> Path:
    """Временная директория для тестовых файлов."""
    return tmp_path


@pytest.fixture
def sample_uuid_str() -> str:
    """Тестовый UUID."""
    return "6329f5af-6d16-4b18-be94-2b71b6276e74"


@pytest.fixture
def mock_subprocess(monkeypatch):
    """Мокает subprocess.run для тестов без реальных вызовов."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()

    monkeypatch.setattr("subprocess.run", fake_run)
    return calls
