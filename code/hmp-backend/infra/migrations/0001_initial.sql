-- ============================================================
-- HTML_MeetingProtokol — Initial Schema (PostgreSQL 15)
-- Based on DATA_MODEL.md (17 tables)
-- Migration: 0001_initial
-- ============================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ============================================================
-- ENUM types
-- ============================================================
CREATE TYPE protocol_status AS ENUM (
    'loaded', 'transcribing', 'diarizing', 'ready', 'failed'
);
CREATE TYPE audio_source AS ENUM ('local', 'url', 'telegram');
CREATE TYPE term_category AS ENUM ('name', 'product', 'abbreviation', 'other');
CREATE TYPE tag_source AS ENUM ('manual', 'llm_extracted');
CREATE TYPE item_priority AS ENUM ('low', 'medium', 'high');
CREATE TYPE item_status AS ENUM ('open', 'in_progress', 'done', 'cancelled');
CREATE TYPE item_source AS ENUM ('manual', 'llm_extracted');
CREATE TYPE llm_provider AS ENUM ('local_ollama', 'gigachat', 'hermes');
CREATE TYPE whisper_model AS ENUM ('tiny', 'base', 'small', 'medium', 'large-v3');
CREATE TYPE ui_theme AS ENUM ('light', 'dark', 'auto');
CREATE TYPE command_status AS ENUM ('pending', 'success', 'failed');
CREATE TYPE export_format AS ENUM ('docx', 'pdf', 'html');
CREATE TYPE task_status AS ENUM ('queued', 'processing', 'completed', 'failed');
CREATE TYPE change_source AS ENUM ('user', 'llm', 'import');
CREATE TYPE summary_provider AS ENUM ('local_llama', 'gigachat', 'hermes', 'manual');

-- ============================================================
-- 1. user_setting
-- ============================================================
CREATE TABLE user_setting (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    llm_provider llm_provider NOT NULL DEFAULT 'hermes',
    llm_model VARCHAR(100),
    whisper_model whisper_model NOT NULL DEFAULT 'large-v3',
    whisper_prompt TEXT,
    theme ui_theme NOT NULL DEFAULT 'auto',
    hotkey_show_search VARCHAR(50) NOT NULL DEFAULT 'Ctrl+K',
    notifications_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 2. audio_file
-- ============================================================
CREATE TABLE audio_file (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_path TEXT NOT NULL,
    filename VARCHAR(255) NOT NULL,
    extension VARCHAR(10) NOT NULL,
    size_bytes BIGINT NOT NULL,
    mime_type VARCHAR(100),
    source audio_source NOT NULL DEFAULT 'local',
    source_url TEXT,
    checksum_sha256 VARCHAR(64),
    duration_sec INTEGER,
    sample_rate INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_audio_file_checksum ON audio_file(checksum_sha256) WHERE checksum_sha256 IS NOT NULL;
CREATE INDEX idx_audio_file_source ON audio_file(source);

-- ============================================================
-- 3. protocol
-- ============================================================
CREATE TABLE protocol (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    date DATE NOT NULL,
    location VARCHAR(255),
    chair VARCHAR(100),
    agenda TEXT,
    decisions_summary TEXT,
    duration_sec INTEGER,
    wer_quality NUMERIC(5,2) CHECK (wer_quality IS NULL OR (wer_quality >= 0 AND wer_quality <= 100)),
    status protocol_status NOT NULL DEFAULT 'loaded',
    audio_file_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    FOREIGN KEY (audio_file_id) REFERENCES audio_file(id) ON DELETE SET NULL
);

CREATE INDEX idx_protocol_date ON protocol(date);
CREATE INDEX idx_protocol_status ON protocol(status);
CREATE INDEX idx_protocol_created_at ON protocol(created_at);
CREATE INDEX idx_protocol_wer_quality ON protocol(wer_quality);

-- ============================================================
-- 4. voice_profile
-- ============================================================
CREATE TABLE voice_profile (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name VARCHAR(100) NOT NULL UNIQUE,
    embedding_vector BYTEA,
    sample_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 5. speaker
-- ============================================================
CREATE TABLE speaker (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    protocol_id UUID NOT NULL,
    speaker_label VARCHAR(50) NOT NULL,
    display_name VARCHAR(100),
    color VARCHAR(7),
    voice_profile_id UUID,
    is_user BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (protocol_id) REFERENCES protocol(id) ON DELETE CASCADE,
    FOREIGN KEY (voice_profile_id) REFERENCES voice_profile(id) ON DELETE SET NULL
);

CREATE INDEX idx_speaker_protocol ON speaker(protocol_id);
CREATE UNIQUE INDEX idx_speaker_label_protocol ON speaker(protocol_id, speaker_label);

-- ============================================================
-- 6. utterance (CORE TABLE)
-- ============================================================
CREATE TABLE utterance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    protocol_id UUID NOT NULL,
    speaker_id UUID,
    start_sec NUMERIC(10,3) NOT NULL,
    end_sec NUMERIC(10,3) NOT NULL,
    text TEXT NOT NULL,
    text_original TEXT,
    confidence NUMERIC(4,3) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    low_confidence BOOLEAN NOT NULL DEFAULT FALSE,
    important BOOLEAN NOT NULL DEFAULT FALSE,
    corrected_by_llm BOOLEAN NOT NULL DEFAULT FALSE,
    action_item_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (protocol_id) REFERENCES protocol(id) ON DELETE CASCADE,
    FOREIGN KEY (speaker_id) REFERENCES speaker(id) ON DELETE SET NULL,
    CHECK (end_sec >= start_sec)
);

CREATE INDEX idx_utterance_protocol ON utterance(protocol_id);
CREATE INDEX idx_utterance_speaker ON utterance(speaker_id);
CREATE INDEX idx_utterance_low_confidence ON utterance(low_confidence);
CREATE INDEX idx_utterance_text_search ON utterance USING GIN (to_tsvector('russian', text));
CREATE INDEX idx_utterance_start ON utterance(protocol_id, start_sec);

-- ============================================================
-- 7. screenshot
-- ============================================================
CREATE TABLE screenshot (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    protocol_id UUID NOT NULL,
    file_path TEXT NOT NULL,
    timestamp_sec NUMERIC(10,3) NOT NULL,
    width_px INTEGER,
    height_px INTEGER,
    file_size_kb INTEGER,
    caption TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (protocol_id) REFERENCES protocol(id) ON DELETE CASCADE
);

CREATE INDEX idx_screenshot_protocol ON screenshot(protocol_id);
CREATE INDEX idx_screenshot_timestamp ON screenshot(protocol_id, timestamp_sec);

-- ============================================================
-- 8. decision
-- ============================================================
CREATE TABLE decision (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    protocol_id UUID NOT NULL,
    text TEXT NOT NULL,
    decided_by VARCHAR(100),
    source_utterance_id UUID,
    priority item_priority NOT NULL DEFAULT 'medium',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (protocol_id) REFERENCES protocol(id) ON DELETE CASCADE,
    FOREIGN KEY (source_utterance_id) REFERENCES utterance(id) ON DELETE SET NULL
);

CREATE INDEX idx_decision_protocol ON decision(protocol_id);

-- ============================================================
-- 9. action_item
-- ============================================================
CREATE TABLE action_item (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    protocol_id UUID NOT NULL,
    owner VARCHAR(100),
    task TEXT NOT NULL,
    deadline DATE,
    status item_status NOT NULL DEFAULT 'open',
    source_utterance_id UUID,
    source item_source NOT NULL DEFAULT 'manual',
    confidence NUMERIC(4,3) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (protocol_id) REFERENCES protocol(id) ON DELETE CASCADE,
    FOREIGN KEY (source_utterance_id) REFERENCES utterance(id) ON DELETE SET NULL
);

CREATE INDEX idx_action_item_protocol ON action_item(protocol_id);
CREATE INDEX idx_action_item_status_deadline ON action_item(status, deadline);
CREATE INDEX idx_action_item_owner ON action_item(owner);

-- ============================================================
-- 10. tag
-- ============================================================
CREATE TABLE tag (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    protocol_id UUID NOT NULL,
    name VARCHAR(50) NOT NULL,
    source tag_source NOT NULL DEFAULT 'manual',
    color VARCHAR(7),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (protocol_id) REFERENCES protocol(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX idx_tag_protocol_name ON tag(protocol_id, name);

-- ============================================================
-- 11. summary
-- ============================================================
CREATE TABLE summary (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    protocol_id UUID NOT NULL UNIQUE,
    text TEXT NOT NULL,
    provider summary_provider NOT NULL,
    model VARCHAR(100),
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    tokens_used INTEGER,
    regenerated INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (protocol_id) REFERENCES protocol(id) ON DELETE CASCADE
);

-- ============================================================
-- 12. protocol_version (undo history)
-- ============================================================
CREATE TABLE protocol_version (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    protocol_id UUID NOT NULL,
    version_number INTEGER NOT NULL,
    snapshot JSONB NOT NULL,
    changed_field VARCHAR(100),
    changed_by change_source NOT NULL DEFAULT 'user',
    change_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (protocol_id) REFERENCES protocol(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX idx_protocol_version_number ON protocol_version(protocol_id, version_number);

-- ============================================================
-- 13. diarization_result
-- ============================================================
CREATE TABLE diarization_result (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    protocol_id UUID NOT NULL UNIQUE,
    der_score NUMERIC(5,2) CHECK (der_score IS NULL OR (der_score >= 0 AND der_score <= 100)),
    num_speakers_detected INTEGER,
    num_speakers_expected INTEGER,
    pipeline_version VARCHAR(50),
    confidence_avg NUMERIC(4,3),
    segments_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (protocol_id) REFERENCES protocol(id) ON DELETE CASCADE
);

-- ============================================================
-- 14. dictionary
-- ============================================================
CREATE TABLE dictionary (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_setting_id UUID NOT NULL,
    term VARCHAR(255) NOT NULL,
    category term_category NOT NULL DEFAULT 'other',
    weight NUMERIC(3,2) NOT NULL DEFAULT 1.00 CHECK (weight >= 0 AND weight <= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (user_setting_id) REFERENCES user_setting(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX idx_dictionary_user_term ON dictionary(user_setting_id, LOWER(term));

-- ============================================================
-- 15. api_user
-- ============================================================
CREATE TABLE api_user (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_id BIGINT NOT NULL UNIQUE,
    username VARCHAR(100),
    display_name VARCHAR(100),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    user_setting_id UUID NOT NULL,
    last_active_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (user_setting_id) REFERENCES user_setting(id) ON DELETE RESTRICT
);

CREATE INDEX idx_api_user_active ON api_user(is_active);

-- ============================================================
-- 16. command_log
-- ============================================================
CREATE TABLE command_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_user_id UUID NOT NULL,
    command VARCHAR(50) NOT NULL,
    args TEXT,
    status command_status NOT NULL DEFAULT 'pending',
    error_message TEXT,
    execution_ms INTEGER,
    tokens_used INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (api_user_id) REFERENCES api_user(id) ON DELETE CASCADE
);

CREATE INDEX idx_command_log_user_created ON command_log(api_user_id, created_at);
CREATE INDEX idx_command_log_command ON command_log(command);

-- ============================================================
-- 17. export_task
-- ============================================================
CREATE TABLE export_task (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    protocol_id UUID NOT NULL,
    format export_format NOT NULL DEFAULT 'docx',
    include_timestamps BOOLEAN NOT NULL DEFAULT TRUE,
    include_screenshots BOOLEAN NOT NULL DEFAULT TRUE,
    include_video_links BOOLEAN NOT NULL DEFAULT TRUE,
    group_by_speaker BOOLEAN NOT NULL DEFAULT TRUE,
    mark_doubtful BOOLEAN NOT NULL DEFAULT TRUE,
    status task_status NOT NULL DEFAULT 'queued',
    progress_percent INTEGER NOT NULL DEFAULT 0 CHECK (progress_percent >= 0 AND progress_percent <= 100),
    output_path TEXT,
    file_size_bytes BIGINT,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (protocol_id) REFERENCES protocol(id) ON DELETE CASCADE
);

CREATE INDEX idx_export_task_protocol ON export_task(protocol_id);
CREATE INDEX idx_export_task_status ON export_task(status);

-- ============================================================
-- Default data: initial user_setting
-- ============================================================
INSERT INTO user_setting (id, llm_provider, whisper_model, theme)
VALUES (gen_random_uuid(), 'hermes', 'large-v3', 'auto');

-- ============================================================
-- End of migration 0001_initial
-- ============================================================
