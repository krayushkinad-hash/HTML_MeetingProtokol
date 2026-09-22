#!/usr/bin/env python3
"""Generate initial_schema.sql from SQLAlchemy models.

Usage: python scripts/generate_schema.py
"""
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db.models import Base


def main() -> None:
    """Generate SQL DDL from models."""
    engine = create_engine("sqlite:///:memory:")
    metadata = Base.metadata
    sorted_tables = list(metadata.sorted_tables)

    output_path = PROJECT_ROOT / "infra" / "initial_schema.sql"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        f.write("-- ============================================================\n")
        f.write("-- HTML_MeetingProtokol — Initial Schema\n")
        f.write(f"-- Generated from SQLAlchemy models\n")
        f.write(f"-- Target: PostgreSQL 15\n")
        f.write(f"-- Total tables: {len(sorted_tables)}\n")
        f.write("-- ============================================================\n\n")
        f.write("-- Extensions\n")
        f.write('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";\n')
        f.write('CREATE EXTENSION IF NOT EXISTS "pg_trgm";\n\n')

        # ENUMs (extracted from models)
        enums = [
            "protocol_status", "audio_source", "term_category", "tag_source",
            "item_priority", "item_status", "item_source", "llm_provider",
            "whisper_model", "ui_theme", "command_status", "export_format",
            "task_status", "change_source", "summary_provider",
        ]
        f.write("-- ENUM types\n")
        for enum_name in enums:
            f.write(f"-- TODO: Define {enum_name} ENUM\n")
        f.write("\n")

        # Tables
        for table in sorted_tables:
            f.write("-- " + "=" * 60 + "\n")
            f.write(f"-- Table: {table.name}\n")
            f.write("-- " + "=" * 60 + "\n")
            try:
                ddl = str(CreateTable(table).compile(engine))
                f.write(ddl + ";\n\n")
            except Exception as e:
                f.write(f"-- Error generating DDL: {e}\n\n")

        # Indexes
        f.write("-- " + "=" * 60 + "\n")
        f.write("-- Indexes\n")
        f.write("-- " + "=" * 60 + "\n")
        for table in sorted_tables:
            for idx in table.indexes:
                try:
                    ddl = str(CreateIndex(idx).compile(engine))
                    f.write(ddl + ";\n")
                except Exception as e:
                    f.write(f"-- Index {idx.name} skipped: {e}\n")
        f.write("\n")

    print(f"✅ Generated: {output_path}")
    print(f"   Total tables: {len(sorted_tables)}")


if __name__ == "__main__":
    main()
