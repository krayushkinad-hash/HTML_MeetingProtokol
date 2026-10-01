"""V3 coverage test for app/routers/screenshots.py — targets 50%+.

Endpoints covered (incremental beyond test_internal_screenshots.py):
- GET    /protocols/{protocol_id}/screenshots — 404/empty/order
- GET    /screenshots/{id}                   — 404
- POST   /protocols/{protocol_id}/screenshots/synthesize — 404/400/422 + uniform/change_detection
- DELETE /screenshots/{id}                    — 404, missing-file path
- GET    /_debug/screenshot                  — module check

Uses `make_factory` pattern from test_internal_protocols_v3.py.
"""
from __future__ import annotations

import io
import uuid
from datetime import date as date_cls
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.db.models import AudioFile, Protocol, Screenshot

pytestmark = pytest.mark.asyncio

PREFIX = "/api/v1/hmp"


# ============================================================================
# Helpers — make_factory pattern
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
        title="Screenshots V3",
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


# ============================================================================
# GET /protocols/{protocol_id}/screenshots — list
# ============================================================================

async def test_list_screenshots_empty(
    client: AsyncClient, make_factory
):
    """GET screenshots for protocol with no screenshots → 200 + []."""
    p = await _make_protocol(make_factory)

    r = await client.get(f"{PREFIX}/protocols/{p.id}/screenshots")
    assert r.status_code == 200, r.text
    assert r.json() == []


async def test_list_screenshots_returns_sorted_by_timestamp(
    client: AsyncClient, make_factory
):
    """GET screenshots returns ordered by timestamp_sec ASC."""
    p = await _make_protocol(make_factory)

    # Insert in non-sorted order
    s3 = await _make_screenshot(make_factory, p.id, timestamp_sec=30.0)
    s1 = await _make_screenshot(make_factory, p.id, timestamp_sec=10.0)
    s2 = await _make_screenshot(make_factory, p.id, timestamp_sec=20.0)

    r = await client.get(f"{PREFIX}/protocols/{p.id}/screenshots")
    assert r.status_code == 200, r.text
    ids = [item["id"] for item in r.json()]
    assert ids == [str(s1.id), str(s2.id), str(s3.id)]


async def test_list_screenshots_protocol_not_found(client: AsyncClient):
    """GET screenshots for non-existent protocol → 404."""
    r = await client.get(f"{PREFIX}/protocols/{uuid.uuid4()}/screenshots")
    assert r.status_code == 404
    assert "Протокол" in r.json()["detail"]


async def test_list_screenshots_invalid_uuid_422(client: AsyncClient):
    """GET screenshots with malformed UUID → 422."""
    r = await client.get(f"{PREFIX}/protocols/not-a-uuid/screenshots")
    assert r.status_code == 422


async def test_list_screenshots_excludes_soft_deleted_protocol(
    client: AsyncClient, make_factory, db_engine
):
    """GET screenshots for soft-deleted protocol → 404."""
    from datetime import datetime, timezone

    p = await _make_protocol(make_factory)

    sm = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        proto = await s.get(Protocol, p.id)
        proto.deleted_at = datetime.now(timezone.utc)
        await s.commit()

    r = await client.get(f"{PREFIX}/protocols/{p.id}/screenshots")
    assert r.status_code == 404


# ============================================================================
# GET /screenshots/{id}
# ============================================================================

async def test_get_screenshot_success(
    client: AsyncClient, make_factory
):
    """GET screenshot/{id} → 200 with metadata."""
    p = await _make_protocol(make_factory)
    s = await _make_screenshot(
        make_factory, p.id,
        caption="hello",
        width_px=800,
        height_px=600,
        file_size_kb=42,
    )

    r = await client.get(f"{PREFIX}/screenshots/{s.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == str(s.id)
    assert body["caption"] == "hello"
    assert body["width_px"] == 800
    assert body["height_px"] == 600
    assert body["file_size_kb"] == 42
    assert body["protocol_id"] == str(p.id)


async def test_get_screenshot_not_found(client: AsyncClient):
    """GET screenshot with random UUID → 404."""
    r = await client.get(f"{PREFIX}/screenshots/{uuid.uuid4()}")
    assert r.status_code == 404
    assert "Скриншот" in r.json()["detail"]


async def test_get_screenshot_invalid_uuid_422(client: AsyncClient):
    """GET screenshot with bad UUID → 422."""
    r = await client.get(f"{PREFIX}/screenshots/not-a-uuid")
    assert r.status_code == 422


# ============================================================================
# DELETE /screenshots/{id}
# ============================================================================

async def test_delete_screenshot_not_found(client: AsyncClient):
    """DELETE non-existent screenshot → 404."""
    r = await client.delete(f"{PREFIX}/screenshots/{uuid.uuid4()}")
    assert r.status_code == 404
    assert "Скриншот" in r.json()["detail"]


async def test_delete_screenshot_invalid_uuid_422(client: AsyncClient):
    """DELETE with malformed UUID → 422."""
    r = await client.delete(f"{PREFIX}/screenshots/abc")
    assert r.status_code == 422


async def test_delete_screenshot_with_missing_file(
    client: AsyncClient, make_factory
):
    """DELETE screenshot whose file_path does not exist on disk → still 200.

    Covers the `else: logger.warning("screenshot_file_missing")` branch.
    """
    p = await _make_protocol(make_factory)
    # file_path points to a non-existent file
    s = await _make_screenshot(
        make_factory, p.id,
        file_path="/tmp/this/path/never/exists.png",
    )

    r = await client.delete(f"{PREFIX}/screenshots/{s.id}")
    assert r.status_code == 200, r.text

    # Verify DB row removed
    r2 = await client.get(f"{PREFIX}/screenshots/{s.id}")
    assert r2.status_code == 404


# ============================================================================
# POST /protocols/{protocol_id}/screenshots/synthesize
# ============================================================================

async def test_synthesize_protocol_not_found(client: AsyncClient):
    """POST synthesize with non-existent protocol → 404."""
    r = await client.post(
        f"{PREFIX}/protocols/{uuid.uuid4()}/screenshots/synthesize",
        json={"max_screenshots": 5, "strategy": "uniform"},
    )
    assert r.status_code == 404


async def test_synthesize_protocol_no_audio(client: AsyncClient, make_factory):
    """POST synthesize when protocol has no audio_file_id → 400."""
    p = await _make_protocol(make_factory)  # no audio_file_id set

    r = await client.post(
        f"{PREFIX}/protocols/{p.id}/screenshots/synthesize",
        json={"max_screenshots": 5, "strategy": "uniform"},
    )
    assert r.status_code == 400
    assert "audio" in r.json()["detail"].lower()


async def test_synthesize_max_screenshots_validation(
    client: AsyncClient, make_factory
):
    """POST synthesize with max_screenshots=0 → 422 (ge=1 violated)."""
    p = await _make_protocol(make_factory)

    r = await client.post(
        f"{PREFIX}/protocols/{p.id}/screenshots/synthesize",
        json={"max_screenshots": 0, "strategy": "uniform"},
    )
    assert r.status_code == 422


async def test_synthesize_max_screenshots_upper_bound(
    client: AsyncClient, make_factory
):
    """POST synthesize with max_screenshots=100 → 422 (le=50 violated)."""
    p = await _make_protocol(make_factory)

    r = await client.post(
        f"{PREFIX}/protocols/{p.id}/screenshots/synthesize",
        json={"max_screenshots": 100, "strategy": "uniform"},
    )
    assert r.status_code == 422


# ============================================================================
# GET /_debug/screenshot
# ============================================================================

async def test_debug_screenshot_endpoint(client: AsyncClient):
    """GET /_debug/screenshot → 200 with module status dict."""
    r = await client.get(f"{PREFIX}/_debug/screenshot")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "python" in body
    assert "modules" in body
    assert "PIL" in body["modules"]
    assert "fastapi" in body["modules"]
    # ffmpeg and test_extract keys always present
    assert "ffmpeg" in body
    assert "test_extract" in body


# ============================================================================
# POST /screenshots/upload — additional paths (415, success)
# ============================================================================

async def test_upload_screenshot_protocol_not_found(
    client: AsyncClient, tmp_path, monkeypatch
):
    """POST upload with non-existent protocol_id → 404."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    fake_uuid = uuid.uuid4()
    files = {"file": ("a.png", io.BytesIO(b"PNGDATA"), "image/png")}
    data = {"protocol_id": str(fake_uuid), "timestamp_sec": "1.0"}

    r = await client.post(f"{PREFIX}/screenshots/upload", files=files, data=data)
    assert r.status_code == 404


async def test_upload_screenshot_wrong_content_type(
    client: AsyncClient, make_factory, tmp_path, monkeypatch
):
    """POST upload with non-image content_type → 415."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    p = await _make_protocol(make_factory)
    files = {"file": ("a.txt", io.BytesIO(b"data"), "text/plain")}
    data = {"protocol_id": str(p.id), "timestamp_sec": "0.5"}

    r = await client.post(f"{PREFIX}/screenshots/upload", files=files, data=data)
    assert r.status_code == 415
    assert "image/" in r.json()["detail"]


async def test_upload_screenshot_success(
    client: AsyncClient, make_factory, tmp_path, monkeypatch
):
    """POST upload with valid PNG → 201 + DB row + file on disk."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    p = await _make_protocol(make_factory)
    payload = b"\x89PNG_FAKE_BYTES" * 200  # ~3.6 KB
    files = {
        "file": (
            "shot.png",
            io.BytesIO(payload),
            "image/png",
        )
    }
    data = {
        "protocol_id": str(p.id),
        "timestamp_sec": "12.5",
        "caption": "test cap",
        "width_px": "640",
        "height_px": "480",
    }

    r = await client.post(f"{PREFIX}/screenshots/upload", files=files, data=data)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["protocol_id"] == str(p.id)
    assert body["caption"] == "test cap"
    assert body["width_px"] == 640
    assert body["height_px"] == 480
    assert body["file_size_kb"] is not None and body["file_size_kb"] >= 1
    # File should exist on disk
    assert Path(body["file_path"]).exists()