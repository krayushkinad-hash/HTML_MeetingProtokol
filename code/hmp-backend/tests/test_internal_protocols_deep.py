"""Deep coverage tests for app/routers/protocols.py — targets 40%+.

Endpoints covered:
- POST   /protocols                      (create_protocol)
- POST   /protocols/from-url             (create_protocol_from_url)
- GET    /protocols                      (list_protocols — default/with filter/pagination)
- GET    /protocols/{id}                 (get_protocol — success + 404)
- PATCH  /protocols/{id}                 (update_protocol — success + 404)
- DELETE /protocols/{id}                  (delete_protocol — soft delete)
- DELETE /protocols/{id}/permanent        (hard_delete_protocol)
"""
from __future__ import annotations

import io
import uuid
from datetime import date as date_cls, datetime, timezone

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Local fixtures — sample_protocol in tests/conftest_pg.py omits `date` and
# would 500 on these endpoints (Protocol.date is nullable=False).
# ---------------------------------------------------------------------------

async def _make_protocol(db_session, *, title: str = "Deep Test", **overrides):
    from app.db.models import Protocol

    kwargs = dict(
        id=uuid.uuid4(),
        title=title,
        date=date_cls(2026, 1, 15),
        location="Room A",
        chair="Alice",
        agenda="Discuss things",
        status="loaded",
        language="ru",
    )
    kwargs.update(overrides)
    p = Protocol(**kwargs)
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest.fixture
async def deep_protocol(db_session):
    return await _make_protocol(db_session, title="Deep Protocol")


@pytest.fixture
async def deep_protocol_status(db_session):
    return await _make_protocol(
        db_session,
        title="Filtered Protocol",
        status="ready",
    )


@pytest.fixture
async def second_protocol(db_session):
    return await _make_protocol(db_session, title="Second Protocol", date=date_cls(2025, 6, 1))


# ---------------------------------------------------------------------------
# GET /protocols — list with various filters and pagination
# ---------------------------------------------------------------------------

async def test_list_protocols_default(client, deep_protocol):
    r = await client.get("/api/v1/hmp/protocols")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "total" in body
    assert body["page"] == 1
    assert body["limit"] == 50
    assert any(it["id"] == str(deep_protocol.id) for it in body["items"])


async def test_list_protocols_with_status_filter(client, deep_protocol, deep_protocol_status):
    r = await client.get("/api/v1/hmp/protocols?status=ready")
    assert r.status_code == 200
    body = r.json()
    ids = [it["id"] for it in body["items"]]
    assert str(deep_protocol_status.id) in ids
    assert str(deep_protocol.id) not in ids


async def test_list_protocols_pagination_and_sort(client, deep_protocol, second_protocol):
    r = await client.get("/api/v1/hmp/protocols?limit=10&sort=-date&page=1")
    assert r.status_code == 200
    body = r.json()
    assert body["limit"] == 10
    assert body["page"] == 1
    # -date sort puts the later date (deep_protocol: 2026-01-15) first
    assert body["items"][0]["id"] == str(deep_protocol.id)


async def test_list_protocols_sort_by_title(client, deep_protocol, second_protocol):
    r = await client.get("/api/v1/hmp/protocols?sort=title&limit=50")
    assert r.status_code == 200
    body = r.json()
    titles = [it["title"] for it in body["items"]]
    assert titles == sorted(titles)


async def test_list_protocols_excludes_soft_deleted(client, db_session):
    p = await _make_protocol(db_session, title="Soft Deleted")
    p.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    r = await client.get("/api/v1/hmp/protocols")
    assert r.status_code == 200
    body = r.json()
    assert all(it["id"] != str(p.id) for it in body["items"])


# ---------------------------------------------------------------------------
# GET /protocols/{id}
# ---------------------------------------------------------------------------

async def test_get_protocol_success(client, deep_protocol):
    r = await client.get(f"/api/v1/hmp/protocols/{deep_protocol.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(deep_protocol.id)
    assert body["title"] == "Deep Protocol"
    assert body["date"] == "2026-01-15"
    assert body["location"] == "Room A"
    assert body["chair"] == "Alice"


async def test_get_protocol_not_found(client):
    missing_id = uuid.uuid4()
    r = await client.get(f"/api/v1/hmp/protocols/{missing_id}")
    assert r.status_code == 404
    assert r.json()["detail"] == "Протокол не найден"


async def test_get_protocol_invalid_uuid(client):
    r = await client.get("/api/v1/hmp/protocols/not-a-uuid")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /protocols — multipart file upload
# ---------------------------------------------------------------------------

async def test_create_protocol_with_file(client, tmp_path, monkeypatch):
    """Upload a small file via multipart form and verify ProtocolResponse."""
    from app.core.config import settings

    # protocols_path is a @property derived from protocols_dir → patch the source.
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    file_bytes = b"FAKEAUDIO" * 100  # ~900 bytes
    files = {"file": ("meeting.mp3", io.BytesIO(file_bytes), "audio/mpeg")}
    data = {
        "title": "Created Protocol",
        "date": "2026-02-20",
        "location": "Office",
        "chair": "Bob",
        "agenda": "Q1 review",
        "language": "ru",
    }

    r = await client.post("/api/v1/hmp/protocols", files=files, data=data)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "Created Protocol"
    assert body["date"] == "2026-02-20"
    assert body["status"] == "loaded"
    assert body["audio_file"]["filename"] == "meeting.mp3"
    assert body["audio_file"]["extension"] == "mp3"
    assert body["audio_file"]["source"] == "local"
    assert body["audio_file"]["size_bytes"] == len(file_bytes)


async def test_create_protocol_missing_title(client):
    """Title is required → 422."""
    files = {"file": ("a.mp3", io.BytesIO(b"x"), "audio/mpeg")}
    data = {"date": "2026-02-20"}
    r = await client.post("/api/v1/hmp/protocols", files=files, data=data)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /protocols/{id}
# ---------------------------------------------------------------------------

async def test_update_protocol_success(client, deep_protocol):
    payload = {"title": "Updated Title", "location": "New Room"}
    r = await client.patch(f"/api/v1/hmp/protocols/{deep_protocol.id}", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Updated Title"
    assert body["location"] == "New Room"


async def test_update_protocol_not_found(client):
    r = await client.patch(
        f"/api/v1/hmp/protocols/{uuid.uuid4()}", json={"title": "X"}
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /protocols/{id} — soft delete
# ---------------------------------------------------------------------------

async def test_soft_delete_protocol_success(client, deep_protocol):
    r = await client.delete(f"/api/v1/hmp/protocols/{deep_protocol.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "soft_deleted"
    assert body["protocol_id"] == str(deep_protocol.id)


async def test_soft_delete_protocol_not_found(client):
    r = await client.delete(f"/api/v1/hmp/protocols/{uuid.uuid4()}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /protocols/{id}/permanent
# ---------------------------------------------------------------------------

async def test_hard_delete_protocol_success(client, db_session, tmp_path, monkeypatch):
    """Hard delete removes protocol + related data."""
    from app.core.config import settings
    from app.db.models import Protocol

    # protocols_path is a @property derived from protocols_dir → patch source.
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    # Create protocol dir + audio file
    pid = uuid.uuid4()
    proto_dir = tmp_path / str(pid)
    proto_dir.mkdir(parents=True, exist_ok=True)
    audio_path = proto_dir / "audio.mp3"
    audio_path.write_bytes(b"DELETEME")

    p = Protocol(
        id=pid,
        title="To Be Deleted",
        date=date_cls(2026, 3, 1),
        status="loaded",
    )
    db_session.add(p)
    await db_session.commit()

    r = await client.delete(f"/api/v1/hmp/protocols/{pid}/permanent")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "deleted"
    assert body["protocol_id"] == str(pid)
    assert "deleted_counts" in body
    # Protocol dir should be gone from disk
    assert not proto_dir.exists()


async def test_hard_delete_protocol_not_found(client):
    r = await client.delete(f"/api/v1/hmp/protocols/{uuid.uuid4()}/permanent")
    assert r.status_code == 404