"""Миграция: добавить поля для pause/resume в TranscriptionTask.

E150: paused_at, last_processed_sec, segments_so_far_json, audio_hash.

Запуск:
    python -m scripts.migrations.2026_09_23_add_pause_resume_fields
"""
import asyncio
import logging

from sqlalchemy import text
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def upgrade() -> None:
    async with AsyncSessionLocal() as db:
        for col, typedef in [
            ("paused_at", "TIMESTAMP WITH TIME ZONE"),
            ("last_processed_sec", "FLOAT"),
            ("segments_so_far_json", "TEXT"),
            ("audio_hash", "VARCHAR(64)"),
        ]:
            try:
                await db.execute(
                    text(f"ALTER TABLE transcription_task ADD COLUMN IF NOT EXISTS {col} {typedef}")
                )
                await db.commit()
                logger.info(f"✅ transcription_task.{col} added")
            except Exception as e:
                await db.rollback()
                logger.warning(f"transcription_task.{col}: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(upgrade())
    print("✅ Migration completed.")
