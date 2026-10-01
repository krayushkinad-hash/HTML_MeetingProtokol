"""Round 3 coverage tests for app/routers/screenshots.py.

Builds on round2 (which covers the bulk of error branches). Round3 targets
remaining gaps to push coverage from ~60% to 70%+:

- UPLOAD happy path (multipart, real file on disk, DB row created) — covers
  the full file-stream loop, default suffix `.png` branch, default fields
  path, and the file_exists/`unlink` happy-path branches.
- UPLOAD with no content_type (browser omission branch)
- UPLOAD with `.jpg` extension (alternate suffix branch, lowercase normalization)
- GET happy path with metadata — verifies _to_response covers all 9 fields
  including created_at ISO string.
- DELETE happy path — file actually removed from disk, row gone from DB.
- SYNTHESIZE strategy='important' (uniform-branch alternate)
- SYNTHESIZE strategy='change_detection' (calls alternate service)
- SYNTHESIZE audio.file_path is None branch (line 322)
- SYNTHESIZE video_path doesn't exist on disk branch (line 326)
- SYNTHESIZE service returns [] (defensive, screenshots_created=0)
- LIST with screenshots containing full metadata (round-trip field map)
- LIST with screenshots present but on non-existent protocol — sanity check

NOTE: db_session fixture is shared across the test (no factory) to avoid
TRUNCATE deadlocks when the FastAPI client opens its own session concurrently.
"""
from __future__ import annotations

import io
import os
import tempfile
import uuid
from datetime import date as date_cls
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AudioFile, Protocol, Screenshot
from app.services import video_screenshots as video_screenshots_service

pytestmark = pytest.mark.asyncio

PREFIX = "/api/v1/hmp"


# ============================================================================
# Helpers
# ============================================================================

async def _make_protocol(db_session: AsyncSession, **overrides) -> Protocol:
    defaults = dict(
        id=uuid.uuid4(),
        title="Round3",
        date=date_cls(2026, 1, 1),
        status="loaded",
        language="ru",
    )
    defaults.update(overrides)
    p = Protocol(**defaults)
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


async def _make_screenshot(
    db_session: AsyncSession, protocol_id: uuid.UUID, **overrides
) -> Screenshot:
    defaults = dict(
        id=uuid.uuid4(),
        protocol_id=protocol_id,
        file_path="/tmp/fake.png",
        timestamp_sec=0.0,
    )
    defaults.update(overrides)
    s = Screenshot(**defaults)
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)
    return s


async def _make_audio_file(
    db_session: AsyncSession, tmp_path: Path, **overrides
) -> AudioFile:
    """Create a real on-disk file so video_path.exists() is True."""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False, dir=str(tmp_path))
    tmp.write(b"FAKE")
    tmp.close()

    defaults = dict(
        id=uuid.uuid4(),
        file_path=tmp.name,
        filename="fake.mp4",
        extension="mp4",
        size_bytes=4,
        mime_type="video/mp4",
    )
    defaults.update(overrides)
    a = AudioFile(**defaults)
    db_session.add(a)
    await db_session.commit()
    await db_session.refresh(a)
    return a


async def _attach_audio(db_session: AsyncSession, protocol_id, audio_id):
    proto = await db_session.get(Protocol, protocol_id)
    proto.audio_file_id = audio_id
    await db_session.commit()


# ============================================================================
# UPLOAD — happy paths
# ============================================================================

async def test_upload_screenshot_happy_path_minimal(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    """POST /screenshots/upload with only required fields succeeds,
    writes the file to disk, and persists a Screenshot row."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    p = await _make_protocol(db_session)
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 1024
    files = {"file": ("screenshot.png", io.BytesIO(png_bytes), "image/png")}
    data = {"protocol_id": str(p.id), "timestamp_sec": "0.0"}

    r = await client.post(f"{PREFIX}/screenshots/upload", files=files, data=data)
    assert r.status_code == 201, r.text
    body = r.json()

    # Response fields populated
    assert uuid.UUID(body["id"])
    assert uuid.UUID(body["protocol_id"]) == p.id
    assert body["timestamp_sec"] == 0.0
    assert body["caption"] is None
    assert body["width_px"] is None
    assert body["height_px"] is None
    assert body["file_size_kb"] == 1  # 1024 bytes -> 1 KB
    assert body["file_path"].endswith(".png")

    # File actually written to disk under protocols_path / protocol_id / screenshots
    expected_dir = tmp_path / str(p.id) / "screenshots"
    assert expected_dir.is_dir(), f"expected dir {expected_dir} missing"
    saved_files = list(expected_dir.glob("*.png"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == png_bytes

    # DB row created
    screenshot = await db_session.get(Screenshot, uuid.UUID(body["id"]))
    assert screenshot is not None
    assert screenshot.protocol_id == p.id


async def test_upload_screenshot_no_content_type(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    """When UploadFile.content_type is None, validation is skipped (the
    `if file.content_type and ...` guard). File should still be saved."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    p = await _make_protocol(db_session)
    # No content_type passed (simulates older browser / curl)
    files = {"file": ("shot.png", io.BytesIO(b"\x89PNG\r\n\x1a\nDATA"), None)}
    data = {"protocol_id": str(p.id), "timestamp_sec": "3.14"}

    r = await client.post(f"{PREFIX}/screenshots/upload", files=files, data=data)
    assert r.status_code == 201, r.text
    assert r.json()["timestamp_sec"] == 3.14


async def test_upload_screenshot_jpg_extension_normalized(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    """Upload with .JPG extension -> suffix lowered to .jpg; defaults branch
    since filename has a suffix (so the `or ".png"` fallback is unused)."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    p = await _make_protocol(db_session)
    files = {"file": ("photo.JPG", io.BytesIO(b"\xff\xd8\xff\xe0JPEGDATA"), "image/jpeg")}
    data = {"protocol_id": str(p.id), "timestamp_sec": "0.0"}

    r = await client.post(f"{PREFIX}/screenshots/upload", files=files, data=data)
    assert r.status_code == 201, r.text
    assert r.json()["file_path"].endswith(".jpg")


async def test_upload_screenshot_large_file_chunked_write(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    """Upload a multi-chunk file (>chunk_size MB) to exercise the streaming
    write loop end-to-end and verify file_size_kb math.

    We force chunk_size to 1 MB by monkeypatching settings.video_range_chunk_size_mb
    and writing 3 MB of payload.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))
    monkeypatch.setattr(settings, "video_range_chunk_size_mb", 1)

    p = await _make_protocol(db_session)
    # 3 MB of zeros -> 3072 KB reported
    payload = b"\x00" * (3 * 1024 * 1024)
    files = {"file": ("big.bin", io.BytesIO(payload), "application/octet-stream")}
    data = {"protocol_id": str(p.id), "timestamp_sec": "0.0"}

    # Note: content_type 'application/octet-stream' doesn't start with 'image/'
    # so we rely on the no-content-type-equivalent path. Use image/png instead.
    files = {"file": ("big.png", io.BytesIO(payload), "image/png")}

    r = await client.post(f"{PREFIX}/screenshots/upload", files=files, data=data)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["file_size_kb"] == 3 * 1024

    # File actually written and matches payload
    saved_path = Path(body["file_path"])
    assert saved_path.exists()
    assert saved_path.stat().st_size == len(payload)


# ============================================================================
# GET — happy path with metadata
# ============================================================================

async def test_get_screenshot_with_full_metadata(
    client: AsyncClient, db_session
):
    """GET /screenshots/{id} returns all fields from the ORM model,
    including the ISO-8601 created_at string."""
    p = await _make_protocol(db_session)
    s = await _make_screenshot(
        db_session,
        p.id,
        timestamp_sec=42.5,
        width_px=1920,
        height_px=1080,
        file_size_kb=128,
        caption="Quarterly review",
    )

    r = await client.get(f"{PREFIX}/screenshots/{s.id}")
    assert r.status_code == 200, r.text
    body = r.json()

    # _to_response field map
    assert body["id"] == str(s.id)
    assert body["protocol_id"] == str(p.id)
    assert body["file_path"] == "/tmp/fake.png"
    assert body["timestamp_sec"] == 42.5
    assert body["width_px"] == 1920
    assert body["height_px"] == 1080
    assert body["file_size_kb"] == 128
    assert body["caption"] == "Quarterly review"
    # created_at is an ISO-8601 string (non-empty)
    assert isinstance(body["created_at"], str)
    assert body["created_at"]  # non-empty


# ============================================================================
# DELETE — happy path
# ============================================================================

async def test_delete_screenshot_happy_path(
    client: AsyncClient, db_session, tmp_path
):
    """DELETE /screenshots/{id} removes both the file from disk and the DB row."""
    # Create a real file on disk and a screenshot row pointing to it
    real_file = tmp_path / "to_delete.png"
    real_file.write_bytes(b"\x89PNG\r\n\x1a\nDELETE_ME")
    assert real_file.exists()

    p = await _make_protocol(db_session)
    s = await _make_screenshot(
        db_session, p.id, file_path=str(real_file), timestamp_sec=1.0
    )

    r = await client.delete(f"{PREFIX}/screenshots/{s.id}")
    assert r.status_code == 200, r.text
    # Response body is None / empty
    assert r.json() in (None, "")

    # File removed from disk
    assert not real_file.exists()

    # Row removed from DB
    r2 = await client.get(f"{PREFIX}/screenshots/{s.id}")
    assert r2.status_code == 404


# ============================================================================
# SYNTHESIZE — strategy dispatch and edge branches
# ============================================================================

async def test_synthesize_important_strategy(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    """POST synthesize with strategy='important' takes the uniform-branch
    (generate_screenshots_for_protocol) with strategy forwarded."""
    p = await _make_protocol(db_session)
    audio = await _make_audio_file(db_session, tmp_path)
    await _attach_audio(db_session, p.id, audio.id)

    async def fake_important(**kwargs):
        assert kwargs.get("strategy") == "important"
        return [object()] * 7

    monkeypatch.setattr(
        video_screenshots_service,
        "generate_screenshots_for_protocol",
        fake_important,
    )

    r = await client.post(
        f"{PREFIX}/protocols/{p.id}/screenshots/synthesize",
        json={"max_screenshots": 15, "strategy": "important"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["screenshots_created"] == 7
    assert body["strategy"] == "important"
    assert body["protocol_id"] == str(p.id)


async def test_synthesize_change_detection_strategy(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    """POST synthesize with strategy='change_detection' takes the
    alternate branch (generate_screenshots_change_detection)."""
    p = await _make_protocol(db_session)
    audio = await _make_audio_file(db_session, tmp_path)
    await _attach_audio(db_session, p.id, audio.id)

    async def fake_change_detection(**kwargs):
        # The router forwards: protocol_id, video_path, output_dir,
        # max_screenshots, db
        assert "video_path" in kwargs
        assert "output_dir" in kwargs
        assert kwargs["max_screenshots"] == 4
        return [object()] * 3

    monkeypatch.setattr(
        video_screenshots_service,
        "generate_screenshots_change_detection",
        fake_change_detection,
    )

    r = await client.post(
        f"{PREFIX}/protocols/{p.id}/screenshots/synthesize",
        json={"max_screenshots": 4, "strategy": "change_detection"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["screenshots_created"] == 3
    assert body["strategy"] == "change_detection"


async def test_synthesize_audio_file_path_none(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    """AudioFile row exists but file_path is None -> 400 'no file_path'.

    We monkey-patch AsyncSession.get for AudioFile to return a stub
    AudioFile with file_path=None (the column is NOT NULL in DB so we
    can't store it directly).
    """
    p = await _make_protocol(db_session)
    audio = await _make_audio_file(db_session, tmp_path)
    await _attach_audio(db_session, p.id, audio.id)

    from app.db.models import AudioFile as AudioFileModel
    from app.db import session as session_module

    original_db_get = session_module.AsyncSession.get

    class _FakeAudio:
        def __init__(self, real_id):
            self.id = real_id
            self.file_path = None

    async def patched_get(self, entity, ident, *args, **kwargs):
        if entity is AudioFileModel:
            return _FakeAudio(ident)
        return await original_db_get(self, entity, ident, *args, **kwargs)

    monkeypatch.setattr(session_module.AsyncSession, "get", patched_get)

    r = await client.post(
        f"{PREFIX}/protocols/{p.id}/screenshots/synthesize",
        json={"max_screenshots": 5, "strategy": "uniform"},
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"].lower()
    assert "file_path" in detail or "audiofile" in detail


async def test_synthesize_video_file_missing_on_disk(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    """AudioFile.row exists and has file_path, but the file is not on disk
    -> 404 'Video file not found on disk'."""
    p = await _make_protocol(db_session)

    # Create AudioFile pointing to a non-existent path (bypass _make_audio_file)
    audio = AudioFile(
        id=uuid.uuid4(),
        file_path="/tmp/__definitely_missing_video__" + uuid.uuid4().hex + ".mp4",
        filename="missing.mp4",
        extension="mp4",
        size_bytes=0,
        mime_type="video/mp4",
    )
    db_session.add(audio)
    await db_session.commit()
    await db_session.refresh(audio)
    await _attach_audio(db_session, p.id, audio.id)

    r = await client.post(
        f"{PREFIX}/protocols/{p.id}/screenshots/synthesize",
        json={"max_screenshots": 5, "strategy": "uniform"},
    )
    assert r.status_code == 404, r.text
    detail = r.json()["detail"].lower()
    assert "video" in detail or "not found" in detail


async def test_synthesize_service_returns_empty_list(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    """Service is called but returns [] -> 200 with screenshots_created=0.
    Exercises the `len(screenshots)` -> 0 branch."""
    p = await _make_protocol(db_session)
    audio = await _make_audio_file(db_session, tmp_path)
    await _attach_audio(db_session, p.id, audio.id)

    async def fake_empty(**kwargs):
        return []

    monkeypatch.setattr(
        video_screenshots_service,
        "generate_screenshots_for_protocol",
        fake_empty,
    )

    r = await client.post(
        f"{PREFIX}/protocols/{p.id}/screenshots/synthesize",
        json={"max_screenshots": 5, "strategy": "uniform"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["screenshots_created"] == 0
    assert body["strategy"] == "uniform"


# ============================================================================
# LIST — round-trip with screenshots containing metadata
# ============================================================================

async def test_list_screenshots_returns_full_metadata(
    client: AsyncClient, db_session
):
    """LIST returns each screenshot with all _to_response fields populated,
    verifying the response schema field map for the list path."""
    p = await _make_protocol(db_session)
    s1 = await _make_screenshot(
        db_session,
        p.id,
        timestamp_sec=10.0,
        width_px=800,
        height_px=600,
        file_size_kb=42,
        caption="first",
    )
    s2 = await _make_screenshot(
        db_session,
        p.id,
        timestamp_sec=20.0,
        caption="second",
    )

    r = await client.get(f"{PREFIX}/protocols/{p.id}/screenshots")
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 2

    # Ordered ASC by timestamp_sec
    assert items[0]["id"] == str(s1.id)
    assert items[1]["id"] == str(s2.id)

    # First item has all metadata
    first = items[0]
    assert first["width_px"] == 800
    assert first["height_px"] == 600
    assert first["file_size_kb"] == 42
    assert first["caption"] == "first"
    assert isinstance(first["created_at"], str)

    # Second item has only the caption populated (no width/height/size)
    second = items[1]
    assert second["caption"] == "second"
    assert second["width_px"] is None
    assert second["height_px"] is None
    assert second["file_size_kb"] is None


# ============================================================================
# DIRECT HANDLER CALLS — bypass ASGITransport tracking anomaly
#
# The pytest-cov + ASGITransport + Depends(get_db) combination fails to
# register most handler-body line executions on this project (documented in
# the cov-tracking-anomaly-fastapi-lazy-imports skill). Calling the handler
# functions directly on the same AsyncSession runs the body on the test's
# own greenlet, which the tracer records properly.
# ============================================================================

async def test_direct_synthesize_change_detection_calls_alt_service(
    db_session, tmp_path, monkeypatch
):
    """Direct call to synthesize_screenshots with strategy='change_detection'
    exercises the entire body (path validation, service dispatch, response
    build) on the test greenlet — the tracer records every line."""
    from app.routers import screenshots as screenshots_router
    from app.services import video_screenshots as vs

    p = await _make_protocol(db_session)
    audio = await _make_audio_file(db_session, tmp_path)
    await _attach_audio(db_session, p.id, audio.id)

    async def fake_change(**kwargs):
        return [object()] * 4

    monkeypatch.setattr(vs, "generate_screenshots_change_detection", fake_change)

    result = await screenshots_router.synthesize_screenshots(
        protocol_id=p.id,
        req=screenshots_router.SynthesizeRequest(
            max_screenshots=8, strategy="change_detection"
        ),
        db=db_session,
    )
    assert result.screenshots_created == 4
    assert result.strategy == "change_detection"
    assert result.protocol_id == str(p.id)


async def test_direct_synthesize_uniform_branch(
    db_session, tmp_path, monkeypatch
):
    """Direct call to synthesize_screenshots with strategy='uniform'
    exercises the generate_screenshots_for_protocol path with strategy
    forwarded correctly."""
    from app.routers import screenshots as screenshots_router
    from app.services import video_screenshots as vs

    p = await _make_protocol(db_session)
    audio = await _make_audio_file(db_session, tmp_path)
    await _attach_audio(db_session, p.id, audio.id)

    captured = {}

    async def fake_uniform(**kwargs):
        captured["strategy"] = kwargs.get("strategy")
        captured["max_screenshots"] = kwargs.get("max_screenshots")
        captured["video_path"] = kwargs.get("video_path")
        captured["output_dir"] = kwargs.get("output_dir")
        return [object()] * 6

    monkeypatch.setattr(vs, "generate_screenshots_for_protocol", fake_uniform)

    result = await screenshots_router.synthesize_screenshots(
        protocol_id=p.id,
        req=screenshots_router.SynthesizeRequest(
            max_screenshots=12, strategy="uniform"
        ),
        db=db_session,
    )
    assert result.screenshots_created == 6
    assert captured["strategy"] == "uniform"
    assert captured["max_screenshots"] == 12
    # output_dir is video_path.parent / "screenshots"
    assert captured["output_dir"].name == "screenshots"
    # video_path is the audio file's actual file_path
    assert captured["video_path"] == Path(audio.file_path)


async def test_direct_upload_screenshot_happy_path(
    db_session, tmp_path, monkeypatch
):
    """Direct call to upload_screenshot exercises the full body: protocol
    check, content_type guard, mkdir, chunked write, DB insert, refresh."""
    from io import BytesIO

    from app.routers import screenshots as screenshots_router
    from app.core.config import settings

    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    p = await _make_protocol(db_session)

    class _FakeUpload:
        def __init__(self, data, filename, content_type):
            self._data = data
            self.filename = filename
            self.content_type = content_type

        async def read(self, n=-1):
            if n < 0 or n >= len(self._data):
                chunk, self._data = self._data, b""
                return chunk
            chunk, self._data = self._data[:n], self._data[n:]
            return chunk

    fake_file = _FakeUpload(b"\x89PNG\r\n\x1a\nDIRECT_CALL", "shot.png", "image/png")

    result = await screenshots_router.upload_screenshot(
        file=fake_file,
        protocol_id=p.id,
        timestamp_sec=7.5,
        caption="direct",
        width_px=640,
        height_px=480,
        db=db_session,
    )
    assert result.timestamp_sec == 7.5
    assert result.caption == "direct"
    assert result.width_px == 640
    assert result.height_px == 480
    assert Path(result.file_path).exists()


async def test_direct_delete_screenshot_file_unlink(
    db_session, tmp_path
):
    """Direct call to delete_screenshot exercises the file-exists / unlink
    branch end-to-end (roundtrip through Path.exists + Path.unlink)."""
    from app.routers import screenshots as screenshots_router

    real_file = tmp_path / "to_unlink.png"
    real_file.write_bytes(b"\x89PNG\r\n\x1a\n")
    p = await _make_protocol(db_session)
    s = await _make_screenshot(db_session, p.id, file_path=str(real_file))
    assert real_file.exists()

    await screenshots_router.delete_screenshot(screenshot_id=s.id, db=db_session)

    assert not real_file.exists()
    gone = await db_session.get(Screenshot, s.id)
    assert gone is None


async def test_direct_list_screenshots_sorted(
    db_session
):
    """Direct call to list_screenshots exercises the full handler body."""
    from app.routers import screenshots as screenshots_router

    p = await _make_protocol(db_session)
    s2 = await _make_screenshot(db_session, p.id, timestamp_sec=2.0)
    s1 = await _make_screenshot(db_session, p.id, timestamp_sec=1.0)
    s3 = await _make_screenshot(db_session, p.id, timestamp_sec=3.0)

    items = await screenshots_router.list_screenshots(protocol_id=p.id, db=db_session)
    assert [i.id for i in items] == [s1.id, s2.id, s3.id]


async def test_direct_get_screenshot_with_metadata(
    db_session
):
    """Direct call to get_screenshot returns the full _to_response mapping."""
    from app.routers import screenshots as screenshots_router

    p = await _make_protocol(db_session)
    s = await _make_screenshot(
        db_session,
        p.id,
        timestamp_sec=99.9,
        width_px=1024,
        height_px=768,
        file_size_kb=256,
        caption="direct-get",
    )

    resp = await screenshots_router.get_screenshot(screenshot_id=s.id, db=db_session)
    assert resp.id == s.id
    assert resp.protocol_id == p.id
    assert resp.timestamp_sec == 99.9
    assert resp.width_px == 1024
    assert resp.height_px == 768
    assert resp.file_size_kb == 256
    assert resp.caption == "direct-get"
