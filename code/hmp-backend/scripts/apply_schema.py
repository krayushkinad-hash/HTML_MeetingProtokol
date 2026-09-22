"""Compare ORM schema with current DB schema and generate migration SQL.

E046, E047: Comprehensive DB schema update.

This script:
1. Reads SQLAlchemy ORM models
2. Reads current DB schema (information_schema.columns)
3. Compares them and generates exact ALTER TABLE statements
4. Optionally executes them

Usage:
    # Just show what would change (dry run):
    python code/hmp-backend/scripts/apply_schema.py --dry-run

    # Apply changes:
    python code/hmp-backend/scripts/apply_schema.py --apply

    # Generate SQL file only:
    python code/hmp-backend/scripts/apply_schema.py --sql > migration.sql
"""
import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from app.core.config import settings
from app.db.models import (
    Protocol, Utterance, Speaker, Tag, ActionItem, Decision,
    Summary, TranscriptionTask, Screenshot, AudioFile, Folder,
    ProtocolVersion, UserSetting, ApiUser, CommandLog,
    ExportTask, DiarizationResult, Dictionary, VoiceProfile,
)


MODELS = [
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
    """Get Mapped columns from SQLAlchemy model with types."""
    from sqlalchemy import inspect
    mapper = inspect(model)
    cols = {}
    for col in mapper.columns:
        # Skip relationships / association proxies
        if hasattr(col, 'type'):
            cols[col.key] = col.type
    return cols


def sql_type_for_column(col_type):
    """Convert SQLAlchemy type to PostgreSQL DDL."""
    from sqlalchemy import String, Integer, BigInteger, Float, Text, Boolean, DateTime, Date
    from sqlalchemy.dialects.postgresql import UUID as PgUUID
    type_name = type(col_type).__name__

    if type_name == "UUID":
        return "UUID"
    elif type_name == "String":
        return f"VARCHAR({col_type.length})" if col_type.length else "VARCHAR(255)"
    elif type_name == "Integer":
        return "INTEGER"
    elif type_name == "BigInteger":
        return "BIGINT"
    elif type_name == "Float":
        return "DOUBLE PRECISION"
    elif type_name == "Text":
        return "TEXT"
    elif type_name == "Boolean":
        return "BOOLEAN"
    elif type_name in ("DateTime",):
        return "TIMESTAMP WITH TIME ZONE"
    elif type_name in ("Date",):
        return "DATE"
    else:
        return "TEXT"


async def get_db_columns(conn, table_name):
    """Get columns from information_schema."""
    result = await conn.execute(text("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :table
        ORDER BY ordinal_position
    """), {"table": table_name})
    return {row[0]: {"type": row[1], "nullable": row[2] == "YES", "default": row[3]} for row in result.fetchall()}


async def generate_migration_sql(conn):
    """Generate SQL statements to align DB with ORM."""
    statements = []
    missing_columns_report = []

    for model, table_name in MODELS:
        model_cols = get_model_columns(model)
        db_cols = await get_db_columns(conn, table_name)

        if not db_cols:
            # Table doesn't exist - skip (init_db creates it)
            continue

        for col_name, col_type in model_cols.items():
            if col_name not in db_cols:
                sql_type = sql_type_for_column(col_type)
                # Handle nullable / default
                nullable = "" if col_type.nullable else " NOT NULL"
                default = ""
                if hasattr(col_type, 'default') and col_type.default is not None:
                    default_val = col_type.default.arg if hasattr(col_type.default, 'arg') else col_type.default
                    if default_val is not None and not callable(default_val):
                        if isinstance(default_val, bool):
                            default = f" DEFAULT {str(default_val).upper()}"
                        elif isinstance(default_val, (int, float)):
                            default = f" DEFAULT {default_val}"
                        elif isinstance(default_val, str):
                            default = f" DEFAULT '{default_val}'"
                elif hasattr(col_type, 'server_default') and col_type.server_default is not None:
                    sd = col_type.server_default.arg if hasattr(col_type.server_default, 'arg') else str(col_type.server_default)
                    default = f" DEFAULT {sd}"

                stmt = f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{col_name}" {sql_type}{nullable}{default};'
                statements.append(stmt)
                missing_columns_report.append(f"{table_name}.{col_name} ({sql_type})")

    return statements, missing_columns_report


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Just show what would change")
    parser.add_argument("--apply", action="store_true", help="Apply changes")
    parser.add_argument("--sql", action="store_true", help="Print SQL only")
    args = parser.parse_args()

    print("=" * 70)
    print("DB Schema Migration Tool (E046, E047)")
    print("=" * 70)

    engine = create_async_engine(settings.database_url)

    try:
        async with engine.begin() as conn:
            statements, missing = await generate_migration_sql(conn)

            if args.sql:
                for stmt in statements:
                    print(stmt)
                return

            if not statements:
                print("\n✅ DB schema is in sync with ORM models")
                return

            print(f"\nMissing columns: {len(missing)}\n")
            for col in missing:
                print(f"  - {col}")

            if args.dry_run:
                print("\n(DRY RUN - ничего не применено)")
                print("\nSQL для применения:")
                for stmt in statements:
                    print(f"  {stmt}")
                return

            if args.apply:
                print("\nApplying migration...")
                for stmt in statements:
                    print(f"  → {stmt[:80]}...")
                    await conn.execute(text(stmt))
                print(f"\n✅ Applied {len(statements)} migrations")
            else:
                print("\nИспользование:")
                print("  --dry-run  : показать что изменится")
                print("  --apply    : применить миграцию")
                print("  --sql      : вывести SQL")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
