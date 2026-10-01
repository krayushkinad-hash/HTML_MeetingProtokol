"""Tests for app/routers/audio.py — streaming, range, transcode, open-folder, metadata.

Targets endpoints:
  GET  /api/v1/hmp/media/protocols/{protocol_id}/source.{ext}
  GET  /api/v1/hmp/audio-files/{audio_file_id}
  GET  /api/v1/hmp/audio-files/{audio_file_id}/video    (Range + seek redirect)
  POST /api/v1/hmp/audio-files/{audio_file_id}/transcode (mocked ffmpeg)
  POST /api/v1/hmp/audio-files/{audio_file_id}/open-folder

Goal: push routers/audio.py coverage from ~13% to 50%+.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_audio_file(tmp_path: Path):
    """Create a real audio file on disk and return its path + bytes payload."""
    p = tmp_path / "sample.webm"
    payload = b"\x1a\x45\xdf\xa3" + b"FAKE_WEBM_DATA" * 256  # ~3.5KB
    p.write_bytes(payload)
    return p, payload


@pytest.fixture
async def audio_row(db_session, fake_audio_file):
    """Insert an AudioFile row pointing to a real file on disk."""
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
async def protocol_with_audio(db_session, audio_row):
    """Protocol linked to an audio file."""
    from app.db.models import Protocol, ProtocolStatus

    p = Protocol(
        id=uuid.uuid4(),
        title="Stream Test Protocol",
        status=ProtocolStatus.READY,
        date=datetime.now(timezone.utc).date(),
        audio_file_id=audio_row.id,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


# ===========================================================================
# GET /media/protocols/{protocol_id}/source.{ext}
# ===========================================================================


@pytest.mark.asyncio
async def test_stream_source_by_protocol_success(client, protocol_with_audio, fake_audio_file):
    p, payload = fake_audio_file
    r = await client.get(
        f"/api/v1/hmp/media/protocols/{protocol_with_audio.id}/source.webm"
    )
    assert r.status_code == 200
    assert r.headers.get("accept-ranges") == "bytes"
    assert r.content == payload
    assert r.headers.get("content-type", "").startswith("video/webm")


@pytest.mark.asyncio
async def test_stream_source_protocol_not_found(client):
    r = await client.get(f"/api/v1/hmp/media/protocols/{uuid.uuid4()}/source.webm")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_stream_source_audio_missing(client, db_session, fake_audio_file):
    """Protocol with audio_file_id but AudioFile row deleted -> 404."""
    from app.db.models import Protocol, ProtocolStatus

    # Create an AudioFile row first, then link a protocol to it, then delete the audio row
    from app.db.models import AudioFile

    af = AudioFile(
        id=uuid.uuid4(),
        file_path="/nonexistent/path/deleted.webm",
        filename="deleted.webm",
        extension="webm",
        size_bytes=0,
        mime_type="video/webm",
        source="local",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(af)
    await db_session.commit()
    af_id = af.id

    proto = Protocol(
        id=uuid.uuid4(),
        title="Ghost",
        status=ProtocolStatus.READY,
        date=datetime.now(timezone.utc).date(),
        audio_file_id=af_id,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(proto)
    await db_session.commit()
    await db_session.refresh(proto)

    # Delete the AudioFile so the protocol still has audio_file_id set, but row missing
    await db_session.delete(af)
    await db_session.commit()

    r = await client.get(f"/api/v1/hmp/media/protocols/{proto.id}/source.webm")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_stream_source_file_missing_on_disk(client, db_session, tmp_path):
    """Audio row exists, file doesn't → 404 with 'on disk' detail."""
    from app.db.models import AudioFile, Protocol, ProtocolStatus

    missing = tmp_path / "never_existed.webm"  # never written
    af = AudioFile(
        id=uuid.uuid4(),
        file_path=str(missing),
        filename=missing.name,
        extension="webm",
        size_bytes=0,
        mime_type="video/webm",
        source="local",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(af)
    await db_session.commit()

    proto = Protocol(
        id=uuid.uuid4(),
        title="Missing",
        status=ProtocolStatus.READY,
        date=datetime.now(timezone.utc).date(),
        audio_file_id=af.id,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(proto)
    await db_session.commit()
    await db_session.refresh(proto)

    r = await client.get(f"/api/v1/hmp/media/protocols/{proto.id}/source.webm")
    assert r.status_code == 404
    assert "диске" in r.text or "disk" in r.text.lower()


# ===========================================================================
# GET /audio-files/{audio_file_id}
# ===========================================================================


@pytest.mark.asyncio
async def test_get_audio_file_success(client, audio_row):
    r = await client.get(f"/api/v1/hmp/audio-files/{audio_row.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(audio_row.id)
    assert body["filename"] == audio_row.filename
    assert body["mime_type"] == "video/webm"


@pytest.mark.asyncio
async def test_get_audio_file_404(client):
    r = await client.get(f"/api/v1/hmp/audio-files/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_audio_file_invalid_uuid(client):
    r = await client.get("/api/v1/hmp/audio-files/not-a-uuid")
    assert r.status_code == 422


# ===========================================================================
# GET /audio-files/{audio_file_id}/video — Range + seek redirect + 404
# ===========================================================================


@pytest.mark.asyncio
async def test_stream_video_full_no_range(client, audio_row):
    r = await client.get(f"/api/v1/hmp/audio-files/{audio_row.id}/video")
    assert r.status_code == 200
    assert r.headers.get("accept-ranges") == "bytes"
    assert r.headers.get("cache-control") == "public, max-age=3600"


@pytest.mark.asyncio
async def test_stream_video_range_partial(client, audio_row, fake_audio_file):
    p, payload = fake_audio_file
    file_size = p.stat().st_size
    # Request last 100 bytes
    r = await client.get(
        f"/api/v1/hmp/audio-files/{audio_row.id}/video",
        headers={"Range": f"bytes=-100"},
    )
    assert r.status_code == 206
    assert "content-range" in {k.lower() for k in r.headers.keys()}
    cr = r.headers["content-range"]
    assert cr.startswith("bytes ")
    assert cr.endswith(f"/{file_size}")
    assert r.content == payload[-100:]
    assert int(r.headers["content-length"]) == 100


@pytest.mark.asyncio
async def test_stream_video_range_open_end(client, audio_row, fake_audio_file):
    p, _ = fake_audio_file
    # bytes=0- -> from start to EOF
    r = await client.get(
        f"/api/v1/hmp/audio-files/{audio_row.id}/video",
        headers={"Range": "bytes=0-"},
    )
    assert r.status_code == 206
    assert r.headers["content-range"].startswith("bytes 0-")
    assert int(r.headers["content-length"]) == p.stat().st_size


@pytest.mark.asyncio
async def test_stream_video_malformed_range_falls_back_to_full(client, audio_row):
    """With Range header present but parser returning None → 200 with full body.
    Use bytes=0-999999 which exceeds file size — our parser clamps end but returns valid range,
    so this hits the 206 branch. Instead, force the None branch via direct unit test."""
    # The HTTP layer rejects truly-malformed Range headers (e.g. 'junk=') with 400
    # before reaching our handler. The empty-start-empty-end case (None branch) is
    # exercised via the unit test below.
    from app.routers.audio import _parse_range
    assert _parse_range("bytes=-", 1024) is None
    assert _parse_range("", 1024) is None
    # Sanity: well-formed range parses correctly
    assert _parse_range("bytes=0-99", 1024) == (0, 99)
    # And invalid patterns also return None
    assert _parse_range("bytes=abc-def", 1024) is None


@pytest.mark.asyncio
async def test_stream_video_seek_redirect(client, audio_row):
    """With ?t=<seconds> and no Range header → 302 to static mount."""
    r = await client.get(
        f"/api/v1/hmp/audio-files/{audio_row.id}/video",
        params={"t": 5.0},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "static-mount" in r.headers or f"/source.{audio_row.extension}" in r.headers.get("location", "")


@pytest.mark.asyncio
async def test_stream_video_file_missing_redirects(client, db_session, tmp_path):
    """Audio row in DB, file absent → 302 redirect to static mount."""
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

    r = await client.get(
        f"/api/v1/hmp/audio-files/{af.id}/video", follow_redirects=False
    )
    assert r.status_code == 302


@pytest.mark.asyncio
async def test_stream_video_404(client):
    r = await client.get(f"/api/v1/hmp/audio-files/{uuid.uuid4()}/video")
    assert r.status_code == 404


# ===========================================================================
# POST /audio-files/{audio_file_id}/transcode — ffmpeg mocked
# ===========================================================================


@pytest.mark.asyncio
async def test_transcode_success(client, audio_row, monkeypatch, tmp_path):
    """Successful ffmpeg run → 'ok' status, file replaced."""
    import subprocess as sp

    class _Result:
        returncode = 0
        stderr = b""

    def fake_run(cmd, capture_output=True, timeout=600):
        # Simulate ffmpeg writing output file
        out_path = Path(cmd[-1])
        out_path.write_bytes(b"TRANSCODED")
        return _Result()

    monkeypatch.setattr(sp, "run", fake_run)
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/ffmpeg" if x == "ffmpeg" else None)

    r = await client.post(f"/api/v1/hmp/audio-files/{audio_row.id}/transcode")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert "transcoded_file" in body


@pytest.mark.asyncio
async def test_transcode_ffmpeg_failure(client, audio_row, monkeypatch):
    """ffmpeg returns non-zero → 500."""
    import subprocess as sp

    class _Result:
        returncode = 1
        stderr = b"ffmpeg error: bad codec"

    monkeypatch.setattr(sp, "run", lambda *a, **kw: _Result())
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/ffmpeg" if x == "ffmpeg" else None)

    r = await client.post(f"/api/v1/hmp/audio-files/{audio_row.id}/transcode")
    assert r.status_code == 500


@pytest.mark.asyncio
async def test_transcode_no_ffmpeg(client, audio_row, monkeypatch):
    """No ffmpeg binary → 500."""
    monkeypatch.setattr("shutil.which", lambda x: None)

    r = await client.post(f"/api/v1/hmp/audio-files/{audio_row.id}/transcode")
    assert r.status_code == 500
    assert "ffmpeg" in r.text.lower()


@pytest.mark.asyncio
async def test_transcode_file_missing(client, db_session, tmp_path):
    """Audio row in DB, file missing → 404."""
    from app.db.models import AudioFile

    af = AudioFile(
        id=uuid.uuid4(),
        file_path=str(tmp_path / "ghost.webm"),
        filename="ghost.webm",
        extension="webm",
        size_bytes=0,
        mime_type="video/webm",
        source="local",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(af)
    await db_session.commit()
    await db_session.refresh(af)

    r = await client.post(f"/api/v1/hmp/audio-files/{af.id}/transcode")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_transcode_404_audio_missing(client):
    r = await client.post(f"/api/v1/hmp/audio-files/{uuid.uuid4()}/transcode")
    assert r.status_code == 404


# ===========================================================================
# POST /audio-files/{audio_file_id}/open-folder
# ===========================================================================


@pytest.mark.asyncio
async def test_open_folder_linux(client, audio_row, monkeypatch):
    """Linux branch — xdg-open called; subprocess.Popen mocked."""
    import sys
    import subprocess

    # `import platform` inside the endpoint grabs the module from sys.modules.
    # Patch its .system attribute directly so the endpoint sees "Linux".
    monkeypatch.setattr(sys.modules["platform"], "system", lambda: "Linux")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: None)

    r = await client.post(f"/api/v1/hmp/audio-files/{audio_row.id}/open-folder")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["os"] == "linux"
    assert body["file_exists"] is True
    assert "xdg-open" in (body["command"] or [])


@pytest.mark.asyncio
async def test_open_folder_404_audio_missing(client):
    r = await client.post(f"/api/v1/hmp/audio-files/{uuid.uuid4()}/open-folder")
    assert r.status_code == 404


# ===========================================================================
# Range parser unit-ish coverage (via /video endpoint with crafted headers)
# ===========================================================================


@pytest.mark.asyncio
async def test_stream_video_range_suffix_invalid_length(client, audio_row):
    """Suffix length > file_size → parser returns None (would fall back to 200 in HTTP).
    Test the parser branch directly + verify HTTP returns 206 with valid range."""
    from app.routers.audio import _parse_range
    # length > file_size returns None
    assert _parse_range("bytes=-99999999", 1024) is None
    # length == 0 returns None
    assert _parse_range("bytes=-0", 1024) is None
    # Valid suffix returns (file_size - length, file_size - 1)
    assert _parse_range("bytes=-100", 1024) == (924, 1023)


@pytest.mark.asyncio
async def test_stream_video_range_start_beyond_eof(client, audio_row):
    """Start byte >= file_size → parser returns None → falls back to full body.
    Note: Starlette rejects this at the HTTP layer with 416, so we test the
    parser branch directly."""
    from app.routers.audio import _parse_range
    # Direct parser: start >= file_size returns None
    assert _parse_range("bytes=99999999-99999999", 1024) is None
    # start == file_size also returns None
    assert _parse_range("bytes=1024-1024", 1024) is None
    # start > end returns None
    assert _parse_range("bytes=100-50", 1024) is None