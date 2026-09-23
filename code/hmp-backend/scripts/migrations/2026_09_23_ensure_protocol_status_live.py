"""E195: добавить 'live' в protocol_status enum.

Если миграция уже была применена (через 2026_09_22_add_live_to_protocol_status.py),
SQL выдаст "уже существует" — это нормально, ALTER TYPE ... ADD VALUE IF NOT EXISTS
поддерживается PostgreSQL 12+.
"""
import asyncio
from sqlalchemy import text

from app.db.session import engine
from app.core.logging_config import get_logger

logger = get_logger(__name__)


async def main():
    async with engine.begin() as conn:
        try:
            await conn.execute(text(
                "ALTER TYPE protocol_status ADD VALUE IF NOT EXISTS 'live'"
            ))
            # ALTER TYPE в транзакции нельзя использовать, но ADD VALUE — исключение
            await conn.commit()
            logger.info("protocol_status_live_added")
        except Exception as e:
            logger.warning("protocol_status_live_add_failed", error=str(e))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
