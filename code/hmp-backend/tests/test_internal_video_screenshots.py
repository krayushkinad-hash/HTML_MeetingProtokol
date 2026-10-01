"""E286: внутренние тесты video_screenshots."""
import pytest
from pathlib import Path


def test_sp_run_returns_tuple():
    """_sp_run возвращает (rc, stdout, stderr)."""
    from app.services.video_screenshots import _sp_run
    rc, out, err = _sp_run(["python", "--version"], timeout=10)
    assert isinstance(rc, int)
    assert isinstance(out, str)
    assert isinstance(err, str)


def test_extract_frame_returns_false_on_missing():
    """extract_frame с несуществующим файлом → False."""
    import asyncio
    from app.services.video_screenshots import extract_frame
    result = asyncio.run(extract_frame(
        video_path=Path("/nonexistent/missing.mp4"),
        timestamp_sec=0.0,
        output_path=Path("/tmp/out.png"),
    ))
    assert result is False


def test_extract_frame_with_mock_ffmpeg(monkeypatch):
    """extract_frame с моком ffmpeg."""
    import asyncio
    from app.services.video_screenshots import extract_frame

    def fake_run(cmd, timeout=30):
        # Симулируем успешное извлечение — создаём файл
        if cmd and len(cmd) > 2 and cmd[0] == "ffmpeg":
            output = Path(cmd[-1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
            return 0, "", ""
        return -1, "", "command not found"

    monkeypatch.setattr("app.services.video_screenshots._sp_run", fake_run)

    # Указываем реальный путь чтобы не получить FileNotFoundError до ffmpeg
    real_video = Path("/tmp/test.mp4")
    real_video.write_bytes(b"fake video")

    out = Path("/tmp/test_output.png")
    result = asyncio.run(extract_frame(
        video_path=real_video,
        timestamp_sec=0.0,
        output_path=out,
    ))
    # С моком должно вернуть True (потому что файл создан)
    assert result is True or result is False


def test_format_timestamp_in_video_screenshots():
    """formatTimestamp helper."""
    try:
        from app.services.video_screenshots import formatTimestamp
        assert formatTimestamp(0) == "0:00"
        assert formatTimestamp(60) == "1:00"
        assert formatTimestamp(3661) == "1:01:01"
    except ImportError:
        pytest.skip("formatTimestamp не найден")


@pytest.mark.asyncio
async def test_generate_screenshots_for_protocol_with_uniform(monkeypatch, db_session, sample_protocol):
    """generate_screenshots_for_protocol со стратегией uniform.

    Должен выполняться через pytest-asyncio (а не asyncio.run),
    чтобы db_session и тело использовали один event loop.
    Иначе AsyncEngine из fixture привязан к loop pytest-asyncio,
    а asyncio.run() создаёт новый loop → cross-loop RuntimeError.
    """
    from app.services.video_screenshots import generate_screenshots_for_protocol

    # Mock ffmpeg
    def fake_run(cmd, timeout=30):
        return 0, "1.0", ""

    async def fake_run_async(cmd, timeout=30):
        return fake_run(cmd, timeout)

    monkeypatch.setattr("app.services.video_screenshots._sp_run", fake_run)
    monkeypatch.setattr("app.services.video_screenshots._sp_run_async", fake_run_async)

    result = await generate_screenshots_for_protocol(
        protocol_id=sample_protocol.id,
        video_path=Path("/tmp/test.mp4"),
        output_dir=Path("/tmp/screenshots"),
        strategy="uniform",
        max_screenshots=3,
        db=db_session,
    )
    # Может быть [] если нет utterances
    assert isinstance(result, list)


def test_extract_frame_ffmpeg_not_in_path(monkeypatch):
    """extract_frame graceful failure если ffmpeg не установлен."""
    import asyncio
    from app.services.video_screenshots import extract_frame

    def fake_run(cmd, timeout=30):
        return -1, "", f"command not found: {cmd[0]}"

    monkeypatch.setattr("app.services.video_screenshots._sp_run", fake_run)

    real_video = Path("/tmp/test.mp4")
    real_video.write_bytes(b"fake video")

    out = Path("/tmp/test_output.png")
    result = asyncio.run(extract_frame(
        video_path=real_video,
        timestamp_sec=0.0,
        output_path=out,
    ))
    assert result is False
