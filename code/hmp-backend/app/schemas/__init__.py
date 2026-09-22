import uuid
"""Pydantic schemas for API request/response (NFR §4.4)."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ============================================================================
# Common
# ============================================================================

class ProblemDetails(BaseModel):
    """RFC 7807 Problem Details (NFR §5.4)."""
    type: str
    title: str
    status: int
    code: str
    message: str
    details: list[dict] | None = None
    correlation_id: UUID | None = None
    timestamp: datetime | None = None


class PaginationParams(BaseModel):
    """Pagination query parameters (NFR §5.11)."""
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=50, ge=1, le=200)
    sort: str | None = None


class PaginatedResponse(BaseModel):
    """Standard paginated response."""
    total: int
    page: int
    limit: int
    items: list


# ============================================================================
# Protocol
# ============================================================================

class ProtocolBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    date: date
    location: str | None = Field(None, max_length=255)
    chair: str | None = Field(None, max_length=100)
    agenda: str | None = None


class ProtocolCreate(ProtocolBase):
    """Create protocol request."""
    pass


class ProtocolUpdate(BaseModel):
    """Partial update."""
    title: str | None = Field(None, max_length=255)
    location: str | None = Field(None, max_length=255)
    chair: str | None = Field(None, max_length=100)
    agenda: str | None = None
    language: str | None = Field(
        None, max_length=10, description="E148: язык совещания (ru, en, ...)"
    )
    translation_language: str | None = Field(
        None, max_length=10, description="E149: целевой язык перевода"
    )


class AudioFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    filename: str
    file_path: str | None = None  # Полный путь к файлу на диске
    extension: str
    size_bytes: int
    mime_type: str | None
    duration_sec: int | None
    sample_rate: int | None
    source: str
    source_url: str | None
    created_at: datetime


class ProtocolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    date: date
    location: str | None
    chair: str | None
    agenda: str | None
    duration_sec: int | None
    wer_quality: float | None
    status: str
    language: str = "ru"  # E148
    translation_language: str | None = None  # E149
    audio_file: AudioFileResponse | None
    created_at: datetime
    updated_at: datetime


class ProtocolListItem(BaseModel):
    """Lightweight protocol for list view."""
    id: UUID
    title: str
    date: date
    status: str
    duration_sec: int | None
    wer_quality: float | None
    speakers_count: int = 0
    utterances_count: int = 0
    tags: list[str] = []
    folder_id: UUID | None = None
    created_at: datetime


# ============================================================================
# Utterance
# ============================================================================

class UtteranceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    protocol_id: UUID
    speaker_id: UUID | None
    speaker_label: str | None = None  # From join
    start_sec: float
    end_sec: float
    text: str
    confidence: float | None
    low_confidence: bool
    important: bool
    corrected_by_llm: bool
    created_at: datetime
    updated_at: datetime


class UtteranceUpdateText(BaseModel):
    """US-048: Edit utterance text."""
    text: str = Field(..., min_length=1, max_length=2000)
    version_snapshot: bool = True


class UtteranceUpdateSpeaker(BaseModel):
    """Reassign speaker."""
    speaker_id: UUID


# ============================================================================
# Speaker
# ============================================================================

class SpeakerBase(BaseModel):
    speaker_label: str = Field(..., max_length=50)
    display_name: str | None = Field(None, max_length=100)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class SpeakerCreate(SpeakerBase):
    pass


class SpeakerUpdate(BaseModel):
    display_name: str | None = Field(None, max_length=100)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    is_user: bool | None = None


class SpeakerResponse(SpeakerBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    protocol_id: UUID
    is_user: bool
    utterance_count: int = 0
    created_at: datetime


class SpeakerMergeRequest(BaseModel):
    """Merge two speakers (US-009)."""
    source_id: UUID
    target_id: UUID
    new_display_name: str | None = None


# ============================================================================
# Transcription
# ============================================================================

class TranscriptionRequest(BaseModel):
    """POST /transcribe/run."""
    protocol_id: UUID
    model: Literal["tiny", "base", "small", "medium", "large-v3"] = "large-v3"
    language: str = "ru"
    prompt: str | None = None
    beam_size: int = Field(default=1, ge=1, le=5)
    compute_type: Literal["float16", "int8", "float32"] = "float16"
    initial_prompt: str | None = None


class TranscriptionStatus(BaseModel):
    task_id: UUID
    protocol_id: UUID
    status: Literal["queued", "processing", "paused", "completed", "failed", "cancelled"]
    progress_percent: int = Field(ge=0, le=100)
    current_chunk: int | None = None
    total_chunks: int | None = None
    peak_rss_mb: float | None = None
    estimated_completion: datetime | None = None
    error_message: str | None = None
    wer_quality: float | None = None


# ============================================================================
# AI
# ============================================================================

class SummarizeRequest(BaseModel):
    protocol_id: UUID
    provider: Literal["hermes", "gigachat", "local_ollama"] = "hermes"
    style: Literal["brief", "detailed", "structured"] = "brief"
    max_words: int = Field(default=500, ge=100, le=2000)
    include_citations: bool = True
    additional_instructions: str | None = Field(None, max_length=500)


class SummarizeResponse(BaseModel):
    id: UUID
    protocol_id: UUID
    text: str
    provider: str
    model: str | None
    tokens_used: int | None
    duration_ms: int | None
    generated_at: datetime


class ExtractActionsRequest(BaseModel):
    protocol_id: UUID
    provider: Literal["hermes", "gigachat", "local_ollama"] = "hermes"
    min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    add_to_existing: bool = True


# ============================================================================
# Dictionary
# ============================================================================

class DictionaryTermCreate(BaseModel):
    term: str = Field(..., min_length=2, max_length=100)
    category: Literal["name", "product", "abbreviation", "other"] = "other"
    weight: float = Field(default=1.00, ge=0.0, le=1.0)


class DictionaryTermUpdate(BaseModel):
    term: str | None = Field(None, min_length=2, max_length=100)
    category: Literal["name", "product", "abbreviation", "other"] | None = None
    weight: float | None = Field(None, ge=0.0, le=1.0)


class DictionaryTermResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    term: str
    category: str
    weight: float
    created_at: datetime


# ============================================================================
# Action Items
# ============================================================================

class ActionItemCreate(BaseModel):
    protocol_id: UUID
    owner: str | None = Field(None, max_length=100)
    task: str = Field(..., min_length=5, max_length=500)
    deadline: date | None = None
    source_utterance_id: UUID | None = None


class ActionItemUpdate(BaseModel):
    owner: str | None = Field(None, max_length=100)
    task: str | None = Field(None, min_length=5, max_length=500)
    deadline: date | None = None
    status: Literal["open", "in_progress", "done", "cancelled"] | None = None


class ActionItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    protocol_id: UUID
    owner: str | None
    task: str
    deadline: date | None
    status: str
    source: str
    confidence: float | None
    completed_at: datetime | None
    created_at: datetime


# ============================================================================
# Export
# ============================================================================

class ExportRequest(BaseModel):
    protocol_id: UUID
    include_timestamps: bool = True
    include_screenshots: bool = True
    include_video_links: bool = True
    group_by_speaker: bool = True
    mark_doubtful: bool = True
    include_summary: bool = True
    include_decisions: bool = True
    include_action_items: bool = True
    template: str = "default"


class ExportStatus(BaseModel):
    task_id: UUID
    protocol_id: UUID
    status: Literal["queued", "processing", "completed", "failed"]
    progress_percent: int = Field(ge=0, le=100)
    estimated_completion: datetime | None
    output_path: str | None
    file_size_bytes: int | None
    error_message: str | None


# ============================================================================
# Live Mode
# ============================================================================

class LiveStartRequest(BaseModel):
    telemost_url: str = Field(..., pattern=r"^https://.*")
    title: str = Field(..., min_length=1, max_length=255)
    audio_device: str = "default"
    enable_screenshots: bool = True
    screenshot_interval_sec: int = Field(default=60, ge=10, le=600)


class LiveStartResponse(BaseModel):
    protocol_id: UUID
    live_session_id: UUID
    websocket_url: str
    telemost_iframe_url: str
    started_at: datetime


# ============================================================================
# Bot
# ============================================================================

class BotUserCreate(BaseModel):
    telegram_id: int
    username: str | None = None
    display_name: str | None = None


class BotSettingsUpdate(BaseModel):
    is_active: bool | None = None
    default_provider: Literal["hermes", "gigachat", "local_ollama"] | None = None
    fallback_provider: Literal["hermes", "gigachat", "local_ollama"] | None = None
    notifications_enabled: bool | None = None


# ============================================================================
# Folders (organize protocols)
# ============================================================================


class FolderCreate(BaseModel):
    """Schema for creating a new folder."""

    name: str = Field(..., min_length=1, max_length=255)
    color: str = Field("#3b82f6", pattern=r"^#[0-9a-fA-F]{6}$")
    icon: str = Field("folder", max_length=50)
    parent_id: uuid.UUID | None = None
    sort_order: int = 0


class FolderUpdate(BaseModel):
    """Schema for updating a folder."""

    name: str | None = Field(None, min_length=1, max_length=255)
    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    icon: str | None = Field(None, max_length=50)
    parent_id: uuid.UUID | None = None
    sort_order: int | None = None


class FolderResponse(BaseModel):
    """Folder response schema."""

    id: uuid.UUID
    name: str
    color: str
    icon: str
    parent_id: uuid.UUID | None
    sort_order: int
    protocol_count: int = 0
    created_at: datetime
    updated_at: datetime


class MoveProtocolRequest(BaseModel):
    """Move protocol to folder."""

    folder_id: uuid.UUID | None  # None = remove from folder


class MoveProtocolsBatch(BaseModel):
    """Move multiple protocols to folder."""

    protocol_ids: list[uuid.UUID]
    folder_id: uuid.UUID | None

class FromUrlRequest(BaseModel):
    """Create protocol from URL request (US-073)."""
    url: str
    title: str | None = None
    date: str | None = None
    location: str | None = None
    chair: str | None = None
