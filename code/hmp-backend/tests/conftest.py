"""E288: PostgreSQL-based conftest."""
import asyncio
import os

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import MagicMock

TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://hmp:hmp_password@localhost:5432/html_mp_test",
)


async def _insert(session, model_cls, **kwargs):
    """E349-round4 helper: add + commit + return instance.

    Tests call ``await _insert(db_session, Model, id=..., field=value)``
    instead of manually constructing and committing.
    """
    obj = model_cls(**kwargs)
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return obj


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    from app.db.session import Base
    from app.db import models  # noqa

    async with engine.begin() as conn:
        from sqlalchemy import text
        await conn.execute(text("""
            DO $$
            DECLARE r RECORD;
            BEGIN
                FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public')
                LOOP
                    EXECUTE 'TRUNCATE TABLE "' || r.tablename || '" CASCADE';
                END LOOP;
            END $$;
        """))

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    async_session = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_engine):
    """AsyncClient with PostgreSQL engine."""
    from app.main import app
    from app.db.session import get_db

    async_session = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with async_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# Factories
@pytest_asyncio.fixture
async def sample_protocol(db_session):
    from app.db.models import Protocol, ProtocolStatus
    import uuid
    from datetime import datetime, timezone

    p = Protocol(
        id=uuid.uuid4(),
        title="Test Protocol",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def sample_speaker(db_session, sample_protocol):
    from app.db.models import Speaker
    import uuid

    s = Speaker(
        id=uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_label="SPK_TEST",
    )
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)
    return s


@pytest_asyncio.fixture
async def sample_utterance(db_session, sample_protocol, sample_speaker):
    from app.db.models import Utterance
    import uuid

    u = Utterance(
        id=uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_id=sample_speaker.id,
        start_sec=0.0,
        end_sec=1.0,
        text="Test utterance",
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


@pytest_asyncio.fixture
async def sample_decision(db_session, sample_protocol, sample_utterance):
    from app.db.models import Decision
    import uuid

    d = Decision(
        id=uuid.uuid4(),
        protocol_id=sample_protocol.id,
        utterance_id=sample_utterance.id,
        text="Test decision",
    )
    db_session.add(d)
    await db_session.commit()
    await db_session.refresh(d)
    return d


@pytest_asyncio.fixture
async def sample_action_item(db_session, sample_protocol):
    from app.db.models import ActionItem
    import uuid

    a = ActionItem(
        id=uuid.uuid4(),
        protocol_id=sample_protocol.id,
        title="Test action",
    )
    db_session.add(a)
    await db_session.commit()
    await db_session.refresh(a)
    return a


@pytest_asyncio.fixture
async def sample_tag(db_session):
    from app.db.models import Tag
    import uuid

    t = Tag(
        id=uuid.uuid4(),
        name="test-tag",
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


@pytest.fixture
def mock_ffmpeg(monkeypatch):
    """Patch _sp_run / _sp_run_async with MagicMocks; return (sync_mock, async_mock).

    Tests that need to customise behaviour unpack the tuple:
        sync_mock, async_mock = mock_ffmpeg
        async_mock.side_effect = lambda cmd, timeout=30: (0, "", "")
    """
    from unittest.mock import MagicMock, AsyncMock

    from app.services import video_screenshots as vs

    sync_mock = MagicMock(return_value=(0, "", ""))
    async_mock = AsyncMock(return_value=(0, "", ""))

    monkeypatch.setattr(vs, "_sp_run", sync_mock)
    monkeypatch.setattr(vs, "_sp_run_async", async_mock)
    return sync_mock, async_mock


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_whisper(monkeypatch):
    """E289/E292: stub for whisper model used by /transcribe/* endpoints.

    The transcribe tests pass this fixture but it was never declared in any
    conftest — pytest reported `fixture 'mock_whisper' not found`. We provide
    a no-op stub: patches whisper_models.is_model_loaded → True, get_model →
    MagicMock that yields canned transcriptions. Returning a value is enough
    to satisfy the fixture contract; the tests assert only on HTTP status
    codes (200/202/404/422/500/503) and don't inspect the mock.
    """
    from app.services import whisper_models as wm

    monkeypatch.setattr(wm, "is_model_loaded", lambda model_name: True, raising=False)

    fake_model = MagicMock()
    fake_model.transcribe = MagicMock(
        return_value=(
            {"text": "stub transcription", "language": "ru", "segments": []},
            MagicMock(),
        )
    )

    async def _fake_get_model(model_name, **kwargs):
        return fake_model

    monkeypatch.setattr(wm, "get_model", _fake_get_model, raising=False)

    # Also patch the alias used inside app.routers.transcribe.local if any
    try:
        from app.routers.transcribe import local as local_mod  # noqa: F401

        monkeypatch.setattr(
            "app.routers.transcribe.local._get_whisper_model",
            _fake_get_model,
            raising=False,
        )
    except Exception:
        pass

    return fake_model
