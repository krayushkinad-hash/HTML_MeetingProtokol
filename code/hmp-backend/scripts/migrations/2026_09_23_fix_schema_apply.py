"""Аварийная миграция: исправляет все ошибки схемы после 2026-09-22.

Применяет все миграции в правильном порядке с обработкой ошибок.
Запускать при 500 на любом endpoint.

Запуск:
    python -m scripts.migrations.2026_09_23_fix_schema_apply
"""
import asyncio
import logging

from sqlalchemy import text
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


MIGRATIONS = [
    # E145: добавить 'live' в protocol_status enum
    ("ALTER TYPE protocol_status ADD VALUE IF NOT EXISTS 'live'", "enum_live"),

    # E148/E149: поля language + translation_language + translation_text
    ("ALTER TABLE protocol ADD COLUMN IF NOT EXISTS language VARCHAR(10)", "protocol_language"),
    ("ALTER TABLE protocol ADD COLUMN IF NOT EXISTS translation_language VARCHAR(10)", "protocol_translation_language"),
    ("ALTER TABLE utterance ADD COLUMN IF NOT EXISTS translation_language VARCHAR(10)", "utterance_translation_language"),
    ("ALTER TABLE utterance ADD COLUMN IF NOT EXISTS translation_text TEXT", "utterance_translation_text"),

    # E150: pause/resume поля
    ("ALTER TABLE transcription_task ADD COLUMN IF NOT EXISTS paused_at TIMESTAMP WITH TIME ZONE", "tt_paused_at"),
    ("ALTER TABLE transcription_task ADD COLUMN IF NOT EXISTS last_processed_sec FLOAT", "tt_last_processed_sec"),
    ("ALTER TABLE transcription_task ADD COLUMN IF NOT EXISTS segments_so_far_json TEXT", "tt_segments_so_far_json"),
    ("ALTER TABLE transcription_task ADD COLUMN IF NOT EXISTS audio_hash VARCHAR(64)", "tt_audio_hash"),
]


async def upgrade() -> None:
    success = 0
    failed = 0

    async with AsyncSessionLocal() as db:
        for sql, name in MIGRATIONS:
            try:
                await db.execute(text(sql))
                await db.commit()
                logger.info(f"OK {name}")
                success += 1
            except Exception as e:
                await db.rollback()
                err = str(e).strip()[:200]
                logger.warning(f"WARN {name}: {err}")
                failed += 1

        # UPDATE language='ru' for existing rows (если язык уже добавлен)
        try:
            await db.execute(text("UPDATE protocol SET language = 'ru' WHERE language IS NULL"))
            await db.commit()
            logger.info("OK updated language='ru' for existing rows")
        except Exception as e:
            await db.rollback()
            logger.warning(f"WARN update language: {e}")

        # SET NOT NULL и DEFAULT теперь когда все строки имеют значение
        try:
            await db.execute(text("ALTER TABLE protocol ALTER COLUMN language SET NOT NULL"))
            await db.commit()
            logger.info("OK language SET NOT NULL")
        except Exception as e:
            await db.rollback()
            logger.warning(f"WARN SET NOT NULL: {e}")

        try:
            await db.execute(text("ALTER TABLE protocol ALTER COLUMN language SET DEFAULT 'ru'"))
            await db.commit()
            logger.info("OK language SET DEFAULT 'ru'")
        except Exception as e:
            await db.rollback()
            logger.warning(f"WARN SET DEFAULT: {e}")

    logger.info(f"--- {success}/{success + failed} migrations applied ---")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(upgrade())
    print()
    print("Done. Restart backend.")
