"""Pytest configuration and fixtures."""
import os
from pathlib import Path

# Set test environment BEFORE importing the app
os.environ["APP_ENV"] = "testing"
os.environ["DEBUG"] = "true"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost:5432/test_db"
os.environ["ENCRYPTION_MASTER_KEY"] = "dGVzdC1tYXN0ZXIta2V5LTMyLWJ5dGVzLWFiY2RlZmdoaWprbG1ub3BxcnN0dXY="
os.environ["WHISPER_MODEL"] = "tiny"  # Small for tests

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def sample_audio_file(tmp_path: Path) -> Path:
    """Create a dummy audio file for upload tests."""
    file_path = tmp_path / "test_audio.wav"
    file_path.write_bytes(b"RIFF$\x00\x00\x00WAVEfmt ")  # Minimal WAV header
    return file_path


@pytest.fixture
def sample_protocol_data() -> dict:
    """Sample protocol data for tests."""
    return {
        "title": "Test Meeting",
        "date": "2026-09-14",
        "location": "Test Room",
        "chair": "Test Chair",
        "agenda": "Test agenda",
    }


@pytest.fixture(autouse=True)
def reset_settings_cache():
    """Reset the lru_cache on settings between tests."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
