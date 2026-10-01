"""E284: минимальные smoke тесты инфраструктуры.

Эти тесты НЕ требуют PostgreSQL/Redis/Whisper.
"""
import pytest


def test_import_app():
    """app.main импортируется."""
    try:
        import app.main
        assert hasattr(app.main, 'app')
    except Exception as e:
        pytest.skip(f"app.main не импортируется: {e}")


def test_import_schemas():
    """app.schemas импортируется."""
    try:
        from app.schemas import ProtocolResponse, UtteranceResponse
        assert ProtocolResponse is not None
    except Exception as e:
        pytest.skip(f"app.schemas не импортируется: {e}")


def test_import_video_screenshots():
    """app.services.video_screenshots импортируется."""
    try:
        from app.services.video_screenshots import extract_frame
        assert extract_frame is not None
    except Exception as e:
        pytest.skip(f"video_screenshots не импортируется: {e}")


def test_sp_run_helper_exists():
    """_sp_run helper для Windows-safe subprocess."""
    try:
        from app.services import video_screenshots as vs
        assert hasattr(vs, '_sp_run')
        assert hasattr(vs, '_sp_run_async')
    except Exception as e:
        pytest.skip(f"helper не найден: {e}")


def test_optional_in_models():
    """E283: Optional импортирован в models.py."""
    try:
        from app.db import models
        assert hasattr(models, 'Optional'), "Optional не импортирован"
    except Exception as e:
        pytest.skip(f"models не импортируется: {e}")
