"""SQLAlchemy ORM models — 17 tables (DATA_MODEL.md).

All tables from /root/.hermes/profiles/alex3/projects/HTML_MeetingProtokol/artifacts/07-data-model/DATA_MODEL.md.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, BYTEA, ENUM, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.db.types import BYTEAType, GUID, JSONType


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


# ============================================================================
# Enums (DATA_MODEL §DDL)
# ============================================================================

protocol_status_enum = ENUM(
    "loaded", "transcribing", "diarizing", "ready", "failed", "live",
    name="protocol_status",
)
audio_source_enum = ENUM("local", "url", "telegram", name="audio_source")
term_category_enum = ENUM(
    "name", "product", "abbreviation", "other", name="term_category"
)
tag_source_enum = ENUM("manual", "llm_extracted", name="tag_source")
item_priority_enum = ENUM("low", "medium", "high", name="item_priority")
item_status_enum = ENUM("open", "in_progress", "done", "cancelled", name="item_status")
item_source_enum = ENUM("manual", "llm_extracted", name="item_source")
llm_provider_enum = ENUM("local_ollama", "gigachat", "hermes", name="llm_provider")
whisper_model_enum = ENUM(
    "tiny", "base", "small", "medium", "large-v3", name="whisper_model"
)
ui_theme_enum = ENUM("light", "dark", "auto", name="ui_theme")
command_status_enum = ENUM("pending", "success", "failed", name="command_status")
export_format_enum = ENUM("docx", "pdf", "html", name="export_format")
task_status_enum = ENUM("queued", "processing", "completed", "failed", name="task_status")
change_source_enum = ENUM("user", "llm", "import", name="change_source")
summary_provider_enum = ENUM(
    "local_llama", "gigachat", "hermes", "manual", name="summary_provider"
)


# ============================================================================
# 1. user_setting (DATA_MODEL §4.16)
# ============================================================================

class UserSetting(Base):
    __tablename__ = "user_setting"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=uuid.uuid4
    )
    llm_provider: Mapped[str] = mapped_column(
        llm_provider_enum, nullable=False, server_default="hermes"
    )
    llm_model: Mapped[str | None] = mapped_column(String(100))
    whisper_model: Mapped[str] = mapped_column(
        whisper_model_enum, nullable=False, server_default="large-v3"
    )
    whisper_prompt: Mapped[str | None] = mapped_column(Text)
    theme: Mapped[str] = mapped_column(ui_theme_enum, nullable=False, server_default="auto")
    hotkey_show_search: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="Ctrl+K"
    )
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # === Extended fields for full settings UI (US-054..066) ===
    user_name: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(50), server_default="Europe/Moscow")
    default_language: Mapped[str] = mapped_column(String(20), server_default="ru")
    use_gpu: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # E254: remote Whisper settings (US-089)
    whisper_remote_enabled: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    whisper_remote_url: Mapped[str | None] = mapped_column(String(255))
    whisper_remote_path: Mapped[str | None] = mapped_column(String(100), server_default="/transcribe")
    default_provider: Mapped[str | None] = mapped_column(String(50))
    fallback_provider: Mapped[str | None] = mapped_column(String(50))
    api_keys: Mapped[str | None] = mapped_column(Text)
    telegram_bot_token: Mapped[str | None] = mapped_column(Text)
    telegram_webhook_url: Mapped[str | None] = mapped_column(Text)
    telegram_allowed_users: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )


# ============================================================================
# 2. audio_file (DATA_MODEL §4.2)
# ============================================================================

class AudioFile(Base):
    __tablename__ = "audio_file"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=uuid.uuid4
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    extension: Mapped[str] = mapped_column(String(10), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(
        audio_source_enum, nullable=False, server_default="local"
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )

    __table_args__ = (
        Index(
            "idx_audio_file_checksum",
            "checksum_sha256",
            unique=True,
            postgresql_where="checksum_sha256 IS NOT NULL",
        ),
        Index("idx_audio_file_source", "source"),
    )


# ============================================================================
# 3. protocol (DATA_MODEL §4.1)
# ============================================================================



# ============================================================================
# 3a. folder (for organizing protocols)
# ============================================================================


class Folder(Base):
    """Folder for grouping protocols."""

    __tablename__ = "folder"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    color: Mapped[str] = mapped_column(String(20), server_default="#3b82f6")
    icon: Mapped[str] = mapped_column(String(50), server_default="folder")
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("folder.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(GUID)  # For multi-user
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )

    # Relationships
    parent: Mapped["Folder | None"] = relationship(
        "Folder", remote_side="Folder.id", backref="children"
    )
    protocols: Mapped[list["Protocol"]] = relationship(back_populates="folder")

    __table_args__ = (
        Index("idx_folder_user", "user_id"),
        Index("idx_folder_parent", "parent_id"),
        Index("idx_folder_sort", "sort_order"),
    )


class Protocol(Base):
    __tablename__ = "protocol"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    date: Mapped[Date] = mapped_column(Date, nullable=False)
    location: Mapped[str | None] = mapped_column(String(255))
    chair: Mapped[str | None] = mapped_column(String(100))
    agenda: Mapped[str | None] = mapped_column(Text)
    decisions_summary: Mapped[str | None] = mapped_column(Text)
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="ru"
    )  # E148: язык совещания (по умолчанию ru)
    wer_quality: Mapped[float | None] = mapped_column(Numeric(5, 2))
    translation_language: Mapped[str | None] = mapped_column(String(10))
    # E149: язык перевода utterance (None = нет перевода)
    status: Mapped[str] = mapped_column(
        protocol_status_enum, nullable=False, server_default="loaded"
    )
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey('folder.id', ondelete='SET NULL')
    )
    audio_file_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("audio_file.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    audio_file: Mapped["AudioFile"] = relationship(lazy="joined")
    folder: Mapped["Folder | None"] = relationship(back_populates="protocols")
    utterances: Mapped[list["Utterance"]] = relationship(
        back_populates="protocol", cascade="all, delete-orphan"
    )
    speakers: Mapped[list["Speaker"]] = relationship(
        back_populates="protocol", cascade="all, delete-orphan"
    )
    tags: Mapped[list["Tag"]] = relationship(
        back_populates="protocol", cascade="all, delete-orphan"
    )
    action_items: Mapped[list["ActionItem"]] = relationship(
        back_populates="protocol", cascade="all, delete-orphan"
    )
    decisions: Mapped[list["Decision"]] = relationship(
        back_populates="protocol", cascade="all, delete-orphan"
    )
    summary: Mapped["Summary | None"] = relationship(
        back_populates="protocol", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        Index("idx_protocol_date", "date"),
        Index("idx_protocol_status", "status"),
        Index("idx_protocol_created_at", "created_at"),
        CheckConstraint(
            "wer_quality IS NULL OR (wer_quality >= 0 AND wer_quality <= 100)",
            name="chk_protocol_wer",
        ),
    )



# ============================================================================
# 9a. transcription_task (отслеживание активных задач)
# ============================================================================


class TranscriptionTask(Base):
    """Активная задача транскрипции."""

    __tablename__ = "transcription_task"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=uuid.uuid4
    )
    protocol_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("protocol.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="queued")
    progress: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.0")
    current_step: Mapped[str | None] = mapped_column(String(100))
    current_chunk: Mapped[int] = mapped_column(Integer, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # E150: Pause / Resume — между сессиями
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_processed_sec: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # до какого момента в аудио дошли
    segments_so_far_json: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # JSON: уже обработанные сегменты (для resume без перетранскрибации)
    audio_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # E153: hash аудиофайла чтобы resume не работал с другой записью

    __table_args__ = (
        Index("idx_task_protocol", "protocol_id"),
        Index("idx_task_status", "status"),
        # E195: защита от опечаток в status. Вместо расширения ENUM
        # (что требует миграции) используем CheckConstraint на уровне БД.
        CheckConstraint(
            "status IN ('queued', 'processing', 'running', 'starting', "
            "'paused', 'completed', 'failed', 'cancelled')",
            name="chk_task_status",
        ),
    )


# ============================================================================
# 4. voice_profile (DATA_MODEL §4.4)
# ============================================================================

class VoiceProfile(Base):
    __tablename__ = "voice_profile"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=uuid.uuid4
    )
    display_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    embedding_vector: Mapped[bytes | None] = mapped_column(BYTEAType)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )


# ============================================================================
# 5. speaker (DATA_MODEL §4.3)
# ============================================================================

class Speaker(Base):
    __tablename__ = "speaker"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=uuid.uuid4
    )
    protocol_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("protocol.id", ondelete="CASCADE"), nullable=False
    )
    speaker_label: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))
    color: Mapped[str | None] = mapped_column(String(7))
    voice_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("voice_profile.id", ondelete="SET NULL")
    )
    is_user: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )

    # Relationships
    protocol: Mapped["Protocol"] = relationship(back_populates="speakers")
    utterances: Mapped[list["Utterance"]] = relationship(back_populates="speaker")

    __table_args__ = (
        Index("idx_speaker_protocol", "protocol_id"),
        UniqueConstraint("protocol_id", "speaker_label", name="idx_speaker_label_protocol"),
    )


# ============================================================================
# 6. utterance (DATA_MODEL §4.5) — CORE TABLE
# ============================================================================

class Utterance(Base):
    __tablename__ = "utterance"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=uuid.uuid4
    )
    protocol_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("protocol.id", ondelete="CASCADE"), nullable=False
    )
    speaker_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("speaker.id", ondelete="SET NULL")
    )
    start_sec: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    end_sec: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_original: Mapped[str | None] = mapped_column(Text)
    # E149: перевод на другой язык (например "en" для английского)
    translation_language: Mapped[str | None] = mapped_column(String(10))
    translation_text: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    low_confidence: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    important: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    corrected_by_llm: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    action_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )

    # Relationships
    protocol: Mapped["Protocol"] = relationship(back_populates="utterances")
    speaker: Mapped["Speaker | None"] = relationship(back_populates="utterances")

    __table_args__ = (
        Index("idx_utterance_protocol", "protocol_id"),
        Index("idx_utterance_speaker", "speaker_id"),
        Index("idx_utterance_low_confidence", "low_confidence"),
        Index("idx_utterance_start", "protocol_id", "start_sec"),
        CheckConstraint("end_sec >= start_sec", name="chk_utterance_duration"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="chk_utterance_confidence",
        ),
    )


# ============================================================================
# 7. screenshot (DATA_MODEL §4.6)
# ============================================================================

class Screenshot(Base):
    __tablename__ = "screenshot"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=uuid.uuid4
    )
    protocol_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("protocol.id", ondelete="CASCADE"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp_sec: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    width_px: Mapped[int | None] = mapped_column(Integer)
    height_px: Mapped[int | None] = mapped_column(Integer)
    file_size_kb: Mapped[int | None] = mapped_column(Integer)
    caption: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )

    __table_args__ = (
        Index("idx_screenshot_protocol", "protocol_id"),
        Index("idx_screenshot_timestamp", "protocol_id", "timestamp_sec"),
    )


# ============================================================================
# 8. decision (DATA_MODEL §4.7)
# ============================================================================

class Decision(Base):
    __tablename__ = "decision"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=uuid.uuid4
    )
    protocol_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("protocol.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(100))
    source_utterance_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("utterance.id", ondelete="SET NULL")
    )
    priority: Mapped[str] = mapped_column(
        item_priority_enum, nullable=False, server_default="medium"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )

    protocol: Mapped["Protocol"] = relationship(back_populates="decisions")

    __table_args__ = (Index("idx_decision_protocol", "protocol_id"),)


# ============================================================================
# 9. action_item (DATA_MODEL §4.8)
# ============================================================================

class ActionItem(Base):
    __tablename__ = "action_item"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=uuid.uuid4
    )
    protocol_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("protocol.id", ondelete="CASCADE"), nullable=False
    )
    owner: Mapped[str | None] = mapped_column(String(100))
    task: Mapped[str] = mapped_column(Text, nullable=False)
    deadline: Mapped[Date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(item_status_enum, nullable=False, server_default="open")
    source_utterance_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("utterance.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(
        item_source_enum, nullable=False, server_default="manual"
    )
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )

    protocol: Mapped["Protocol"] = relationship(back_populates="action_items")

    __table_args__ = (
        Index("idx_action_item_protocol", "protocol_id"),
        Index("idx_action_item_status_deadline", "status", "deadline"),
        Index("idx_action_item_owner", "owner"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="chk_action_item_confidence",
        ),
    )


# ============================================================================
# 10. tag (DATA_MODEL §4.9)
# ============================================================================

class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=uuid.uuid4
    )
    protocol_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("protocol.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    source: Mapped[str] = mapped_column(tag_source_enum, nullable=False, server_default="manual")
    color: Mapped[str | None] = mapped_column(String(7))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )

    protocol: Mapped["Protocol"] = relationship(back_populates="tags")

    __table_args__ = (
        UniqueConstraint("protocol_id", "name", name="idx_tag_protocol_name"),
    )


# ============================================================================
# 11. summary (DATA_MODEL §4.10)
# ============================================================================

class Summary(Base):
    __tablename__ = "summary"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=uuid.uuid4
    )
    protocol_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("protocol.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(summary_provider_enum, nullable=False)
    model: Mapped[str | None] = mapped_column(String(100))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )
    tokens_used: Mapped[int | None] = mapped_column(Integer)
    regenerated: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    protocol: Mapped["Protocol"] = relationship(back_populates="summary")


# ============================================================================
# 12. protocol_version (DATA_MODEL §4.11)
# ============================================================================

class ProtocolVersion(Base):
    __tablename__ = "protocol_version"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=uuid.uuid4
    )
    protocol_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("protocol.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONType, nullable=False)
    changed_field: Mapped[str | None] = mapped_column(String(100))
    changed_by: Mapped[str] = mapped_column(
        change_source_enum, nullable=False, server_default="user"
    )
    change_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )

    __table_args__ = (
        UniqueConstraint("protocol_id", "version_number", name="idx_protocol_version_number"),
    )


# ============================================================================
# 13. diarization_result (DATA_MODEL §4.12)
# ============================================================================

class DiarizationResult(Base):
    __tablename__ = "diarization_result"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=uuid.uuid4
    )
    protocol_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("protocol.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    der_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    num_speakers_detected: Mapped[int | None] = mapped_column(Integer)
    num_speakers_expected: Mapped[int | None] = mapped_column(Integer)
    pipeline_version: Mapped[str | None] = mapped_column(String(50))
    confidence_avg: Mapped[float | None] = mapped_column(Numeric(4, 3))
    segments_json: Mapped[dict | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )

    __table_args__ = (
        CheckConstraint(
            "der_score IS NULL OR (der_score >= 0 AND der_score <= 100)",
            name="chk_diarization_der",
        ),
    )


# ============================================================================
# 14. dictionary (DATA_MODEL §4.13)
# ============================================================================

class Dictionary(Base):
    __tablename__ = "dictionary"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=uuid.uuid4
    )
    user_setting_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("user_setting.id", ondelete="CASCADE"), nullable=False
    )
    term: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(
        term_category_enum, nullable=False, server_default="other"
    )
    weight: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False, server_default="1.00")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )

    __table_args__ = (
        CheckConstraint("weight >= 0 AND weight <= 1", name="chk_dictionary_weight"),
    )


# ============================================================================
# 15. api_user (DATA_MODEL §4.14)
# ============================================================================

class ApiUser(Base):
    __tablename__ = "api_user"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=uuid.uuid4
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    username: Mapped[str | None] = mapped_column(String(100))
    display_name: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    user_setting_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("user_setting.id", ondelete="RESTRICT"), nullable=False
    )
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )

    __table_args__ = (Index("idx_api_user_active", "is_active"),)


# ============================================================================
# 16. command_log (DATA_MODEL §4.15)
# ============================================================================

class CommandLog(Base):
    __tablename__ = "command_log"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=uuid.uuid4
    )
    api_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("api_user.id", ondelete="CASCADE"), nullable=False
    )
    command: Mapped[str] = mapped_column(String(50), nullable=False)
    args: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        command_status_enum, nullable=False, server_default="pending"
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    execution_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_used: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )

    __table_args__ = (
        Index("idx_command_log_user_created", "api_user_id", "created_at"),
        Index("idx_command_log_command", "command"),
    )


# ============================================================================
# 17. export_task (DATA_MODEL §4.17)
# ============================================================================

class ExportTask(Base):
    __tablename__ = "export_task"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=uuid.uuid4
    )
    protocol_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("protocol.id", ondelete="CASCADE"), nullable=False
    )
    format: Mapped[str] = mapped_column(export_format_enum, nullable=False, server_default="docx")
    include_timestamps: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    include_screenshots: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    include_video_links: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    group_by_speaker: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    mark_doubtful: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    status: Mapped[str] = mapped_column(task_status_enum, nullable=False, server_default="queued")
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_path: Mapped[str | None] = mapped_column(Text)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now
    )

    __table_args__ = (
        Index("idx_export_task_protocol", "protocol_id"),
        Index("idx_export_task_status", "status"),
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="chk_export_task_progress",
        ),
    )
