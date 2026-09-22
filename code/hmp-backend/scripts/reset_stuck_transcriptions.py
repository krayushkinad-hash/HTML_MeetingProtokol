"""Reset stuck transcription statuses.

Finds protocols with status='transcribing' and resets them to 'loaded'
since the process is gone (backend restarted).

Run: python reset_stuck_transcriptions.py
"""
import asyncio
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.db.models import Protocol


async def main():
    """Reset stuck transcriptions."""
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://hmp:hmp_password@localhost:5432/html_mp"
    )

    engine = create_async_engine(database_url, echo=False)
    session_maker = async_sessionmaker(engine, class_=AsyncSession)

    async with session_maker() as session:
        # Find stuck protocols
        result = await session.execute(
            select(Protocol).where(Protocol.status == "transcribing")
        )
        stuck = result.scalars().all()

        if not stuck:
            print("No stuck transcriptions found.")
            await engine.dispose()
            return

        print(f"Found {len(stuck)} stuck transcriptions:")
        for p in stuck:
            print(f"  - {p.id} '{p.title}' (created {p.created_at})")

        # Reset them
        await session.execute(
            update(Protocol)
            .where(Protocol.status == "transcribing")
            .values(status="loaded", duration_sec=None)
        )
        await session.commit()
        print(f"\nReset {len(stuck)} protocols to 'loaded'")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
