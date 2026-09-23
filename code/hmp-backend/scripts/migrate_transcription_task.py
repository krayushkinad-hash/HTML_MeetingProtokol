"""
Apply transcription_task column migrations to existing DB.

Run this ONCE after deploying new code:
    python code/hmp-backend/scripts/migrate_transcription_task.py

This will:
1. Add 'current_chunk' INTEGER column (if not exists)
2. Add 'current_step' VARCHAR(100) column (if not exists)
3. Reset stuck transcribing statuses to 'loaded'
"""
import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.config import settings


async def main():
    print("Connecting to DB...")
    engine = create_async_engine(settings.database_url)
    AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        # Add columns
        for col_name, col_type in [
            ("current_chunk", "INTEGER DEFAULT 0"),
            ("current_step", "VARCHAR(100)"),
        ]:
            try:
                await conn.execute(text(
                    f'ALTER TABLE transcription_task ADD COLUMN IF NOT EXISTS {col_name} {col_type}'
                ))
                print(f"  + Column '{col_name}' added")
            except Exception as e:
                print(f"  ! Column '{col_name}': {e}")

    # Reset stuck transcriptions
    async with AsyncSessionLocal() as session:
        result = await session.execute(text(
            "UPDATE transcription_task SET status = 'completed', finished_at = NOW() "
            "WHERE status IN ('queued', 'running', 'starting')"
        ))
        await session.commit()
        print(f"  + Reset stuck transcriptions: {result.rowcount}")

    await engine.dispose()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
