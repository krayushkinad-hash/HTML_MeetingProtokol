"""Tests for app/routers/audio.py — round 2.

Targets branches NOT covered by test_internal_audio_round1.py / _v2.py / .py:

  * _parse_range — start > end (None), empty range header bytes= (None),
    start == file_size (None), whitespace-stripped header, garbage format
  * stream_audio_file — ?t redirect branch, no-mime fallback to _guess_mime
  * stream_source_by_protocol — protocol exists with audio_file_id, but
    AudioFile row was deleted (the second 404 branch)
  * get_audio_file — metadata field shape (US-001 happy with filename/source)

Goal: push coverage over 60% for app.routers.audio.

NOTE: Tests that hit the /audio-files/{id}/video endpoint with the `client`
fixture have flaky interaction with the conftest's per-function engine
disposal. We focus on pure unit tests for _parse_range and on routes that
don't trigger the same engine lifecycle issues.
"""
from __future__ import annotations

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


@pytest.fixture
async def audio_row_no_mime(db_session, fake_audio_file):
    """AudioFile row with mime_type=None — forces _guess_mime fallback path."""
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
# _parse_range — additional remaining edge branches (5 new tests)
# ===========================================================================


@pytest.mark.asyncio
async def test_parse_range_start_greater_than_end_returns_none():
    """bytes=100-50 → start > end → None (RFC 7233: invalid range)."""
    from app.routers.audio import _parse_range

    assert _parse_range("bytes=100-50", 1024) is None


@pytest.mark.asyncio
async def test_parse_range_empty_range_returns_none():
    """bytes= with neither start nor end → None (rejected)."""
    from app.routers.audio import _parse_range

    # No start, no end → fails the `if not start_str and not end_str` branch
    assert _parse_range("bytes=", 1024) is None


@pytest.mark.asyncio
async def test_parse_range_start_at_filesize_returns_none():
    """bytes=1024-1024 against 1024-byte file → start >= file_size → None."""
    from app.routers.audio import _parse_range

    # 1024 == file_size, the parser rejects (start >= file_size)
    assert _parse_range("bytes=1024-1024", 1024) is None


@pytest.mark.asyncio
async def test_parse_range_with_whitespace_stripped():
    """Leading/trailing whitespace around header is stripped before parsing."""
    from app.routers.audio import _parse_range

    # The parser calls range_header.strip() so surrounding whitespace is OK
    assert _parse_range("  bytes=0-99  ", 1024) == (0, 99)


@pytest.mark.asyncio
async def test_parse_range_garbage_returns_none():
    """Completely malformed header (not bytes=N-N) → None."""
    from app.routers.audio import _parse_range

    # Regex doesn't match → None
    assert _parse_range("chunks=0-99", 1024) is None
    assert _parse_range("bytes=abc-def", 1024) is None


# ===========================================================================
# _guess_mime — direct unit test
# ===========================================================================


@pytest.mark.asyncio
async def test_guess_mime_octet_stream_for_unknown_ext():
    """Unknown extension → application/octet-stream fallback."""
    from app.routers.audio import _guess_mime

    # Unknown extension → fallback
    assert _guess_mime(Path("/tmp/strange.unknownext12345")) == "application/octet-stream"


# ===========================================================================
# GET /audio-files/{id} — verify full metadata payload shape
# ===========================================================================


@pytest.mark.asyncio
async def test_get_audio_file_returns_full_metadata(client, audio_row):
    """GET /audio-files/{id} returns AudioFileResponse with all fields."""
    r = await client.get(f"/api/v1/hmp/audio-files/{audio_row.id}")
    assert r.status_code == 200
    body = r.json()
    # Verify the schema field set matches what AudioFileResponse exposes
    assert body["id"] == str(audio_row.id)
    assert body["filename"] == "clip.webm"
    assert body["extension"] == "webm"
    assert body["mime_type"] == "video/webm"
    assert body["source"] == "local"
    assert "created_at" in body
    assert body["size_bytes"] > 0


# ===========================================================================
# GET /media/protocols/{id}/source.{ext} — second 404 branch
# ===========================================================================


@pytest.mark.asyncio
async def test_stream_source_protocol_with_audio_file_id_but_audio_deleted(
    client, db_session
):
    """Protocol has audio_file_id pointing to a non-existent AudioFile → 404.

    Exercises the branch:
      audio_result = ...scalar_one_or_none()
      if not audio_file: raise HTTPException(404)

    We create both Protocol and AudioFile (FK), then DELETE AudioFile row
    so the Protocol's audio_file_id becomes a dangling reference.
    """
    from app.db.models import AudioFile, Protocol, ProtocolStatus

    # Create matching AudioFile first so FK is satisfied at INSERT time
    af = AudioFile(
        id=uuid.uuid4(),
        file_path="/tmp/dummy.webm",
        filename="dummy.webm",
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
        title="Stale Audio Ref",
        status=ProtocolStatus.READY,
        date=datetime.now(timezone.utc).date(),
        audio_file_id=af.id,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(proto)
    await db_session.commit()
    await db_session.refresh(proto)

    # Now delete AudioFile row → Protocol.audio_file_id becomes dangling
    await db_session.delete(af)
    await db_session.commit()

    r = await client.get(f"/api/v1/hmp/media/protocols/{proto.id}/source.webm")
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"].lower()


# ===========================================================================
# GET /audio-files/{id}/video — happy paths (file present, no special cases)
# ===========================================================================


@pytest.mark.asyncio
async def test_stream_video_full_file_no_params(client, audio_row):
    """No Range header, no t-param → 200 full file with Accept-Ranges/Cache-Control.

    Exercises the final 'Full file' branch in stream_audio_file.
    """
    r = await client.get(f"/api/v1/hmp/audio-files/{audio_row.id}/video")
    assert r.status_code == 200
    # Final branch adds both headers
    assert r.headers.get("accept-ranges") == "bytes"
    assert r.headers.get("cache-control") == "public, max-age=3600"


@pytest.mark.asyncio
async def test_stream_video_no_mime_full_file(client, audio_row_no_mime):
    """AudioFile with mime_type=None + no range → full FileResponse with guessed mime."""
    r = await client.get(f"/api/v1/hmp/audio-files/{audio_row_no_mime.id}/video")
    assert r.status_code == 200
    # mimetypes.guess_type('clip.webm') → 'video/webm'
    assert r.headers.get("content-type", "").startswith("video/webm")


@pytest.mark.asyncio
async def test_stream_video_t_param_redirects_to_static(client, audio_row):
    """?t=<sec> with no Range header → 302 redirect to static mount.

    Even when the file exists locally, the endpoint redirects to /media
    rather than computing a byte offset (no known bitrate).
    """
    r = await client.get(
        f"/api/v1/hmp/audio-files/{audio_row.id}/video",
        params={"t": 1.5},
        follow_redirects=False,
    )
    assert r.status_code == 302
    location = r.headers.get("location", "")
    assert f"/media/protocols/{audio_row.id}/source.webm" in location


@pytest.mark.asyncio
async def test_stream_video_no_mime_with_range_partial(client, audio_row_no_mime):
    """Range request + mime_type=None → 206 with guessed mime + correct slice."""
    p = Path(audio_row_no_mime.file_path)
    r = await client.get(
        f"/api/v1/hmp/audio-files/{audio_row_no_mime.id}/video",
        headers={"Range": "bytes=0-9"},
    )
    assert r.status_code == 206
    assert r.headers.get("content-type", "").startswith("video/webm")
    assert r.headers["content-length"] == "10"
    assert r.headers["content-range"] == f"bytes 0-9/{p.stat().st_size}"