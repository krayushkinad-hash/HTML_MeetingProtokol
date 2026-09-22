"""Миграция: добавить language в Protocol + translation_* в Utterance.

E148: Protocol.language (по умолчанию "ru").
E149: Utterance.translation_language + translation_text.

Запуск:
    python -m scripts.migrations.2026_09_23_add_language_fields
"""
import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def upgrade() -> None:
    async with AsyncSessionLocal() as db:
        try:
            # E148: Protocol.language
            await db.execute(
                text("ALTER TABLE protocol ADD COLUMN IF NOT EXISTS language VARCHAR(10) NOT NULL DEFAULT 'ru'")
            )
            await db.commit()
            logger.info("✅ protocol.language added")
        except Exception as e:
            await db.rollback()
            logger.warning(f"protocol.language: {e}")

        try:
            # E148: Protocol.translation_language
            await db.execute(
                text("ALTER TABLE protocol ADD COLUMN IF NOT EXISTS translation_language VARCHAR(10)")
            )
            await db.commit()
            logger.info("✅ protocol.translation_language added")
        except Exception as e:
            await db.rollback()
            logger.warning(f"protocol.translation_language: {e}")

        try:
            # E149: Utterance.translation_language
            await db.execute(
                text("ALTER TABLE utterance ADD COLUMN IF NOT EXISTS translation_language VARCHAR(10)")
            )
            await db.commit()
            logger.info("✅ utterance.translation_language added")
        except Exception as e:
            await db.rollback()
            logger.warning(f"utterance.translation_language: {e}")

        try:
            # E149: Utterance.translation_text
            await db.execute(
                text("ALTER TABLE utterance ADD COLUMN IF NOT EXISTS translation_text TEXT")
            )
            await db.commit()
            logger.info("✅ utterance.translation_text added")
        except Exception as e:
            await db.rollback()
            logger.warning(f"utterance.translation_text: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(upgrade())
    print("✅ Migration completed.")
