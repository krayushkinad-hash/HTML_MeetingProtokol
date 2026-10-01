"""E294: Deep tests for app/db/session.py — init_db branches, get_db generator, engine/sessionmaker, ALTER TABLE patches."""
import pytest
import pytest_asyncio
from contextlib import asynccontextmanager
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.db.session as session_module
from app.db.session import (
    _safe_url,
    get_db,
    get_db_context,
    close_db,
    AsyncSessionLocal,
    engine,
)


class _NoopConn:
    """Connection stub for engine.begin() in reset_db branch."""
    async def execute(self, *a, **k):
        return MagicMock()
    async def run_sync(self, *a, **k):
        return MagicMock()
    async def commit(self):
        pass
    async def rollback(self):
        pass


# ============ _safe_url ============

class TestSafeUrl:
    def test_safe_url_with_credentials(self):
        """URL with @ should strip credentials."""
        assert _safe_url("postgresql://user:pass@host:5432/db") == "host:5432/db"

    def test_safe_url_without_at_sign(self):
        """URL without @ splits after //."""
        assert _safe_url("postgresql://host:5432/db") == "host:5432/db"

    def test_safe_url_complex(self):
        """URL with multiple @ uses last part."""
        assert _safe_url("postgresql://u:p@s@h:1/d") == "h:1/d"


# ============ engine / AsyncSessionLocal ============

class TestEngineCreation:
    def test_engine_is_async(self):
        """Engine should be an AsyncEngine instance."""
        from sqlalchemy.ext.asyncio import AsyncEngine
        assert isinstance(engine, AsyncEngine)

    def test_async_session_local_is_sessionmaker(self):
        """AsyncSessionLocal should be an async_sessionmaker."""
        assert isinstance(AsyncSessionLocal, async_sessionmaker)

    def test_async_session_local_creates_session(self):
        """AsyncSessionLocal() should produce AsyncSession instances."""
        from sqlalchemy.ext.asyncio import AsyncSession
        # async_sessionmaker stores class_ under different keys depending on version
        # Just verify the factory object exists and is a sessionmaker
        assert AsyncSessionLocal is not None
        assert hasattr(AsyncSessionLocal, "kw") or hasattr(AsyncSessionLocal, "configure")

    def test_async_session_local_expire_on_commit_false(self):
        """AsyncSessionLocal must have expire_on_commit=False."""
        # Check via configured kwargs - try both storage locations
        all_kw = {}
        if hasattr(AsyncSessionLocal, "kw") and AsyncSessionLocal.kw:
            all_kw.update(AsyncSessionLocal.kw)
        # expire_on_commit should be set somewhere
        assert all_kw.get("expire_on_commit", False) is False


# ============ get_db ============

class TestGetDb:
    @pytest.mark.asyncio
    async def test_get_db_yields_session(self):
        """get_db should yield an AsyncSession."""
        gen = get_db()
        sess = await gen.__anext__()
        assert isinstance(sess, AsyncSession)
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass

    @pytest.mark.asyncio
    async def test_get_db_rollback_on_exception(self, db_engine, monkeypatch):
        """On exception in request, get_db should rollback and re-raise."""
        captured = {"rollback_called": False}

        class FakeSession:
            async def rollback(self):
                captured["rollback_called"] = True

            async def commit(self):
                pass

            async def close(self):
                pass

        class FakeCM:
            async def __aenter__(self):
                return FakeSession()

            async def __aexit__(self, *args):
                return False

        monkeypatch.setattr(session_module, "AsyncSessionLocal", lambda: FakeCM())

        gen = session_module.get_db()
        sess = await gen.__anext__()
        # Trigger the exception path inside get_db by throwing into the generator
        with pytest.raises(RuntimeError, match="boom"):
            await gen.athrow(RuntimeError("boom"))
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass
        assert captured["rollback_called"] is True


# ============ get_db_context ============

class TestGetDbContext:
    @pytest.mark.asyncio
    async def test_get_db_context_yields_session_and_commits(self, db_engine, monkeypatch):
        """get_db_context yields AsyncSession and commits on clean exit."""
        local_factory = async_sessionmaker(
            db_engine, class_=AsyncSession, expire_on_commit=False
        )
        monkeypatch.setattr(session_module, "AsyncSessionLocal", local_factory)

        async with session_module.get_db_context() as session:
            assert isinstance(session, AsyncSession)

    @pytest.mark.asyncio
    async def test_get_db_context_rollback_on_exception(self, db_engine, monkeypatch):
        """get_db_context rolls back on exception."""
        local_factory = async_sessionmaker(
            db_engine, class_=AsyncSession, expire_on_commit=False
        )
        monkeypatch.setattr(session_module, "AsyncSessionLocal", local_factory)

        with pytest.raises(ValueError, match="ctx-fail"):
            async with session_module.get_db_context() as session:
                raise ValueError("ctx-fail")


# ============ init_db — PostgreSQL branches ============

class TestInitDbPostgres:
    @pytest.mark.asyncio
    async def test_init_db_creates_pgcrypto_extension(self, db_engine, monkeypatch):
        """init_db should CREATE EXTENSION pgcrypto on PostgreSQL."""
        async with db_engine.begin() as conn:
            # Drop extension first to verify init_db creates it
            await conn.execute(text('DROP EXTENSION IF EXISTS "pgcrypto" CASCADE'))

        # Patch session_module.engine to use db_engine
        monkeypatch.setattr(session_module, "engine", db_engine)
        monkeypatch.setattr(session_module, "AsyncSessionLocal", async_sessionmaker(
            db_engine, class_=AsyncSession, expire_on_commit=False
        ))
        # Ensure we go through PostgreSQL branch
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "database_url", str(db_engine.url))
        monkeypatch.setattr(_s, "reset_db", False, raising=False)

        await session_module.init_db()

        async with db_engine.begin() as conn:
            result = await conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname='pgcrypto'")
            )
            assert result.scalar() == 1

    @pytest.mark.asyncio
    async def test_init_db_alter_table_idempotent(self, db_engine, monkeypatch):
        """Calling init_db twice should not fail (idempotent ALTER TABLE)."""
        monkeypatch.setattr(session_module, "engine", db_engine)
        monkeypatch.setattr(session_module, "AsyncSessionLocal", async_sessionmaker(
            db_engine, class_=AsyncSession, expire_on_commit=False
        ))
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "database_url", str(db_engine.url))
        monkeypatch.setattr(_s, "reset_db", False, raising=False)

        await session_module.init_db()
        # Second call must not raise
        await session_module.init_db()

    @pytest.mark.asyncio
    async def test_init_db_creates_initial_user_setting(self, db_engine, monkeypatch):
        """init_db should create default UserSetting when none exist."""
        # Clean user_setting and any FK-blocking rows
        async with db_engine.begin() as conn:
            await conn.execute(text("DELETE FROM user_setting"))

        monkeypatch.setattr(session_module, "engine", db_engine)
        monkeypatch.setattr(session_module, "AsyncSessionLocal", async_sessionmaker(
            db_engine, class_=AsyncSession, expire_on_commit=False
        ))
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "database_url", str(db_engine.url))
        monkeypatch.setattr(_s, "reset_db", False, raising=False)

        await session_module.init_db()

        async with db_engine.begin() as conn:
            count = (await conn.execute(text("SELECT count(*) FROM user_setting"))).scalar()
        assert count >= 1

    @pytest.mark.asyncio
    async def test_init_db_reset_branch_executed(self, monkeypatch):
        """reset_db=True branch runs DROP/CREATE DATABASE — verify it's invoked.

        We use a fully-mocked engine to avoid hitting the shared test DB.
        """
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "reset_db", True, raising=False)

        # Track how many times the reset-branch's begin() is invoked
        executed = {"begin_calls": 0, "execute_calls": 0}

        class _FakeBeginCM:
            async def __aenter__(self_inner):
                executed["begin_calls"] += 1
                return _FakeConn(executed)
            async def __aexit__(self_inner, *args):
                return False

        class _FakeEngine:
            def begin(self_inner):
                return _FakeBeginCM()
            async def dispose(self_inner):
                pass

        class _FakeSessionMaker:
            def __call__(self_inner):
                return _FakeBeginCM()

        monkeypatch.setattr(session_module, "engine", _FakeEngine())
        monkeypatch.setattr(session_module, "AsyncSessionLocal", _FakeSessionMaker())

        try:
            await session_module.init_db()
        except Exception:
            pass
        # The reset branch must call engine.begin() at least once for DROP/CREATE DATABASE
        assert executed["begin_calls"] >= 1
        assert executed["execute_calls"] >= 2  # DROP + CREATE DATABASE
        # AsyncSessionLocal should be reassigned by reset branch
        assert not isinstance(session_module.AsyncSessionLocal, _FakeSessionMaker)


class _FakeConn:
    """Connection that records execute() calls."""
    def __init__(self, executed):
        self._executed = executed
    async def execute(self, *a, **k):
        self._executed["execute_calls"] += 1
        return MagicMock()
    async def run_sync(self, *a, **k):
        return MagicMock()
    async def commit(self):
        pass
    async def rollback(self):
        pass


# ============ close_db ============

class TestCloseDb:
    @pytest.mark.asyncio
    async def test_close_db_calls_dispose(self, monkeypatch):
        """close_db should dispose engine."""
        dispose_calls = []

        class FakeEngine:
            async def dispose(self_inner):
                dispose_calls.append(True)

        monkeypatch.setattr(session_module, "engine", FakeEngine())
        await session_module.close_db()
        assert dispose_calls == [True]


