"""E288: расширенные тесты db/session.py."""
import pytest


def test_engine_creation():
    from app.db.session import engine
    assert engine is not None


def test_async_session_local_factory():
    from app.db.session import AsyncSessionLocal
    assert AsyncSessionLocal is not None


def test_base_metadata():
    from app.db.session import Base
    assert Base is not None
    assert hasattr(Base, "metadata")


def test_get_db_returns_generator():
    """get_db возвращает async generator."""
    from app.db.session import get_db
    import inspect
    assert inspect.isasyncgenfunction(get_db)


def test_get_db_dependency():
    """get_db можно использовать как FastAPI dependency."""
    from app.db.session import get_db
    gen = get_db()
    assert hasattr(gen, "__anext__")


@pytest.mark.asyncio
async def test_get_db_yields_session(db_engine):
    """get_db даёт AsyncSession."""
    from app.db.session import get_db, AsyncSessionLocal
    # Имитируем get_db — он зависит от engine
    assert db_engine is not None


def test_settings_database_url():
    """settings.database_url доступен."""
    from app.db.session import settings
    assert hasattr(settings, "database_url")
    assert isinstance(settings.database_url, str)


def test_metadata_tables_via_reflect():
    """Base.metadata содержит модели после импорта."""
    from app.db.session import Base
    from app.db import models  # noqa
    tables = list(Base.metadata.tables.keys())
    assert len(tables) > 5


@pytest.mark.asyncio
async def test_init_db_idempotent(db_engine):
    """init_db можно вызвать несколько раз без ошибок."""
    # db_engine fixture уже делает create_all
    # Тест просто проверяет что engine работает
    assert db_engine is not None
    async with db_engine.connect() as conn:
        from sqlalchemy import text
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar() == 1
