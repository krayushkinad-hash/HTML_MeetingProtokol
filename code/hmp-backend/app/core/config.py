"""Application configuration via pydantic-settings."""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All application settings, loaded from .env file."""

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent.parent.parent / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="",
    )

    # Application
    app_name: str = "HTML_MeetingProtokol API"
    app_version: str = "1.0.0"
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Backend
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    backend_workers: int = 1
    api_prefix: str = "/api/v1/hmp"
    cors_origins: str = '["*"]'

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins from JSON string."""
        import json
        try:
            return json.loads(self.cors_origins)
        except (json.JSONDecodeError, TypeError):
            return ["http://localhost:3000"]

    # Database
    database_url: str = "postgresql+asyncpg://hmp:hmp_password@127.0.0.1:5432/html_mp"
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_echo: bool = False

    # Ollama (optional local LLM)
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_timeout: int = 60

    # Whisper (ADR-005)
    whisper_model: Literal["tiny", "base", "small", "medium", "large-v3"] = "large-v3"
    # E111: Default CPU — cuda требует cudnn64_9.dll в PATH,
    # иначе Could not locate cudnn_ops64_9.dll.
    # Если у вас настроен CUDA + cudnn — установите в .env: WHISPER_DEVICE=cuda
    whisper_device: Literal["cuda", "cpu"] = "cpu"
    whisper_compute_type: Literal["float16", "int8", "float32"] = "int8"
    # E111: VAD удаляет тишину, но иногда удаляет и речь.
    # По умолчанию OFF чтобы не терять данные.
    whisper_vad_filter: bool = False

    # E118: VAD параметры (для тонкой настройки чувствительности)
    vad_min_silence_duration_ms: int = 1000   # Минимальная пауза для обрезки
    vad_speech_pad_ms: int = 300               # Padding вокруг речи
    vad_threshold: float = 0.5                 # Speech probability threshold (0-1)
    whisper_beam_size: int = 1
    whisper_language: str = "ru"

    # pyannote.audio
    pyannote_model: str = "pyannote/speaker-diarization-3.1"
    huggingface_token: str = ""

    # LLM providers (ADR-004)
    llm_default_provider: Literal["local_ollama", "gigachat", "hermes"] = "hermes"
    llm_fallback_provider: Literal["local_ollama", "gigachat", "hermes"] = "gigachat"

    hermes_api_key: str = ""
    hermes_base_url: str = "https://api.hermes.com/v1"

    gigachat_token: str = ""
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_base_url: str = "https://gigachat.devices.sberbank.ru/api/v1"

    # Memory monitoring (NFR §QG-7, ADR-010)
    rss_limit_mb: int = 4096
    rss_check_interval_sec: int = 5

    # Telegram Bot
    telegram_bot_token: str = ""
    telegram_bot_webhook_url: str = ""
    telegram_bot_webhook_secret: str = ""

    # File storage
    data_dir: str = "~/.html_mp"
    protocols_dir: str = "~/.html_mp/protocols"
    backup_dir: str = "~/.html_mp/backup"

    @property
    def protocols_path(self) -> Path:
        return Path(self.protocols_dir).expanduser()

    @property
    def backup_path(self) -> Path:
        return Path(self.backup_dir).expanduser()

    # Cloud storage
    cloud_download_timeout: int = 300
    cloud_max_file_size_mb: int = 10240

    # Security (ADR-014)
    encryption_master_key: str = ""
    encryption_algorithm: str = "AES-256-GCM"

    # Observability
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = ""
    metrics_enabled: bool = False

    # Rate limiting
    rate_limit_per_minute: int = 100

    # Video streaming
    video_range_chunk_size_mb: int = 8



    # DROP БД при старте (use only for dev! Example: RESET_DB=true)
    reset_db: bool = False

@lru_cache
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()


# Global settings instance
settings = get_settings()
