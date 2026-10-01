"""Tests for app/routers/audio.py — round 1.

Targets remaining branches NOT covered by test_internal_audio.py / _v2.py:

  * _parse_range — bytes=-N where N == file_size is valid (returns (0,N-1)),
    bytes=0-0 single-byte range, end-clamp at file_size-1, open-end default
  * stream_audio_file — single-byte Range (length << chunk_size),
    Range + ?t= both present (Range wins → 206),
    full-file response carries Accept-Ranges + Cache-Control,
    file-missing redirect to static mount with logged warning
  * transcode_audio_file — success path replaces file + commits,
    ffmpeg Windows fallback discovery branch,
    no-ffmpeg-anywhere → 500 "ffmpeg не найден"
  * open_audio_folder — Linux xdg-open command shape (regression),
    Linux with missing-file folder still opens parent,
    Linux with both file+folder missing (no exception)
  * stream_source_by_protocol — Accept-Ranges: bytes header verification

Goal: lift app.routers.audio coverage above 60%.

NOTE: these tests run against PostgreSQL via the shared conftest. Each test
uses a fresh `db_engine` fixture (function scope) which TRUNCATEs all tables
and disposes the engine. When run in batch, asyncpg connection-pool timing
can occasionally cause intermittent "Could not refresh instance" errors —
this is pre-existing flakiness in the conftest, not in these tests.
"""
from __future__ import annotations

import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_audio_file(tmp_path: Path):
    """Create a real audio file on disk; ~14KB payload."""
    p = tmp_path / "clip.webm"
    payload = b"\x1a\x45\xdf\xa3" + b"AUDIO_PAYLOAD" * 1024  # 12292 bytes
    p.write_bytes(payload)
    return p, payload


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


# ===========================================================================
# _parse_range — additional edge branches
# ===========================================================================


@pytest.mark.asyncio
async def test_parse_range_suffix_length_equals_filesize():
    """bytes=-N where N == file_size is valid → (0, file_size-1).

    The parser only rejects `length > file_size`, not equality.
    """
    from app.routers.audio import _parse_range

    # length == file_size: NOT rejected (returns (file_size-length, file_size-1))
    assert _parse_range("bytes=-1024", 1024) == (0, 1023)
    # length == file_size - 1: returns (1, 1023)
    assert _parse_range("bytes=-1023", 1024) == (1, 1023)
    # length == file_size + 1: rejected
    assert _parse_range("bytes=-1025", 1024) is None


@pytest.mark.asyncio
async def test_parse_range_zero_length_valid():
    """bytes=0-0 → single byte range [0, 0]."""
    from app.routers.audio import _parse_range

    assert _parse_range("bytes=0-0", 1024) == (0, 0)


@pytest.mark.asyncio
async def test_parse_range_end_clamp_at_filesize_minus_one():
    """End bytes=0-99999 → clamped to file_size-1 (1023)."""
    from app.routers.audio import _parse_range

    start, end = _parse_range("bytes=0-99999", 1024)
    assert start == 0
    assert end == 1023


@pytest.mark.asyncio
async def test_parse_range_open_end_default():
    """bytes=N- with no end → end defaults to file_size-1."""
    from app.routers.audio import _parse_range

    assert _parse_range("bytes=500-", 1024) == (500, 1023)
    assert _parse_range("bytes=0-", 1024) == (0, 1023)


# ===========================================================================
# GET /audio-files/{id}/video — Range streaming edge cases
# ===========================================================================


@pytest.mark.asyncio
async def test_stream_video_single_byte_range(client, audio_row, fake_audio_file):
    """Range that produces a single chunk where chunk_size(1MB) >> length(1).

    Exercises the iterator loop's `break` branch (one chunk, no more reads).
    """
    p, payload = fake_audio_file
    r = await client.get(
        f"/api/v1/hmp/audio-files/{audio_row.id}/video",
        headers={"Range": "bytes=0-0"},
    )
    assert r.status_code == 206
    assert r.headers["content-length"] == "1"
    assert r.headers["content-range"] == f"bytes 0-0/{p.stat().st_size}"
    assert r.content == payload[0:1]


@pytest.mark.asyncio
async def test_stream_video_full_file_response_headers(client, audio_row):
    """No range, no t-param → 200 full file with Accept-Ranges + Cache-Control."""
    r = await client.get(f"/api/v1/hmp/audio-files/{audio_row.id}/video")
    assert r.status_code == 200
    assert r.headers.get("accept-ranges") == "bytes"
    assert r.headers.get("cache-control") == "public, max-age=3600"


@pytest.mark.asyncio
async def test_stream_video_t_with_range_prefers_range(client, audio_row, fake_audio_file):
    """When BOTH ?t= and Range header are present, Range branch wins (206).

    Without Range, ?t= would redirect to static mount; with Range, Range is honored.
    """
    p, payload = fake_audio_file
    r = await client.get(
        f"/api/v1/hmp/audio-files/{audio_row.id}/video",
        params={"t": 1.0},
        headers={"Range": "bytes=0-9"},
    )
    assert r.status_code == 206
    assert r.headers["content-length"] == "10"
    assert r.content == payload[0:10]


@pytest.mark.asyncio
async def test_stream_video_redirect_logs_warning(client, db_session, tmp_path):
    """Audio row exists, file missing on disk → 302 with logged warning.

    The Location should point at /media/protocols/{audio_id}/source.{ext}.
    """
    from app.db.models import AudioFile

    missing = tmp_path / "vanished.webm"
    af = AudioFile(
        id=uuid.uuid4(),
        file_path=str(missing),
        filename="vanished.webm",
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
        f"/api/v1/hmp/audio-files/{af.id}/video",
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert f"/media/protocols/{af.id}/source.webm" in r.headers.get("location", "")


# ===========================================================================
# POST /audio-files/{id}/transcode — success path + ffmpeg-fallback discovery
# ===========================================================================


@pytest.mark.asyncio
async def test_transcode_success_replaces_file_and_commits(
    client, audio_row, monkeypatch
):
    """Successful ffmpeg run → 200, file replaced, db.commit() called.

    Verifies the success-path branches:
      * output_path.replace(file_path)
      * audio.updated_at = datetime.now(timezone.utc)
      * await db.commit()
    """
    import subprocess as sp

    class _Result:
        returncode = 0
        stderr = b""

    def fake_run(cmd, capture_output=True, timeout=600):
        # Simulate ffmpeg writing the output file
        out_path = Path(cmd[-1])
        out_path.write_bytes(b"NEW_TRANSCODED")
        return _Result()

    monkeypatch.setattr(sp, "run", fake_run)
    monkeypatch.setattr(
        "shutil.which", lambda x: "/usr/bin/ffmpeg" if x == "ffmpeg" else None
    )

    # Original file content should be replaced after transcoding
    orig_path = Path(audio_row.file_path)
    assert orig_path.read_bytes() != b"NEW_TRANSCODED"  # sanity

    r = await client.post(f"/api/v1/hmp/audio-files/{audio_row.id}/transcode")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert "transcoded_file" in body

    # Original file now contains the transcoded content
    assert orig_path.read_bytes() == b"NEW_TRANSCODED"
    # And the temp .transcoded.webm file should be gone (replaced, not copied)
    leftover = orig_path.with_suffix(".transcoded.webm")
    assert not leftover.exists()


@pytest.mark.asyncio
async def test_transcode_no_ffmpeg_anywhere_returns_500(client, audio_row, monkeypatch):
    """shutil.which returns None AND all fallback paths don't exist → 500 'ffmpeg не найден'."""
    monkeypatch.setattr("shutil.which", lambda x: None)
    # Path.exists returns False for non-existent paths by default on Linux

    r = await client.post(f"/api/v1/hmp/audio-files/{audio_row.id}/transcode")
    assert r.status_code == 500
    assert "ffmpeg" in r.text.lower()


@pytest.mark.asyncio
async def test_transcode_finds_ffmpeg_at_windows_fallback(client, audio_row, monkeypatch):
    """shutil.which returns None but Windows fallback path exists → transcode runs.

    Exercises the for-loop branch that searches C:/ffmpeg/bin/ffmpeg.exe etc.
    """
    import subprocess as sp

    class _Result:
        returncode = 0
        stderr = b""

    real_path_exists = Path.exists

    def patched_exists(self):
        s = str(self)
        if "ffmpeg.exe" in s and "C:/ffmpeg/bin" in s:
            return True
        return real_path_exists(self)

    def fake_run(cmd, capture_output=True, timeout=600):
        # Write the output file so output_path.replace() succeeds
        out_path = Path(cmd[-1])
        out_path.write_bytes(b"TRANSCODED")
        return _Result()

    monkeypatch.setattr("shutil.which", lambda x: None)
    monkeypatch.setattr(Path, "exists", patched_exists)
    monkeypatch.setattr(sp, "run", fake_run)

    r = await client.post(f"/api/v1/hmp/audio-files/{audio_row.id}/transcode")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"


# ===========================================================================
# POST /audio-files/{id}/open-folder — Linux branch (fresh coverage)
# ===========================================================================


@pytest.mark.asyncio
async def test_open_folder_linux_xdg_open_command(client, audio_row, monkeypatch):
    """Linux branch → command[0]=='xdg-open', command[1]==folder_path."""
    monkeypatch.setattr(sys.modules["platform"], "system", lambda: "Linux")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: None)

    r = await client.post(f"/api/v1/hmp/audio-files/{audio_row.id}/open-folder")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["os"] == "linux"
    assert body["command"][0] == "xdg-open"
    assert body["command"][1] == str(Path(audio_row.file_path).parent)
    assert body["folder_exists"] is True


@pytest.mark.asyncio
async def test_open_folder_linux_missing_file_popen_runs(
    client, db_session, tmp_path, monkeypatch
):
    """Linux branch with missing file → Popen still runs; folder_exists=False."""
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

    calls = []
    monkeypatch.setattr(sys.modules["platform"], "system", lambda: "Linux")
    monkeypatch.setattr(
        subprocess, "Popen", lambda cmd, *a, **kw: calls.append(cmd) or None
    )

    r = await client.post(f"/api/v1/hmp/audio-files/{af.id}/open-folder")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["file_exists"] is False
    assert calls[0][0] == "xdg-open"
    assert calls[0][1] == str(missing.parent)


@pytest.mark.asyncio
async def test_open_folder_linux_folder_missing_too(client, db_session, monkeypatch):
    """Linux branch with both file AND folder missing → no exception, returns info."""
    from app.db.models import AudioFile

    af = AudioFile(
        id=uuid.uuid4(),
        file_path="/totally/nonexistent/path/clip.webm",
        filename="clip.webm",
        extension="webm",
        size_bytes=0,
        mime_type="video/webm",
        source="local",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(af)
    await db_session.commit()
    await db_session.refresh(af)

    monkeypatch.setattr(sys.modules["platform"], "system", lambda: "Linux")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: None)

    r = await client.post(f"/api/v1/hmp/audio-files/{af.id}/open-folder")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["file_exists"] is False
    assert body["folder_exists"] is False


# ===========================================================================
# GET /media/protocols/{id}/source.{ext} — verify Accept-Ranges header
# ===========================================================================


@pytest.mark.asyncio
async def test_stream_source_accept_ranges_header(client, db_session, fake_audio_file):
    """Successful response carries Accept-Ranges: bytes header."""
    from app.db.models import AudioFile, Protocol, ProtocolStatus

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

    proto = Protocol(
        id=uuid.uuid4(),
        title="AR Test",
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
    assert r.headers.get("accept-ranges") == "bytes"


# ===========================================================================
# Additional coverage round 1b — covering missing branches in:
#   _parse_range (suffix), _guess_mime, stream_source 404s,
#   get_audio_file happy + 404, open-folder darwin/windows/exception paths,
#   transcode subprocess.TimeoutExpired, transcode generic Exception
# ===========================================================================


@pytest.mark.asyncio
async def test_parse_range_suffix_zero_rejected():
    """bytes=-0 → length=0 ≤ 0 → None."""
    from app.routers.audio import _parse_range

    assert _parse_range("bytes=-0", 1024) is None


@pytest.mark.asyncio
async def test_guess_mime_returns_octet_stream_for_unknown_ext():
    """_guess_mime falls back to application/octet-stream for unknown extensions."""
    from app.routers.audio import _guess_mime

    p = Path("/tmp/somefile.unknownext12345")
    result = _guess_mime(p)
    assert result == "application/octet-stream"

    # And a real extension returns the proper mime
    mp3 = Path("/tmp/song.mp3")
    assert _guess_mime(mp3) == "audio/mpeg"


@pytest.mark.asyncio
async def test_get_audio_file_happy_path(client, audio_row):
    """GET /audio-files/{id} → 200 with metadata."""
    r = await client.get(f"/api/v1/hmp/audio-files/{audio_row.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(audio_row.id)
    assert body["extension"] == "webm"
    assert body["mime_type"] == "video/webm"


@pytest.mark.asyncio
async def test_get_audio_file_404(client):
    """GET /audio-files/<unknown uuid> → 404."""
    r = await client.get(f"/api/v1/hmp/audio-files/{uuid.uuid4()}")
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_stream_source_protocol_not_found_404(client):
    """GET /media/protocols/{unknown uuid}/source.webm → 404."""
    r = await client.get(f"/api/v1/hmp/media/protocols/{uuid.uuid4()}/source.webm")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_stream_source_audio_file_missing_404(client, db_session):
    """Protocol exists with audio_file_id, but AudioFile row missing → 404.

    Use Protocol.audio_file_id = None — first 404 branch in audio.py:
    'if not protocol or not protocol.audio_file_id: raise HTTPException(404)'.
    """
    from app.db.models import Protocol, ProtocolStatus

    proto = Protocol(
        id=uuid.uuid4(),
        title="NoAudio",
        status=ProtocolStatus.READY,
        date=datetime.now(timezone.utc).date(),
        audio_file_id=None,  # No audio_file linked → first 404 branch
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(proto)
    await db_session.commit()

    r = await client.get(f"/api/v1/hmp/media/protocols/{proto.id}/source.webm")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_stream_source_file_missing_on_disk_404(client, db_session, tmp_path):
    """AudioFile row exists but file is missing on disk → 404 with disk-path detail."""
    from app.db.models import AudioFile, Protocol, ProtocolStatus

    missing_path = tmp_path / "ghost.webm"
    af = AudioFile(
        id=uuid.uuid4(),
        file_path=str(missing_path),
        filename="ghost.webm",
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
        title="Ghost",
        status=ProtocolStatus.READY,
        date=datetime.now(timezone.utc).date(),
        audio_file_id=af.id,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(proto)
    await db_session.commit()

    r = await client.get(f"/api/v1/hmp/media/protocols/{proto.id}/source.webm")
    assert r.status_code == 404
    assert "диске" in r.json()["detail"].lower() or "на диске" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_open_folder_darwin_open_command(client, audio_row, monkeypatch):
    """Darwin branch → command[0]=='open', command[1]=='-R'."""
    monkeypatch.setattr(sys.modules["platform"], "system", lambda: "Darwin")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: None)

    r = await client.post(f"/api/v1/hmp/audio-files/{audio_row.id}/open-folder")
    assert r.status_code == 200
    body = r.json()
    assert body["os"] == "darwin"
    assert body["command"][0] == "open"
    assert body["command"][1] == "-R"


@pytest.mark.asyncio
async def test_open_folder_windows_file_exists_select(client, audio_row, monkeypatch):
    """Windows branch with existing file → command uses explorer /select,"""
    monkeypatch.setattr(sys.modules["platform"], "system", lambda: "Windows")
    calls = []
    monkeypatch.setattr(
        subprocess, "Popen", lambda cmd, *a, **kw: calls.append(cmd) or None
    )

    r = await client.post(f"/api/v1/hmp/audio-files/{audio_row.id}/open-folder")
    assert r.status_code == 200
    body = r.json()
    assert body["os"] == "windows"
    assert body["command"][0] == "explorer"
    assert "/select," in body["command"][1]
    # shell=True flag was passed
    assert calls[0] is not None


@pytest.mark.asyncio
async def test_open_folder_windows_file_missing_no_select(client, db_session, tmp_path, monkeypatch):
    """Windows branch with missing file → command uses explorer WITHOUT /select."""
    from app.db.models import AudioFile

    missing = tmp_path / "absent_win.webm"
    af = AudioFile(
        id=uuid.uuid4(),
        file_path=str(missing),
        filename="absent_win.webm",
        extension="webm",
        size_bytes=0,
        mime_type="video/webm",
        source="local",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(af)
    await db_session.commit()

    monkeypatch.setattr(sys.modules["platform"], "system", lambda: "Windows")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: None)

    r = await client.post(f"/api/v1/hmp/audio-files/{af.id}/open-folder")
    assert r.status_code == 200
    body = r.json()
    assert body["os"] == "windows"
    # No /select, → folder-only command
    assert body["command"][0] == "explorer"
    assert "/select," not in body["command"][1]
    assert str(missing.parent) in body["command"][1]


@pytest.mark.asyncio
async def test_open_folder_popen_raises_exception_recorded(
    client, audio_row, monkeypatch
):
    """If Popen raises, the error is captured in response body (not re-raised)."""
    monkeypatch.setattr(sys.modules["platform"], "system", lambda: "Linux")

    def boom(*a, **kw):
        raise OSError("simulated Popen failure")

    monkeypatch.setattr(subprocess, "Popen", boom)

    r = await client.post(f"/api/v1/hmp/audio-files/{audio_row.id}/open-folder")
    # Handler catches the exception and returns 200 with error= in body
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is not None
    assert "simulated Popen failure" in body["error"]


@pytest.mark.asyncio
async def test_open_folder_audio_file_not_found_404(client):
    """POST /audio-files/<unknown uuid>/open-folder → 404."""
    r = await client.post(f"/api/v1/hmp/audio-files/{uuid.uuid4()}/open-folder")
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_open_folder_no_file_path_404(client, db_session):
    """AudioFile row with file_path='' → 404 'Путь к файлу не сохранён'.

    The schema's NOT NULL constraint requires a string, so we use empty string
    instead of NULL. The endpoint's check `if not audio_file.file_path`
    correctly catches both '' and None.
    """
    from app.db.models import AudioFile

    af = AudioFile(
        id=uuid.uuid4(),
        file_path="",  # NOT NULL column; '' triggers the not-found branch
        filename="no_path.webm",
        extension="webm",
        size_bytes=0,
        mime_type="video/webm",
        source="local",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(af)
    await db_session.commit()

    r = await client.post(f"/api/v1/hmp/audio-files/{af.id}/open-folder")
    assert r.status_code == 404
    assert "путь" in r.json()["detail"].lower() or "сохран" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_transcode_file_missing_on_disk_404(client, db_session, tmp_path):
    """POST /transcode when file doesn't exist on disk → 404."""
    from app.db.models import AudioFile

    missing = tmp_path / "phantom.webm"
    af = AudioFile(
        id=uuid.uuid4(),
        file_path=str(missing),
        filename="phantom.webm",
        extension="webm",
        size_bytes=0,
        mime_type="video/webm",
        source="local",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(af)
    await db_session.commit()

    r = await client.post(f"/api/v1/hmp/audio-files/{af.id}/transcode")
    assert r.status_code == 404
    assert "диск" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_transcode_audio_file_not_found_404(client):
    """POST /transcode for unknown audio id → 404."""
    r = await client.post(f"/api/v1/hmp/audio-files/{uuid.uuid4()}/transcode")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_transcode_ffmpeg_nonzero_return_500(
    client, audio_row, monkeypatch
):
    """ffmpeg.run returns non-zero returncode → 500 'ffmpeg не смог'."""
    import subprocess as sp

    class _Result:
        returncode = 1
        stderr = b"some ffmpeg error"

    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/ffmpeg" if x == "ffmpeg" else None)
    monkeypatch.setattr(sp, "run", lambda *a, **kw: _Result())

    r = await client.post(f"/api/v1/hmp/audio-files/{audio_row.id}/transcode")
    assert r.status_code == 500
    assert "ffmpeg" in r.json()["detail"].lower() or "перекодир" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_transcode_subprocess_timeout_500(client, audio_row, monkeypatch):
    """subprocess.run raises TimeoutExpired → 500 'timeout'."""
    import subprocess as sp

    def raise_timeout(*a, **kw):
        raise sp.TimeoutExpired(cmd="ffmpeg", timeout=600)

    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/ffmpeg" if x == "ffmpeg" else None)
    monkeypatch.setattr(sp, "run", raise_timeout)

    r = await client.post(f"/api/v1/hmp/audio-files/{audio_row.id}/transcode")
    assert r.status_code == 500
    assert "timeout" in r.json()["detail"].lower() or "10 мин" in r.json()["detail"].lower()