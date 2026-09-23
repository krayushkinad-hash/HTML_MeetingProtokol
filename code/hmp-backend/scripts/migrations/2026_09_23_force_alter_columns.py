"""E159 — принудительное добавление колонок через прямые ALTER (без DEFAULT).

Создаёт колонки без DEFAULT (чтобы избежать 'cannot use column reference' ошибки),
а потом обновляет существующие строки.
"""
import asyncio
import logging

from sqlalchemy import text
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def upgrade() -> None:
    async with AsyncSessionLocal() as db:
        # 1. Добавляем колонки БЕЗ DEFAULT (это безопасно)
        additions = [
            'ALTER TABLE protocol ADD COLUMN IF NOT EXISTS language VARCHAR(10)',
            'ALTER TABLE protocol ADD COLUMN IF NOT EXISTS translation_language VARCHAR(10)',
            'ALTER TABLE utterance ADD COLUMN IF NOT EXISTS translation_language VARCHAR(10)',
            'ALTER TABLE utterance ADD COLUMN IF NOT EXISTS translation_text TEXT',
            'ALTER TABLE transcription_task ADD COLUMN IF NOT EXISTS paused_at TIMESTAMP WITH TIME ZONE',
            'ALTER TABLE transcription_task ADD COLUMN IF NOT EXISTS last_processed_sec FLOAT',
            'ALTER TABLE transcription_task ADD COLUMN IF NOT EXISTS segments_so_far_json TEXT',
            'ALTER TABLE transcription_task ADD COLUMN IF NOT EXISTS audio_hash VARCHAR(64)',
        ]
        for sql in additions:
            try:
                await db.execute(text(sql))
                await db.commit()
                logger.info(f"✅ {sql[:80]}")
            except Exception as e:
                await db.rollback()
                logger.warning(f"⚠️  {sql[:80]} — {str(e)[:100]}")

        # 2. UPDATE существующих строк (ставим 'ru' для language)
        try:
            await db.execute(text("UPDATE protocol SET language = 'ru' WHERE language IS NULL"))
            await db.commit()
            logger.info("✅ Updated protocol.language for existing rows")
        except Exception as e:
            await db.rollback()
            logger.warning(f"⚠️  update language: {e}")

        # 3. Делаем колонку NOT NULL (после UPDATE)
        try:
            await db.execute(text("ALTER TABLE protocol ALTER COLUMN language SET NOT NULL"))
            await db.commit()
            logger.info("✅ protocol.language SET NOT NULL")
        except Exception as e:
            await db.rollback()
            logger.warning(f"⚠️  SET NOT NULL: {e}")

        # 4. Добавляем DEFAULT теперь когда все строки имеют значение
        try:
            await db.execute(text("ALTER TABLE protocol ALTER COLUMN language SET DEFAULT 'ru'"))
            await db.commit()
            logger.info("✅ protocol.language SET DEFAULT 'ru'")
        except Exception as e:
            await db.rollback()
            logger.warning(f"⚠️  SET DEFAULT: {e}")

        # 5. ALTER TYPE для live
        try:
            await db.execute(text("ALTER TYPE protocol_status ADD VALUE IF NOT EXISTS 'live'"))
            await db.commit()
            logger.info("✅ protocol_status enum: 'live' added")
        except Exception as e:
            await db.rollback()
            logger.warning(f"⚠️  enum: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    asyncio.run(upgrade())
    print()
    print("✅ Done. Restart backend.")
