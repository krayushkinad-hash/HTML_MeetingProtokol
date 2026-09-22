"""Initial schema — 17 tables + 15 ENUMs.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-14 20:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all tables, enums, indexes and initial data."""
    # Extensions
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')

    # ENUMs
    op.execute("CREATE TYPE protocol_status AS ENUM ('loaded', 'transcribing', 'diarizing', 'ready', 'failed')")
    op.execute("CREATE TYPE audio_source AS ENUM ('local', 'url', 'telegram')")
    op.execute("CREATE TYPE term_category AS ENUM ('name', 'product', 'abbreviation', 'other')")
    op.execute("CREATE TYPE tag_source AS ENUM ('manual', 'llm_extracted')")
    op.execute("CREATE TYPE item_priority AS ENUM ('low', 'medium', 'high')")
    op.execute("CREATE TYPE item_status AS ENUM ('open', 'in_progress', 'done', 'cancelled')")
    op.execute("CREATE TYPE item_source AS ENUM ('manual', 'llm_extracted')")
    op.execute("CREATE TYPE llm_provider AS ENUM ('local_ollama', 'gigachat', 'hermes')")
    op.execute("CREATE TYPE whisper_model AS ENUM ('tiny', 'base', 'small', 'medium', 'large-v3')")
    op.execute("CREATE TYPE ui_theme AS ENUM ('light', 'dark', 'auto')")
    op.execute("CREATE TYPE command_status AS ENUM ('pending', 'success', 'failed')")
    op.execute("CREATE TYPE export_format AS ENUM ('docx', 'pdf', 'html')")
    op.execute("CREATE TYPE task_status AS ENUM ('queued', 'processing', 'completed', 'failed')")
    op.execute("CREATE TYPE change_source AS ENUM ('user', 'llm', 'import')")
    op.execute(
        "CREATE TYPE summary_provider AS ENUM ('local_llama', 'gigachat', 'hermes', 'manual')"
    )

    # See 0001_initial.sql for full DDL (executed via raw SQL)
    # In production, each CREATE TABLE would be:\n    # op.create_table(\n    #     \"user_setting\",\n    #     sa.Column(\"id\", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text(\"gen_random_uuid()\")),\n    #     ...\n    # )\n    #
    # For brevity and 1:1 mapping with DATA_MODEL.md, we execute the raw SQL:\n
    op.execute(open("infra/migrations/0001_initial.sql").read())


def downgrade() -> None:
    """Drop all tables, enums, extensions."""
    # Drop tables in reverse FK order
    op.execute("DROP TABLE IF EXISTS export_task CASCADE")
    op.execute("DROP TABLE IF EXISTS command_log CASCADE")
    op.execute("DROP TABLE IF EXISTS api_user CASCADE")
    op.execute("DROP TABLE IF EXISTS dictionary CASCADE")
    op.execute("DROP TABLE IF EXISTS diarization_result CASCADE")
    op.execute("DROP TABLE IF EXISTS protocol_version CASCADE")
    op.execute("DROP TABLE IF EXISTS summary CASCADE")
    op.execute("DROP TABLE IF EXISTS tag CASCADE")
    op.execute("DROP TABLE IF EXISTS action_item CASCADE")
    op.execute("DROP TABLE IF EXISTS decision CASCADE")
    op.execute("DROP TABLE IF EXISTS screenshot CASCADE")
    op.execute("DROP TABLE IF EXISTS utterance CASCADE")
    op.execute("DROP TABLE IF EXISTS speaker CASCADE")
    op.execute("DROP TABLE IF EXISTS voice_profile CASCADE")
    op.execute("DROP TABLE IF EXISTS protocol CASCADE")
    op.execute("DROP TABLE IF EXISTS audio_file CASCADE")
    op.execute("DROP TABLE IF EXISTS user_setting CASCADE")

    # Drop ENUMs
    op.execute("DROP TYPE IF EXISTS summary_provider")
    op.execute("DROP TYPE IF EXISTS change_source")
    op.execute("DROP TYPE IF EXISTS task_status")
    op.execute("DROP TYPE IF EXISTS export_format")
    op.execute("DROP TYPE IF EXISTS command_status")
    op.execute("DROP TYPE IF EXISTS ui_theme")
    op.execute("DROP TYPE IF EXISTS whisper_model")
    op.execute("DROP TYPE IF EXISTS llm_provider")
    op.execute("DROP TYPE IF EXISTS item_source")
    op.execute("DROP TYPE IF EXISTS item_status")
    op.execute("DROP TYPE IF EXISTS item_priority")
    op.execute("DROP TYPE IF EXISTS tag_source")
    op.execute("DROP TYPE IF EXISTS term_category")
    op.execute("DROP TYPE IF EXISTS audio_source")
    op.execute("DROP TYPE IF EXISTS protocol_status")
