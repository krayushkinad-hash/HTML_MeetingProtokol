"""Database session management (ADR-002: PostgreSQL 15)."""
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import text

from app.core.config import settings
from app.core.logging_config import get_logger

# Импорт моделей нужен для reflection в init_db (E042, E046)
from app.db.models import (  # noqa: F401
    ActionItem,
    ApiUser,
    AudioFile,
    CommandLog,
    Decision,
    DiarizationResult,
    Dictionary,
    ExportTask,
    Folder,
    Protocol,
    ProtocolVersion,
    Screenshot,
    Speaker,
    Summary,
    Tag,
    TranscriptionTask,
    UserSetting,
    Utterance,
    VoiceProfile,
)

logger = get_logger(__name__)


def _safe_url(url: str) -> str:
    """Возвращает URL без учётных данных (для логирования)."""
    if "@" in url:
        return url.split("@")[-1]
    return url.split("//")[-1]

# Create async engine
engine = create_async_engine(
    settings.database_url,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_pre_ping=True,
    echo=settings.database_echo,
    future=True,
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# E069: Sync session for use from sync code (e.g., progress_cb from background thread)
from sqlalchemy.orm import sessionmaker, Session
SyncSessionLocal = sessionmaker(
    bind=engine.sync_engine,
    class_=Session,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yield AsyncSession per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for scripts / background tasks."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Initialize database connection and run migrations.

    For SQLite: also creates tables from Base.metadata (development convenience).
    For PostgreSQL: tables are managed by Alembic — see alembic/versions/0001_initial.py.

    For PostgreSQL we use a hybrid approach:
    1. CREATE EXTENSION IF NOT EXISTS "pgcrypto" (для gen_random_uuid)
    2. Run Base.metadata.create_all — создаёт новые таблицы
    3. ALTER TABLE ADD COLUMN IF NOT EXISTS — для колонок в существующих таблицах
    """
    global engine
    from sqlalchemy import text

        # ============================================================
    # Step 0: RESET_DB — опциональный полный сброс (US-XX, dev only!)
    # ============================================================
    if getattr(settings, 'reset_db', False):
        logger.warning("reset_db_enabled_dropping_database")
        async with engine.begin() as conn:
            await conn.execute(text('DROP DATABASE IF EXISTS html_mp WITH (FORCE)'))
            await conn.execute(text('CREATE DATABASE html_mp OWNER hmp'))
        # Закрыть engine и пересоздать
        await engine.dispose()
        engine = create_async_engine(settings.database_url)
        logger.warning("reset_db_database_recreated")

    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("database_connected", url=_safe_url(settings.database_url))
    except Exception as e:
        logger.exception("database_connection_failed", error=str(e))
        raise

    # SQLite: auto-create tables from Base.metadata
    if "sqlite" in settings.database_url:
        from app.db.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("sqlite_tables_created")

        async with AsyncSessionLocal() as session:
            from sqlalchemy import select as _select_sqlite
            result = await session.execute(_select_sqlite(UserSetting))
            if not result.scalar_one_or_none():
                session.add(UserSetting())
                await session.commit()
                logger.info("initial_user_setting_created")
    else:
        # PostgreSQL: full migration pipeline
        from app.db.models import Base

        # Step 1: Ensure pg_default extension for gen_random_uuid()
        async with engine.begin() as conn:
            await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pgcrypto"'))
            logger.info("pgcrypto_extension_ensured")

        # Step 2: create_all — creates NEW tables (won't add columns to existing)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("postgresql_tables_verified")

        # Step 3: ADD COLUMN IF NOT EXISTS for all new columns
        # Use IF NOT EXISTS (Postgres 9.6+) so it's idempotent
        async with engine.begin() as conn:
            # Universal auto-migration via reflection (US-066, E046, E047)
            from sqlalchemy import inspect as _sa_inspect
            for _model, _table in [
                (Protocol, "protocol"),
                (Utterance, "utterance"),
                (Speaker, "speaker"),
                (Tag, "tag"),
                (ActionItem, "action_item"),
                (Decision, "decision"),
                (Summary, "summary"),
                (TranscriptionTask, "transcription_task"),
                (Screenshot, "screenshot"),
                (AudioFile, "audio_file"),
                (Folder, "folder"),
                (ProtocolVersion, "protocol_version"),
                (UserSetting, "user_setting"),
                (ApiUser, "api_user"),
                (CommandLog, "command_log"),
                (ExportTask, "export_task"),
                (DiarizationResult, "diarization_result"),
                (Dictionary, "dictionary"),
                (VoiceProfile, "voice_profile"),
            ]:
                try:
                    _mapper = _sa_inspect(_model)
                    for _col in _mapper.columns:
                        if not hasattr(_col, 'type'):
                            continue
                        _col_name = _col.key
                        # Get existing columns in DB
                        _existing = await conn.execute(text(
                            "SELECT 1 FROM information_schema.columns "
                            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
                        ), {"t": _table, "c": _col_name})
                        if not _existing.first():
                            # Column missing - add it
                            from sqlalchemy import String, Integer, BigInteger, Float, Text, Boolean, DateTime, Date
                            from sqlalchemy.dialects.postgresql import UUID as _PgUUID
                            _t = type(_col.type).__name__
                            if _t == "UUID":
                                _type = "UUID"
                            elif _t == "String":
                                _type = f"VARCHAR({_col.type.length})" if _col.type.length else "VARCHAR(255)"
                            elif _t == "Integer":
                                _type = "INTEGER"
                            elif _t == "BigInteger":
                                _type = "BIGINT"
                            elif _t == "Float":
                                _type = "DOUBLE PRECISION"
                            elif _t == "Text":
                                _type = "TEXT"
                            elif _t == "Boolean":
                                _type = "BOOLEAN"
                            elif _t == "DateTime":
                                _type = "TIMESTAMP WITH TIME ZONE"
                            elif _t == "Date":
                                _type = "DATE"
                            else:
                                _type = "TEXT"

                            _null = "" if getattr(_col, 'nullable', True) else " NOT NULL"
                            _def = ""
                            if hasattr(_col, 'server_default') and _col.server_default is not None:
                                _sd = _col.server_default.arg if hasattr(_col.server_default, 'arg') else str(_col.server_default)
                                # E159: цитировать DEFAULT если это литерал-строка без кавычек
                                if isinstance(_sd, str) and not (_sd.startswith("'") or _sd.lower() in (
                                    "true", "false", "null", "current_timestamp"
                                )):
                                    # Экранируем одинарные кавычки внутри
                                    _sd_escaped = _sd.replace("'", "''")
                                    _sd = f"'{_sd_escaped}'"
                                _def = f" DEFAULT {_sd}"

                            # E159: каждая колонка в отдельной транзакции, чтобы
                            # ошибка одной не убивала все остальные
                            try:
                                await conn.execute(text(
                                    f'ALTER TABLE "{_table}" ADD COLUMN IF NOT EXISTS "{_col_name}" {_type}{_null}{_def}'
                                ))
                                # Принудительный commit после каждой ALTER TABLE
                                await conn.commit()
                                logger.info("column_added", table=_table, column=_col_name)
                            except Exception as col_err:
                                # Rollback чтобы транзакция не была aborted
                                try:
                                    await conn.rollback()
                                except Exception:
                                    pass
                                logger.warning(
                                    "column_add_failed",
                                    table=_table,
                                    column=_col_name,
                                    error=str(col_err)[:200],
                                )
                except Exception as e:
                    logger.warning("auto_migration_warning", table=_table, error=str(e))
                    # Rollback чтобы следующая таблица могла работать
                    try:
                        await conn.rollback()
                    except Exception:
                        pass

        # Step 5: Final commit + then SELECT in a NEW session (after all DDL committed)
        async with AsyncSessionLocal() as session:
            from sqlalchemy import select as _select
            result = await session.execute(_select(UserSetting))
            if not result.scalar_one_or_none():
                session.add(UserSetting())
                await session.commit()
                logger.info("initial_user_setting_created")

        # Step 5b: Migrate legacy audio_file records (US-070)
        # Old code saved as "source.{ext}", new code uses real filename.
        # Try to update file_path for existing files if real filename is found.
        try:
            from pathlib import Path as _Path
            from app.db.models import AudioFile as _AF
            from sqlalchemy import select as _select, update

            async with AsyncSessionLocal() as session:
                # Get all audio files
                result = await session.execute(_select(_AF))
                audio_files = result.scalars().all()

                migrated = 0
                for af in audio_files:
                    if not af.file_path:
                        continue
                    p = _Path(af.file_path)
                    parent = p.parent
                    stem = p.name  # e.g., "source.mp4"

                    # Check if old "source.*" pattern
                    if stem.startswith("source."):
                        # Look for any other file in same dir
                        if parent.exists():
                            siblings = [
                                f for f in parent.iterdir()
                                if f.is_file() and f.name != stem
                            ]
                            if len(siblings) == 1:
                                # Only one other file - assume it's the real one
                                real_file = siblings[0]
                                af.file_path = str(real_file)
                                migrated += 1

                if migrated:
                    await session.commit()
                    logger.info("migrated_audio_file_paths", count=migrated)
        except Exception as e:
            logger.warning("audio_file_migration_failed", error=str(e))

        # Step 6: Reset stuck transcription statuses (на случай если процесс умер)
        # Это происходит при каждом старте backend, но безопасно - просто UPDATE
        try:
            from sqlalchemy import update
            from app.db.models import Protocol as _Protocol
            async with AsyncSessionLocal() as session:
                stuck_result = await session.execute(
                    update(_Protocol)
                    .where(_Protocol.status == "transcribing")
                    .values(status="loaded", duration_sec=None)
                    .returning(_Protocol.id)
                )
                stuck_ids = [r[0] for r in stuck_result.fetchall()]
                if stuck_ids:
                    await session.commit()
                    logger.warning("reset_stuck_transcriptions",
                                   count=len(stuck_ids),
                                   ids=[str(i) for i in stuck_ids[:5]])
                else:
                    logger.debug("no_stuck_transcriptions")
        except Exception as e:
            logger.warning("stuck_transcription_reset_failed", error=str(e))


async def _add_column_if_not_exists(conn, table: str, column: str, col_type: str) -> None:
    """PostgreSQL: ADD COLUMN IF NOT EXISTS (since 9.6)."""
    from sqlalchemy import text
    try:
        await conn.execute(text(
            f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{column}" {col_type}'
        ))
        logger.info("column_added", table=table, column=column)
    except Exception as e:
        logger.warning("column_add_skipped",
                       table=table, column=column, error=str(e))


async def close_db() -> None:
    """Close database engine."""
    await engine.dispose()
    logger.info("database_closed")
