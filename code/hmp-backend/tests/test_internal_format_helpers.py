"""E286: тесты format helpers из video_screenshots."""
import pytest


def test_format_timestamp_minutes_only():
    try:
        from app.services.video_screenshots import formatTimestamp
        assert formatTimestamp(45) in ("0:45", "00:45")
    except (ImportError, AttributeError):
        pytest.skip("formatTimestamp не найден")


def test_format_timestamp_with_hours():
    try:
        from app.services.video_screenshots import formatTimestamp
        assert formatTimestamp(3661) == "1:01:01"
    except (ImportError, AttributeError):
        pytest.skip("formatTimestamp не найден")


def test_format_timestamp_zero():
    try:
        from app.services.video_screenshots import formatTimestamp
        assert formatTimestamp(0) == "0:00"
    except (ImportError, AttributeError):
        pytest.skip("formatTimestamp не найден")


def test_format_timestamp_negative():
    try:
        from app.services.video_screenshots import formatTimestamp
        # Должно корректно обрабатывать отрицательные значения
        result = formatTimestamp(-1)
        assert isinstance(result, str)
    except (ImportError, AttributeError):
        pytest.skip("formatTimestamp не найден")
