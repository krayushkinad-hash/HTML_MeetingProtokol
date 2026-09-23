"""Add folder_id to protocol table."""
import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://hmp:hmp_password@localhost:5432/html_mp")


async def main():
    engine = create_async_engine(DATABASE_URL, echo=True)
    async with engine.begin() as conn:
        # Check if folder_id exists
        result = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'protocol' AND column_name = 'folder_id'"
        ))
        exists = result.scalar() is not None

        if not exists:
            print("Adding folder_id column to protocol table...")
            await conn.execute(text(
                "ALTER TABLE protocol ADD COLUMN folder_id UUID "
                "REFERENCES folder(id) ON DELETE SET NULL"
            ))
            print("Created folder_id column")
        else:
            print("folder_id column already exists")

        # Check if folder table exists
        result = await conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name = 'folder'"
        ))
        if result.scalar() is None:
            print("Creating folder table...")
            await conn.execute(text("""
                CREATE TABLE folder (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name VARCHAR(255) NOT NULL,
                    color VARCHAR(20) DEFAULT '#3b82f6',
                    icon VARCHAR(50) DEFAULT 'folder',
                    parent_id UUID REFERENCES folder(id) ON DELETE CASCADE,
                    user_id UUID,
                    sort_order INTEGER DEFAULT 0,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
            """))
            await conn.execute(text("CREATE INDEX idx_folder_user ON folder(user_id)"))
            await conn.execute(text("CREATE INDEX idx_folder_parent ON folder(parent_id)"))
            print("Created folder table")
        else:
            print("folder table already exists")

        # Ensure transcription_task table
        result = await conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_name = 'transcription_task'"
        ))
        if result.scalar() is None:
            print("Creating transcription_task table...")
            await conn.execute(text('''
                CREATE TABLE transcription_task (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    protocol_id UUID NOT NULL REFERENCES protocol(id) ON DELETE CASCADE,
                    status VARCHAR(20) NOT NULL DEFAULT 'queued',
                    progress DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                    current_step VARCHAR(100),
                    error_message TEXT,
                    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    finished_at TIMESTAMP WITH TIME ZONE
                )
            '''))
            await conn.execute(text("CREATE INDEX idx_task_protocol ON transcription_task(protocol_id)"))
            await conn.execute(text("CREATE INDEX idx_task_status ON transcription_task(status)"))
            print("Created transcription_task table")
        else:
            print("transcription_task table already exists")

    await engine.dispose()
    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
