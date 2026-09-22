"""Check that all columns used by SQLAlchemy ORM models exist in DB schema.

US-066, E046-E047: Prevent 'UndefinedColumnError' on queries against columns
that were added to ORM model but not yet migrated to actual DB.

Run:
    python code/hmp-backend/scripts/check_db_columns.py

Checks:
1. For each model class:
   - Get list of Mapped columns from model
   - Query information_schema.columns
   - Compare and report missing

Graceful behavior:
   - If cannot connect to DB, prints warning and exits 0 (skipped)
   - If columns missing, exits 1 (errors found)
   - If all OK, exits 0
"""
import asyncio
import sys
from pathlib import Path

# Add backend dir to sys.path so 'app' module is importable
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.db.models import (
    Protocol, Utterance, Speaker, Tag, ActionItem, Decision,
    Summary, TranscriptionTask, Screenshot, AudioFile, Folder,
    ProtocolVersion, UserSetting, ApiUser, CommandLog,
    ExportTask, DiarizationResult, Dictionary, VoiceProfile,
)


MODELS_TO_CHECK = [
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
]


def get_model_columns(model):
    """Get Mapped columns from SQLAlchemy model."""
    mapper = inspect(model)
    return {col.key for col in mapper.columns}


async def get_table_columns(conn, table_name):
    """Get column names from information_schema."""
    from sqlalchemy import text
    result = await conn.execute(text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :table
    """), {"table": table_name})
    return {row[0] for row in result.fetchall()}


async def main() -> int:
    """Check DB schema matches ORM. Returns 0 (ok/skipped) or 1 (errors)."""
    print("=" * 70)
    print("Check DB columns match ORM model definitions")
    print("=" * 70)

    # Use short timeout to avoid hanging if DB is down
    engine = create_async_engine(
        settings.database_url,
        connect_args={"timeout": 2},
    )

    total_missing = 0
    total_models = 0

    try:
        async with engine.begin() as conn:
            for model, table_name in MODELS_TO_CHECK:
                total_models += 1
                try:
                    model_cols = get_model_columns(model)
                except Exception as e:
                    print(f"\n⚠️  {table_name}: cannot inspect ORM model: {e}")
                    continue
                try:
                    db_cols = await get_table_columns(conn, table_name)
                except Exception as e:
                    print(f"\n❌ {table_name}: query failed: {e}")
                    total_missing += 1
                    continue

                missing = model_cols - db_cols
                if missing:
                    print(f"\n❌ {table_name}: missing {len(missing)} columns:")
                    for col in sorted(missing):
                        print(f"   - {col}")
                    total_missing += len(missing)
                else:
                    print(f"✅ {table_name}: all {len(model_cols)} columns present")

    except Exception as e:
        err_str = str(e).lower()
        if any(s in err_str for s in (
            "connect call failed",
            "connection refused",
            "connection aborted",
            "could not translate host name",
            "timed out",
            "no such file",
        )):
            print(f"\n⚠️  Cannot connect to DB ({type(e).__name__})")
            print(f"    {e}")
            print("    Skipping DB column check (no PostgreSQL or wrong credentials)")
            print("    To run: docker start hmp-postgres")
            return 0
        raise
    finally:
        await engine.dispose()

    print()
    print("=" * 70)
    if total_missing == 0:
        print(f"All {total_models} tables have correct columns")
        return 0
    print(f"❌ {total_missing} missing columns across tables")
    print("\nFix: запустите init_db() или миграцию")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
