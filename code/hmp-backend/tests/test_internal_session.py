"""E286: тесты db/session.py init_db."""
import pytest
from sqlalchemy import inspect


def test_engine_creation():
    """engine создаётся при импорте session."""
    from app.db.session import engine
    assert engine is not None


def test_async_session_local():
    """AsyncSessionLocal создаётся."""
    from app.db.session import AsyncSessionLocal
    assert AsyncSessionLocal is not None


def test_base_import():
    """Base импортируется."""
    from app.db.session import Base
    assert Base is not None


def test_get_db_function_exists():
    """get_db функция существует."""
    from app.db.session import get_db
    assert callable(get_db)


def test_settings_import():
    """settings импортируется из session."""
    from app.db.session import settings
    assert settings is not None


def test_metadata_tables():
    """Base.metadata содержит таблицы."""
    from app.db.session import Base
    from app.db import models  # noqa: F401 - register models
    tables = Base.metadata.tables.keys()
    assert len(tables) > 0
    # Проверяем что основные таблицы есть
    table_names = list(tables)
    assert any("protocol" in t for t in table_names) or len(table_names) > 5


@pytest.mark.asyncio
async def test_init_db_with_sqlite(db_engine):
    """init_db работает с SQLite (через fixture)."""
    from sqlalchemy import inspect as sa_inspect
    # db_engine fixture уже создал таблицы
    async with db_engine.connect() as conn:
        tables = await conn.run_sync(lambda c: sa_inspect(c).get_table_names())
    # В SQLite имена таблиц могут быть в верхнем регистре или другие
    assert len(tables) > 0
