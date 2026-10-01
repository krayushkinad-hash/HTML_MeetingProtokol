"""E288: conftest для PostgreSQL-based тестов.

Использование:
  DATABASE_URL=postgresql+asyncpg://... pytest tests/ -p no:cacheprovider --confcutdir=tests/

Или через pytest.ini:
  python_files = test_*.pg.py
"""
import asyncio
import os
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# DATABASE_URL from env (default to test)
TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://hmp:hmp_password@localhost:5432/html_mp_test",
)


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """PostgreSQL engine с очисткой данных между тестами."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    # Очищаем все таблицы
    from app.db.session import Base
    from app.db import models  # noqa

    async with engine.begin() as conn:
        from sqlalchemy import text
        # TRUNCATE все таблицы (CASCADE)
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
    """Async session с автоматическим rollback."""
    from app.db.session import Base
    async_session = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_engine):
    """AsyncClient с реальным engine (НЕ переопределяем engine)."""
    # Не подменяем engine — используем настоящий PostgreSQL
    from app.main import app
    from app.db.session import get_db
    from app.db import models  # noqa

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
        name="Test Speaker",
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
    """Мокает ffmpeg subprocess."""
    from app.services import video_screenshots as vs

    def fake_run(cmd, timeout=30):
        return 0, "", ""

    monkeypatch.setattr(vs, "_sp_run", fake_run)
    monkeypatch.setattr(vs, "_sp_run_async", lambda c, t=30: asyncio.sleep(0) or fake_run(c, t))
    return fake_run
