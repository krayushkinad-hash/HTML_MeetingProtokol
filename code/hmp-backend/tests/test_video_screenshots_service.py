"""E283: тесты для video_screenshots service."""
import subprocess
from pathlib import Path
import pytest


def test_extract_frame_with_invalid_input():
    """extract_frame возвращает False для несуществующего файла."""
    import asyncio
    from app.services.video_screenshots import extract_frame
    result = asyncio.run(extract_frame(
        video_path=Path("/nonexistent/path.mp4"),
        timestamp_sec=0.0,
        output_path=Path("/tmp/out.png"),
    ))
    assert result is False


def test_extract_frame_ffmpeg_not_available(monkeypatch):
    """E271: если ffmpeg недоступен — возвращаем False gracefully."""
    import asyncio
    from app.services import video_screenshots as mod

    # Подменяем _sp_run чтобы вернуть "not found"
    def fake_run(cmd, timeout=30):
        return -1, "", f"command not found: {cmd[0]}"

    async def fake_run_async(cmd, timeout=30):
        return -1, "", "not found"

    monkeypatch.setattr(mod, "_sp_run", fake_run)
    monkeypatch.setattr(mod, "_sp_run_async", fake_run_async)

    result = asyncio.run(mod.extract_frame(
        video_path=Path("/tmp/test.mp4"),
        timestamp_sec=0.0,
        output_path=Path("/tmp/out.png"),
    ))
    assert result is False
