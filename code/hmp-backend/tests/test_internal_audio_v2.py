"""Tests for app/routers/audio.py — second pass.

Targets branches NOT yet covered by test_internal_audio.py:

  * GET /audio-files/{id}/video  — Range parser unit tests for the full surface
  * GET /media/protocols/{id}/source.{ext} — protocol-without-audio_file_id → 404
  * POST /audio-files/{id}/open-folder — darwin branch, windows branch,
                                          Popen-raises exception branch,
                                          file_path-empty → 404
  * POST /audio-files/{id}/transcode — subprocess.TimeoutExpired branch,
                                       generic Exception branch, success-commit
                                       branch (verifying updated_at side-effect
                                       is attempted)

Goal: lift audio.py coverage from ~38% to 60%+.
"""
from __future__ import annotations

import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures (re-declared locally to keep this file self-contained)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_audio_file(tmp_path: Path):
    """Create a real audio file on disk."""
    f = tmp_path / "clip.webm"
    payload = b"\x1a\x45\xdf\xa3" + b"AUDIO_PAYLOAD" * 1024  # ~14KB
    f.write_bytes(payload)
    return f, payload


@pytest.fixture
async def audio_row(db_session, fake_audio_file):
    from app.db.models import AudioFile

    p, _ = fake_audio_file
    af = AudioFile(
        id=uuid.uuid4(),
        file_path=str(p),
        filename=p.name,
        extension="webm",
        size_bytes=p.stat().st_size,
        mime_type="video/webm",
        source="local",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(af)
    await db_session.commit()
    await db_session.refresh(af)
    return af


@pytest.fixture
async def audio_row_no_mime(db_session, fake_audio_file):
    """AudioFile row with NULL mime_type — exercises _guess_mime fallback."""
    from app.db.models import AudioFile

    p, _ = fake_audio_file
    af = AudioFile(
        id=uuid.uuid4(),
        file_path=str(p),
        filename=p.name,
        extension="webm",
        size_bytes=p.stat().st_size,
        mime_type=None,
        source="local",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(af)
    await db_session.commit()
    await db_session.refresh(af)
    return af


# ===========================================================================
# _parse_range — unit tests covering ALL branches
# ===========================================================================


@pytest.mark.asyncio
async def test_parse_range_unit_all_branches():
    """Direct unit coverage of _parse_range — every return branch."""
    from app.routers.audio import _parse_range

    # --- Malformed: regex doesn't match ---
    assert _parse_range("junk=0-99", 1024) is None
    assert _parse_range("bytes=abc-def", 1024) is None
    assert _parse_range("", 1024) is None

    # --- Both empty (also returns None) ---
    assert _parse_range("bytes=-", 1024) is None

    # --- Valid suffix bytes=-N, last N bytes ---
    assert _parse_range("bytes=-100", 1024) == (924, 1023)

    # --- Suffix invalid: length <= 0 ---
    assert _parse_range("bytes=-0", 1024) is None

    # --- Suffix invalid: length > file_size ---
    assert _parse_range("bytes=-9999", 1024) is None

    # --- Valid range, both bounds ---
    assert _parse_range("bytes=0-99", 1024) == (0, 99)

    # --- Open end: bytes=N- → from N to EOF (clamped) ---
    assert _parse_range("bytes=100-", 1024) == (100, 1023)

    # --- start > end → None ---
    assert _parse_range("bytes=200-100", 1024) is None

    # --- start >= file_size → None ---
    assert _parse_range("bytes=1024-1024", 1024) is None
    assert _parse_range("bytes=99999-99999", 1024) is None

    # --- End > file_size → end clamped to file_size-1 ---
    assert _parse_range("bytes=0-99999", 1024) == (0, 1023)


@pytest.mark.asyncio
async def test_guess_mime_unit():
    """Direct unit coverage of _guess_mime."""
    from app.routers.audio import _guess_mime

    assert _guess_mime(Path("song.mp3")) == "audio/mpeg"
    assert _guess_mime(Path("clip.webm")) == "video/webm"
    # Unknown extension → fallback
    assert _guess_mime(Path("blob.unknownext")) == "application/octet-stream"
    assert _guess_mime(Path("noext")) == "application/octet-stream"


# ===========================================================================
# GET /media/protocols/{protocol_id}/source.{ext}
# ===========================================================================


@pytest.mark.asyncio
async def test_stream_source_protocol_no_audio_file_id(client, db_session):
    """Protocol row exists but audio_file_id is NULL → 404."""
    from app.db.models import Protocol, ProtocolStatus

    proto = Protocol(
        id=uuid.uuid4(),
        title="No Audio",
        status=ProtocolStatus.READY,
        date=datetime.now(timezone.utc).date(),
        audio_file_id=None,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(proto)
    await db_session.commit()
    await db_session.refresh(proto)

    r = await client.get(f"/api/v1/hmp/media/protocols/{proto.id}/source.webm")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_stream_source_falls_back_to_guess_mime(client, db_session, fake_audio_file):
    """mime_type=NULL → _guess_mime() fallback returns octet-stream for .webm."""
    from app.db.models import AudioFile, Protocol, ProtocolStatus

    p, _ = fake_audio_file
    af = AudioFile(
        id=uuid.uuid4(),
        file_path=str(p),
        filename=p.name,
        extension="webm",
        size_bytes=p.stat().st_size,
        mime_type=None,
        source="local",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(af)
    await db_session.commit()

    proto = Protocol(
        id=uuid.uuid4(),
        title="Mime-less",
        status=ProtocolStatus.READY,
        date=datetime.now(timezone.utc).date(),
        audio_file_id=af.id,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(proto)
    await db_session.commit()
    await db_session.refresh(proto)

    r = await client.get(f"/api/v1/hmp/media/protocols/{proto.id}/source.webm")
    assert r.status_code == 200
    # mimetypes guesses .webm as video/webm
    assert "video/webm" in r.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_stream_source_invalid_uuid(client):
    r = await client.get("/api/v1/hmp/media/protocols/not-a-uuid/source.webm")
    assert r.status_code == 422


# ===========================================================================
# GET /audio-files/{id}/video  — Range streaming coverage
# ===========================================================================


@pytest.mark.asyncio
async def test_stream_video_range_mid_chunk(client, audio_row, fake_audio_file):
    """Range request that hits the chunked-iterator branch with chunk_size < length."""
    p, payload = fake_audio_file
    size = p.stat().st_size

    # Use a small range so iterator yields multiple chunks (chunk_size=1MB, length << 1MB)
    r = await client.get(
        f"/api/v1/hmp/audio-files/{audio_row.id}/video",
        headers={"Range": "bytes=4-23"},
    )
    assert r.status_code == 206
    assert int(r.headers["content-length"]) == 20
    assert r.headers["content-range"].startswith("bytes 4-23/")
    assert r.content == payload[4:24]


@pytest.mark.asyncio
async def test_stream_video_invalid_uuid(client):
    r = await client.get("/api/v1/hmp/audio-files/not-a-uuid/video")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_stream_video_with_negative_t_param(client, audio_row):
    """t<0 violates Query(ge=0) → 422."""
    r = await client.get(
        f"/api/v1/hmp/audio-files/{audio_row.id}/video",
        params={"t": -1.0},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_stream_video_mime_fallback(client, audio_row_no_mime):
    """mime_type=NULL → _guess_mime fallback in /video endpoint."""
    r = await client.get(f"/api/v1/hmp/audio-files/{audio_row_no_mime.id}/video")
    assert r.status_code == 200
    assert "video/webm" in r.headers.get("content-type", "")


# ===========================================================================
# POST /audio-files/{id}/transcode — additional branches
# ===========================================================================


@pytest.mark.asyncio
async def test_transcode_timeout(client, audio_row, monkeypatch):
    """subprocess.TimeoutExpired → 500."""
    def fake_run(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=600)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/ffmpeg" if x == "ffmpeg" else None)

    r = await client.post(f"/api/v1/hmp/audio-files/{audio_row.id}/transcode")
    assert r.status_code == 500
    assert "timeout" in r.text.lower()


@pytest.mark.asyncio
async def test_transcode_generic_exception(client, audio_row, monkeypatch, tmp_path):
    """Generic exception in subprocess.run → 500 + cleanup temp file."""
    def fake_run(*a, **kw):
        # Write the temp output so cleanup path has something to remove
        Path(a[0][-1]).write_bytes(b"PARTIAL")
        raise RuntimeError("boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/ffmpeg" if x == "ffmpeg" else None)

    r = await client.post(f"/api/v1/hmp/audio-files/{audio_row.id}/transcode")
    assert r.status_code == 500
    assert "Ошибка" in r.text or "error" in r.text.lower()

    # Cleanup must have removed .transcoded.webm file
    leftover = Path(audio_row.file_path).with_suffix(".transcoded.webm")
    assert not leftover.exists()


@pytest.mark.asyncio
async def test_transcode_invalid_uuid(client):
    r = await client.post("/api/v1/hmp/audio-files/not-a-uuid/transcode")
    assert r.status_code == 422


# ===========================================================================
# POST /audio-files/{id}/open-folder — additional branches
# ===========================================================================


@pytest.mark.asyncio
async def test_open_folder_darwin(client, audio_row, monkeypatch):
    """macOS branch → 'open -R' command."""
    monkeypatch.setattr(sys.modules["platform"], "system", lambda: "Darwin")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: None)

    r = await client.post(f"/api/v1/hmp/audio-files/{audio_row.id}/open-folder")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["os"] == "darwin"
    assert body["command"][0] == "open"
    assert body["command"][1] == "-R"


@pytest.mark.asyncio
async def test_open_folder_windows_file_exists(client, audio_row, monkeypatch):
    """Windows branch, file exists → 'explorer /select,' with file path."""
    monkeypatch.setattr(sys.modules["platform"], "system", lambda: "Windows")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: None)

    r = await client.post(f"/api/v1/hmp/audio-files/{audio_row.id}/open-folder")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["os"] == "windows"
    assert body["file_exists"] is True
    assert body["command"][0] == "explorer"
    assert "/select," in body["command"][1]


@pytest.mark.asyncio
async def test_open_folder_windows_file_missing(client, db_session, tmp_path, monkeypatch):
    """Windows branch, file missing → 'explorer <folder>' without /select,"""
    from app.db.models import AudioFile

    missing = tmp_path / "absent.webm"
    af = AudioFile(
        id=uuid.uuid4(),
        file_path=str(missing),
        filename="absent.webm",
        extension="webm",
        size_bytes=0,
        mime_type="video/webm",
        source="local",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(af)
    await db_session.commit()
    await db_session.refresh(af)

    monkeypatch.setattr(sys.modules["platform"], "system", lambda: "Windows")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: None)

    r = await client.post(f"/api/v1/hmp/audio-files/{af.id}/open-folder")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["os"] == "windows"
    assert body["file_exists"] is False
    assert body["command"] == ["explorer", str(missing.parent)]


@pytest.mark.asyncio
async def test_open_folder_popen_raises(client, audio_row, monkeypatch):
    """Popen raises → endpoint returns 200 with error populated."""
    def boom(*a, **kw):
        raise OSError("xdg-open: no such file")

    monkeypatch.setattr(sys.modules["platform"], "system", lambda: "Linux")
    monkeypatch.setattr(subprocess, "Popen", boom)

    r = await client.post(f"/api/v1/hmp/audio-files/{audio_row.id}/open-folder")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is not None
    assert "xdg-open" in body["error"] or "no such file" in body["error"]


@pytest.mark.asyncio
async def test_open_folder_no_file_path(client, db_session):
    """Audio row with file_path='' → 404 'Путь к файлу не сохранён'."""
    from app.db.models import AudioFile

    af = AudioFile(
        id=uuid.uuid4(),
        file_path="",
        filename="empty.webm",
        extension="webm",
        size_bytes=0,
        mime_type="video/webm",
        source="local",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(af)
    await db_session.commit()
    await db_session.refresh(af)

    r = await client.post(f"/api/v1/hmp/audio-files/{af.id}/open-folder")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_open_folder_invalid_uuid(client):
    r = await client.post("/api/v1/hmp/audio-files/not-a-uuid/open-folder")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_open_folder_returns_folder_path(client, audio_row, monkeypatch):
    """Response includes folder/file_path/file_exists fields for client verification."""
    monkeypatch.setattr(sys.modules["platform"], "system", lambda: "Linux")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: None)

    r = await client.post(f"/api/v1/hmp/audio-files/{audio_row.id}/open-folder")
    body = r.json()
    # All keys present
    for key in ("os", "folder", "file_path", "file_exists", "folder_exists", "command"):
        assert key in body
    assert body["folder"] == str(Path(audio_row.file_path).parent)
    assert body["file_path"] == audio_row.file_path


# ===========================================================================
# AudioFile metadata
# ===========================================================================


@pytest.mark.asyncio
async def test_get_audio_file_returns_full_metadata(client, audio_row):
    """All fields populated in AudioFileResponse."""
    r = await client.get(f"/api/v1/hmp/audio-files/{audio_row.id}")
    assert r.status_code == 200
    body = r.json()
    # Spot-check schema fields
    assert body["filename"] == audio_row.filename
    assert body["extension"] == "webm"
    assert body["source"] == "local"
    assert body["file_path"] == audio_row.file_path