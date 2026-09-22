"""Миграция: добавить 'live' в enum protocol_status.

E145: нужно для live/stop endpoints. Без этого INSERT/UPDATE с status='live'
падает с "invalid input value for enum protocol_status".

Запуск:
    python -m scripts.migrations.2026_09_22_add_live_to_protocol_status
"""
import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def upgrade() -> None:
    """Добавить 'live' в PostgreSQL enum."""
    async with AsyncSessionLocal() as db:
        # PostgreSQL: ALTER TYPE ... ADD VALUE
        try:
            await db.execute(
                text("ALTER TYPE protocol_status ADD VALUE IF NOT EXISTS 'live'")
            )
            await db.commit()
            logger.info("✅ Added 'live' to protocol_status enum")
        except Exception as e:
            await db.rollback()
            logger.error(f"❌ Failed: {e}")
            raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(upgrade())
    print("✅ Migration completed. Restart backend to apply.")
