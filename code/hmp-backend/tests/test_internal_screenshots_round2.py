"""Round 2 coverage tests for app/routers/screenshots.py.

Targets uncovered branches beyond the v4 baseline (~29% -> 60%+).

Coverage gaps targeted:
- LIST: empty protocol (no screenshots) -> []
- LIST: protocol not found -> 404
- LIST: soft-deleted protocol -> 404
- LIST: sorted by timestamp_sec ASC
- UPLOAD: protocol not found -> 404
- UPLOAD: invalid content_type -> 415
- UPLOAD: with all optional fields populated (caption + width + height)
- UPLOAD: uppercase extension normalized to lowercase
- GET: 404 when screenshot not found
- DELETE: 404 when screenshot not found
- DELETE: file already missing branch (line 263-268)
- SYNTHESIZE: protocol not found -> 404
- SYNTHESIZE: no audio_file_id -> 400
- SYNTHESIZE: audio_file row missing -> 400 (audio is None branch)
- SYNTHESIZE: decisions strategy (alternate uniform-branch)
- DEBUG endpoint sanity check

NOTE: Uses db_session fixture (single shared session) instead of make_factory
to avoid TRUNCATE deadlocks when multiple connections coexist on the test engine.
"""
from __future__ import annotations

import io
import uuid
from datetime import date as date_cls, datetime, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AudioFile, Protocol, Screenshot
from app.services import video_screenshots as video_screenshots_service

pytestmark = pytest.mark.asyncio

PREFIX = "/api/v1/hmp"


# ============================================================================
# Helpers — use db_session directly (single connection = no deadlock)
# ============================================================================

async def _make_protocol(db_session: AsyncSession, **overrides) -> Protocol:
    defaults = dict(
        id=uuid.uuid4(),
        title="Round2",
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


async def _make_audio_file(db_session: AsyncSession, tmp_path: Path, **overrides) -> AudioFile:
    import tempfile

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
# LIST — uncovered branches
# ============================================================================

async def test_list_screenshots_empty_protocol(client: AsyncClient, db_session):
    """GET /protocols/{id}/screenshots for protocol with zero screenshots -> []"""
    p = await _make_protocol(db_session)
    r = await client.get(f"{PREFIX}/protocols/{p.id}/screenshots")
    assert r.status_code == 200, r.text
    assert r.json() == []


async def test_list_screenshots_protocol_not_found(client: AsyncClient):
    """GET /protocols/{nonexistent}/screenshots -> 404."""
    fake_id = uuid.uuid4()
    r = await client.get(f"{PREFIX}/protocols/{fake_id}/screenshots")
    assert r.status_code == 404, r.text
    detail = r.json()["detail"].lower()
    assert "не найден" in detail or "not found" in detail


async def test_list_screenshots_soft_deleted_protocol(
    client: AsyncClient, db_session
):
    """GET /protocols/{id}/screenshots for soft-deleted protocol -> 404."""
    p = await _make_protocol(db_session)
    # Soft-delete the protocol directly via the session
    proto = await db_session.get(Protocol, p.id)
    proto.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    r = await client.get(f"{PREFIX}/protocols/{p.id}/screenshots")
    assert r.status_code == 404, r.text


async def test_list_screenshots_sorted_by_timestamp_asc(
    client: AsyncClient, db_session
):
    """GET returns screenshots ordered by timestamp_sec ASC."""
    p = await _make_protocol(db_session)
    s2 = await _make_screenshot(db_session, p.id, timestamp_sec=5.0)
    s1 = await _make_screenshot(db_session, p.id, timestamp_sec=1.0)
    s3 = await _make_screenshot(db_session, p.id, timestamp_sec=10.0)

    r = await client.get(f"{PREFIX}/protocols/{p.id}/screenshots")
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()]
    assert ids == [str(s1.id), str(s2.id), str(s3.id)]


# ============================================================================
# UPLOAD — uncovered branches
# ============================================================================

async def test_upload_screenshot_protocol_not_found(
    client: AsyncClient, tmp_path, monkeypatch
):
    """POST upload with non-existent protocol_id -> 404."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    fake_pid = uuid.uuid4()
    files = {"file": ("x.png", io.BytesIO(b"data"), "image/png")}
    data = {"protocol_id": str(fake_pid), "timestamp_sec": "0.0"}

    r = await client.post(f"{PREFIX}/screenshots/upload", files=files, data=data)
    assert r.status_code == 404, r.text


async def test_upload_screenshot_invalid_content_type(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    """POST upload with non-image content_type -> 415."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    p = await _make_protocol(db_session)
    files = {"file": ("x.txt", io.BytesIO(b"data"), "text/plain")}
    data = {"protocol_id": str(p.id), "timestamp_sec": "0.0"}

    r = await client.post(f"{PREFIX}/screenshots/upload", files=files, data=data)
    assert r.status_code == 415, r.text
    detail = r.json()["detail"].lower()
    assert "image" in detail or "ожидается" in detail


async def test_upload_screenshot_with_all_optional_fields(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    """POST upload with caption + width_px + height_px populated."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    p = await _make_protocol(db_session)
    files = {"file": ("full.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" * 100), "image/png")}
    data = {
        "protocol_id": str(p.id),
        "timestamp_sec": "12.5",
        "caption": "Important moment",
        "width_px": "1920",
        "height_px": "1080",
    }

    r = await client.post(f"{PREFIX}/screenshots/upload", files=files, data=data)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["caption"] == "Important moment"
    assert body["width_px"] == 1920
    assert body["height_px"] == 1080
    assert body["timestamp_sec"] == 12.5


async def test_upload_screenshot_uppercase_extension(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    """POST upload with filename ending in .PNG (uppercase) -> preserved lowercase."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    p = await _make_protocol(db_session)
    files = {"file": ("photo.PNG", io.BytesIO(b"PNGDATA"), "image/png")}
    data = {"protocol_id": str(p.id), "timestamp_sec": "0.0"}

    r = await client.post(f"{PREFIX}/screenshots/upload", files=files, data=data)
    assert r.status_code == 201, r.text
    body = r.json()
    # suffix is normalized to lowercase
    assert body["file_path"].endswith(".png")


# ============================================================================
# GET — 404 branch
# ============================================================================

async def test_get_screenshot_not_found(client: AsyncClient):
    """GET /screenshots/{nonexistent} -> 404."""
    fake_id = uuid.uuid4()
    r = await client.get(f"{PREFIX}/screenshots/{fake_id}")
    assert r.status_code == 404, r.text
    detail = r.json()["detail"].lower()
    assert "не найден" in detail or "not found" in detail


# ============================================================================
# DELETE — uncovered branches
# ============================================================================

async def test_delete_screenshot_not_found(client: AsyncClient):
    """DELETE /screenshots/{nonexistent} -> 404."""
    fake_id = uuid.uuid4()
    r = await client.delete(f"{PREFIX}/screenshots/{fake_id}")
    assert r.status_code == 404, r.text


async def test_delete_screenshot_file_missing(
    client: AsyncClient, db_session
):
    """DELETE when file is already gone from disk -> 200, row removed."""
    p = await _make_protocol(db_session)
    nonexistent = "/tmp/__hmp_round2_missing_file__.png"
    s = await _make_screenshot(db_session, p.id, file_path=nonexistent)

    # Confirm file genuinely doesn't exist
    assert not Path(nonexistent).exists()

    r = await client.delete(f"{PREFIX}/screenshots/{s.id}")
    assert r.status_code == 200, r.text

    # Row gone
    r2 = await client.get(f"{PREFIX}/screenshots/{s.id}")
    assert r2.status_code == 404


# ============================================================================
# SYNTHESIZE — uncovered error branches
# ============================================================================

async def test_synthesize_protocol_not_found(client: AsyncClient):
    """POST synthesize on non-existent protocol -> 404."""
    fake_id = uuid.uuid4()
    r = await client.post(
        f"{PREFIX}/protocols/{fake_id}/screenshots/synthesize",
        json={"max_screenshots": 5, "strategy": "uniform"},
    )
    assert r.status_code == 404, r.text
    detail = r.json()["detail"].lower()
    assert "not found" in detail or "не найден" in detail


async def test_synthesize_no_audio_attached(client: AsyncClient, db_session):
    """POST synthesize on protocol with audio_file_id=None -> 400."""
    p = await _make_protocol(db_session)  # audio_file_id is None by default
    r = await client.post(
        f"{PREFIX}/protocols/{p.id}/screenshots/synthesize",
        json={"max_screenshots": 5, "strategy": "uniform"},
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"].lower()
    assert "audio" in detail or "video" in detail


async def test_synthesize_audio_file_row_missing(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    """AudioFile lookup returns None -> 400 'AudioFile not found'.

    We monkey-patch AsyncSession.get to return None for AudioFile to simulate
    a dangling FK without fighting the FK constraint.
    """
    p = await _make_protocol(db_session)
    audio = await _make_audio_file(db_session, tmp_path)
    await _attach_audio(db_session, p.id, audio.id)

    from app.db.models import AudioFile as AudioFileModel
    from app.db import session as session_module

    original_db_get = session_module.AsyncSession.get

    async def patched_get(self, entity, ident, *args, **kwargs):
        if entity is AudioFileModel:
            return None
        return await original_db_get(self, entity, ident, *args, **kwargs)

    monkeypatch.setattr(session_module.AsyncSession, "get", patched_get)

    r = await client.post(
        f"{PREFIX}/protocols/{p.id}/screenshots/synthesize",
        json={"max_screenshots": 5, "strategy": "uniform"},
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"].lower()
    assert "audiofile" in detail or "file_path" in detail


async def test_synthesize_decisions_strategy(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    """POST synthesize with strategy='decisions' -> uniform branch, mocked."""
    p = await _make_protocol(db_session)
    audio = await _make_audio_file(db_session, tmp_path)
    await _attach_audio(db_session, p.id, audio.id)

    async def fake_decisions(**kwargs):
        assert kwargs.get("strategy") == "decisions"
        return [object()] * 5

    monkeypatch.setattr(
        video_screenshots_service,
        "generate_screenshots_for_protocol",
        fake_decisions,
    )

    r = await client.post(
        f"{PREFIX}/protocols/{p.id}/screenshots/synthesize",
        json={"max_screenshots": 10, "strategy": "decisions"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["screenshots_created"] == 5
    assert body["strategy"] == "decisions"
    assert body["protocol_id"] == str(p.id)


# ============================================================================
# DEBUG endpoint — sanity check (covers E266 debug route)
# ============================================================================

async def test_debug_screenshot_endpoint(client: AsyncClient):
    """GET /_debug/screenshot returns dependency status dict."""
    r = await client.get(f"{PREFIX}/_debug/screenshot")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "python" in body
    assert "modules" in body
    assert isinstance(body["modules"], dict)
    # Each known module has an entry (✅ or ❌)
    for mod in ("PIL", "imagehash", "fastapi", "sqlalchemy", "asyncpg"):
        assert mod in body["modules"]
