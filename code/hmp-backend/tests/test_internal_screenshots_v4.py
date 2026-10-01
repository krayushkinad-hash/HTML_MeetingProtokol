"""V4 coverage test for app/routers/screenshots.py — targets 60%+.

Builds on test_internal_screenshots_v3.py (which already hits ~48%).

New branches targeted (from 48% → 60%+):
- synthesize change_detection strategy success (line 339-346)
- synthesize uniform strategy success (line 348-355)
- synthesize audio_file row missing → 400 (line 321-323, audio is None branch)
- synthesize video file not on disk → 404 (line 326-327)
- synthesize 'important' strategy (alternate strategy branch)
- delete screenshot — file present + unlink raises OSError (line 254-262)
- upload — total_bytes=0 → file_size_kb=None branch (line 188)
- upload — minimal form (no caption/width/height defaults)
- upload — no extension in filename → default .png applied (line 151)
- list — filters by protocol_id (other protocol's screenshots not returned)
- upload — preserves original filename suffix (.jpg instead of .png)
"""
from __future__ import annotations

import io
import tempfile
import uuid
from datetime import date as date_cls
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.db.models import AudioFile, Protocol, Screenshot
from app.services import video_screenshots as video_screenshots_service

pytestmark = pytest.mark.asyncio

PREFIX = "/api/v1/hmp"


# ============================================================================
# Helpers — make_factory pattern + set_audio_file_id helper
# ============================================================================

@pytest.fixture
async def make_factory(db_engine):
    """Async factory that creates objects in their own session."""
    sm = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def _make(model_cls, refresh: bool = True, **kwargs):
        async with sm() as s:
            obj = model_cls(**kwargs)
            s.add(obj)
            await s.commit()
            if refresh:
                try:
                    await s.refresh(obj)
                except Exception:
                    pass
            return obj

    return _make


async def _make_protocol(make_factory, **overrides) -> Protocol:
    defaults = dict(
        id=uuid.uuid4(),
        title="Screenshots V4",
        date=date_cls(2026, 1, 1),
        status="loaded",
        language="ru",
    )
    defaults.update(overrides)
    return await make_factory(Protocol, **defaults)


async def _make_screenshot(make_factory, protocol_id: uuid.UUID, **overrides) -> Screenshot:
    defaults = dict(
        id=uuid.uuid4(),
        protocol_id=protocol_id,
        file_path="/tmp/fake_screenshot.png",
        timestamp_sec=0.0,
    )
    defaults.update(overrides)
    return await make_factory(Screenshot, **defaults)


async def _make_audio_file(make_factory, **overrides) -> AudioFile:
    """AudioFile pointing to a real on-disk file so synthesize can find it."""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.write(b"FAKE_VIDEO_BYTES")
    tmp.close()
    overrides.setdefault("file_path", tmp.name)
    overrides.setdefault("filename", "fake.mp4")
    overrides.setdefault("extension", "mp4")
    overrides.setdefault("size_bytes", 16)
    overrides.setdefault("mime_type", "video/mp4")
    return await make_factory(AudioFile, **overrides)


async def _attach_audio(make_factory, db_engine, protocol_id, audio_id):
    """Update protocol.audio_file_id using the test DB engine directly."""
    sm = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        proto = await s.get(Protocol, protocol_id)
        proto.audio_file_id = audio_id
        await s.commit()


# ============================================================================
# DELETE — OSError on unlink branch (line 254-262)
# ============================================================================

async def test_delete_screenshot_unlink_oserror(
    client: AsyncClient, make_factory, monkeypatch, tmp_path
):
    """DELETE screenshot where unlink raises OSError → still 200, row removed."""
    p = await _make_protocol(make_factory)

    real_file = tmp_path / "screenshot.png"
    real_file.write_bytes(b"FAKE_PNG")
    s = await _make_screenshot(make_factory, p.id, file_path=str(real_file))

    original_unlink = Path.unlink

    def patched_unlink(self, *args, **kwargs):
        if str(self) == str(real_file):
            raise OSError("simulated unlink failure")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", patched_unlink)

    r = await client.delete(f"{PREFIX}/screenshots/{s.id}")
    assert r.status_code == 200, r.text

    # DB row removed despite the OSError
    r2 = await client.get(f"{PREFIX}/screenshots/{s.id}")
    assert r2.status_code == 404


# ============================================================================
# UPLOAD — total_bytes=0 → file_size_kb=None (line 188)
# ============================================================================

async def test_upload_screenshot_empty_file(
    client: AsyncClient, make_factory, tmp_path, monkeypatch
):
    """POST upload with EMPTY file → 201, file_size_kb=None (else branch)."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    p = await _make_protocol(make_factory)
    files = {"file": ("empty.png", io.BytesIO(b""), "image/png")}
    data = {"protocol_id": str(p.id), "timestamp_sec": "0.0"}

    r = await client.post(f"{PREFIX}/screenshots/upload", files=files, data=data)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["file_size_kb"] is None


# ============================================================================
# UPLOAD — minimal form (no optional fields)
# ============================================================================

async def test_upload_screenshot_minimal_form(
    client: AsyncClient, make_factory, tmp_path, monkeypatch
):
    """POST upload with only required fields → 201, optional fields default None."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    p = await _make_protocol(make_factory)
    files = {"file": ("shot.jpg", io.BytesIO(b"\xff\xd8\xff\xe0" * 10), "image/jpeg")}
    data = {"protocol_id": str(p.id), "timestamp_sec": "5.0"}

    r = await client.post(f"{PREFIX}/screenshots/upload", files=files, data=data)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["caption"] is None
    assert body["width_px"] is None
    assert body["height_px"] is None
    # jpeg suffix preserved from filename
    assert body["file_path"].endswith(".jpg")


# ============================================================================
# UPLOAD — file with no extension uses default .png (line 151)
# ============================================================================

async def test_upload_screenshot_no_extension_uses_png(
    client: AsyncClient, make_factory, tmp_path, monkeypatch
):
    """POST upload with filename lacking extension → file written with .png."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    p = await _make_protocol(make_factory)
    files = {"file": ("noext", io.BytesIO(b"PNGDATA"), "image/png")}
    data = {"protocol_id": str(p.id), "timestamp_sec": "0.0"}

    r = await client.post(f"{PREFIX}/screenshots/upload", files=files, data=data)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["file_path"].endswith(".png")


# ============================================================================
# UPLOAD — preserves original filename suffix (.jpg not forced to .png)
# ============================================================================

async def test_upload_screenshot_uses_filename_suffix(
    client: AsyncClient, make_factory, tmp_path, monkeypatch
):
    """POST upload uses original filename suffix when present (not just .png)."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    p = await _make_protocol(make_factory)
    files = {"file": ("photo.jpg", io.BytesIO(b"\xff\xd8\xff\xe0" * 50), "image/jpeg")}
    data = {"protocol_id": str(p.id), "timestamp_sec": "0.1"}

    r = await client.post(f"{PREFIX}/screenshots/upload", files=files, data=data)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["file_path"].endswith(".jpg")
    assert Path(body["file_path"]).exists()


# ============================================================================
# LIST — filtering by protocol_id
# ============================================================================

async def test_list_screenshots_filters_by_protocol(
    client: AsyncClient, make_factory
):
    """GET /protocols/{id}/screenshots returns only that protocol's screenshots."""
    p1 = await _make_protocol(make_factory, title="P1")
    p2 = await _make_protocol(make_factory, title="P2")

    s1a = await _make_screenshot(make_factory, p1.id, timestamp_sec=1.0)
    s1b = await _make_screenshot(make_factory, p1.id, timestamp_sec=2.0)
    s2 = await _make_screenshot(make_factory, p2.id, timestamp_sec=1.5)

    r = await client.get(f"{PREFIX}/protocols/{p1.id}/screenshots")
    assert r.status_code == 200, r.text
    ids = {item["id"] for item in r.json()}
    assert ids == {str(s1a.id), str(s1b.id)}
    assert str(s2.id) not in ids

    r2 = await client.get(f"{PREFIX}/protocols/{p2.id}/screenshots")
    assert r2.status_code == 200
    assert {item["id"] for item in r2.json()} == {str(s2.id)}


# ============================================================================
# SYNTHESIZE — uniform strategy success (line 348-355)
# ============================================================================

async def test_synthesize_uniform_strategy_success(
    client: AsyncClient, make_factory, db_engine, monkeypatch
):
    """POST synthesize with uniform strategy → 200 with mocked count."""
    p = await _make_protocol(make_factory)
    audio = await _make_audio_file(make_factory)
    await _attach_audio(make_factory, db_engine, p.id, audio.id)

    async def fake_uniform(**kwargs):
        return [object()] * 3

    monkeypatch.setattr(
        video_screenshots_service,
        "generate_screenshots_for_protocol",
        fake_uniform,
    )

    r = await client.post(
        f"{PREFIX}/protocols/{p.id}/screenshots/synthesize",
        json={"max_screenshots": 5, "strategy": "uniform"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["screenshots_created"] == 3
    assert body["strategy"] == "uniform"
    assert body["protocol_id"] == str(p.id)


# ============================================================================
# SYNTHESIZE — change_detection strategy success (line 339-346)
# ============================================================================

async def test_synthesize_change_detection_strategy_success(
    client: AsyncClient, make_factory, db_engine, monkeypatch
):
    """POST synthesize with strategy=change_detection → 200 with mocked count."""
    p = await _make_protocol(make_factory)
    audio = await _make_audio_file(make_factory)
    await _attach_audio(make_factory, db_engine, p.id, audio.id)

    async def fake_change_detection(**kwargs):
        return [object()] * 4

    monkeypatch.setattr(
        video_screenshots_service,
        "generate_screenshots_change_detection",
        fake_change_detection,
    )

    r = await client.post(
        f"{PREFIX}/protocols/{p.id}/screenshots/synthesize",
        json={"max_screenshots": 10, "strategy": "change_detection"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["screenshots_created"] == 4
    assert body["strategy"] == "change_detection"


# ============================================================================
# SYNTHESIZE — 'important' strategy (alternate uniform-branch strategy)
# ============================================================================

async def test_synthesize_important_strategy(
    client: AsyncClient, make_factory, db_engine, monkeypatch
):
    """POST synthesize with strategy='important' → falls into uniform branch."""
    p = await _make_protocol(make_factory)
    audio = await _make_audio_file(make_factory)
    await _attach_audio(make_factory, db_engine, p.id, audio.id)

    async def fake_important(**kwargs):
        assert kwargs.get("strategy") == "important"
        return [object()] * 2

    monkeypatch.setattr(
        video_screenshots_service,
        "generate_screenshots_for_protocol",
        fake_important,
    )

    r = await client.post(
        f"{PREFIX}/protocols/{p.id}/screenshots/synthesize",
        json={"max_screenshots": 7, "strategy": "important"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["screenshots_created"] == 2
    assert body["strategy"] == "important"


# ============================================================================
# SYNTHESIZE — audio_file has no file_path → 400 (line 321-323)
# ============================================================================

async def test_synthesize_audio_file_no_file_path(
    client: AsyncClient, make_factory, db_engine
):
    """AudioFile.file_path is empty → 400 'AudioFile not found or no file_path'."""
    p = await _make_protocol(make_factory)
    audio = await _make_audio_file(make_factory, file_path="")
    await _attach_audio(make_factory, db_engine, p.id, audio.id)

    r = await client.post(
        f"{PREFIX}/protocols/{p.id}/screenshots/synthesize",
        json={"max_screenshots": 5, "strategy": "uniform"},
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "AudioFile" in detail or "file_path" in detail


# ============================================================================
# SYNTHESIZE — video file not on disk → 404 (line 326-327)
# ============================================================================

async def test_synthesize_video_file_not_on_disk(
    client: AsyncClient, make_factory, db_engine
):
    """AudioFile.file_path set to non-existent path → 404 'Video file not found'."""
    p = await _make_protocol(make_factory)
    audio = await _make_audio_file(make_factory, file_path="/tmp/__hmp_no_such_video__.mp4")
    await _attach_audio(make_factory, db_engine, p.id, audio.id)

    r = await client.post(
        f"{PREFIX}/protocols/{p.id}/screenshots/synthesize",
        json={"max_screenshots": 5, "strategy": "uniform"},
    )
    assert r.status_code == 404, r.text
    detail = r.json()["detail"]
    assert "not found" in detail.lower() or "disk" in detail.lower()


# ============================================================================
# GET /screenshots/{id} — returns single object, not list
# ============================================================================

async def test_get_screenshot_returns_single_dict(
    client: AsyncClient, make_factory
):
    """GET /screenshots/{id} returns dict (single item, not array)."""
    p = await _make_protocol(make_factory)
    s = await _make_screenshot(make_factory, p.id, caption="iso")

    r = await client.get(f"{PREFIX}/screenshots/{s.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, dict)
    assert body["caption"] == "iso"
    # response fields
    for k in ("id", "protocol_id", "file_path", "timestamp_sec", "created_at"):
        assert k in body