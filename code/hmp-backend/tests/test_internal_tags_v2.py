"""Coverage tests v2 for app/routers/tags.py — targets 70%+.

The v1 file (test_internal_tags.py) already hits every endpoint once via
a single mega-test. This v2 file splits the scenarios into isolated
async tests AND adds coverage for branches the v1 file missed:

- Direct unit test for the ``_to_response()`` helper (private but
  reachable via the public endpoints).
- Tag with empty-color string and full-length 50-char name.
- POST /tags: invalid UUID in protocol_id field → 422.
- POST /tags: oversized name (51 chars) → 422 (max_length branch).
- POST /tags: lowercase hex color accepted (``#abcdef``).
- GET /protocols/{id}/tags: response shape (total, items[]).
- DELETE /tags/{id}: valid deletion path removes the tag (count drops).
- DELETE /tags/{id}: malformed UUID path parameter → 422.
- POST /tags: duplicate duplicate (different protocol) is allowed
  (uniqueness is per-protocol — exercises the constraint naming branch).
- list_tags returns multiple tags in alphabetical order.

The conftest ``db_session`` fixture holds a transaction open for the
whole test which deadlocks against the request handler's session. So
we use a ``seed_sm`` sessionmaker built on the conftest ``db_engine``
and explicitly close the session BEFORE invoking ``client``. This is
the same deadlock-avoidance pattern used by test_internal_summary_v2.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.db.models import Protocol, ProtocolStatus, Tag
from app.routers.tags import _to_response

pytestmark = pytest.mark.asyncio

PREFIX = "/api/v1/hmp"


# ============================================================================
# Local helpers
# ============================================================================


def _protocol_kwargs(**overrides) -> dict:
    defaults = dict(
        id=uuid.uuid4(),
        title="Tags v2 Protocol",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return defaults


@pytest_asyncio.fixture
async def seed_sm(db_engine):
    """A sessionmaker bound to the conftest engine.

    Tests must commit + close their session BEFORE invoking ``client``
    to avoid deadlock with the request handler's own session.
    """
    return sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


async def _insert_protocol(sm) -> uuid.UUID:
    async with sm() as s:
        p = Protocol(**_protocol_kwargs())
        s.add(p)
        await s.commit()
        return p.id


async def _insert_protocol_with_tag(sm, name: str = "seed-tag") -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a Protocol + a pre-existing Tag and return (proto_id, tag_id)."""
    async with sm() as s:
        p = Protocol(**_protocol_kwargs())
        s.add(p)
        await s.flush()
        t = Tag(
            id=uuid.uuid4(),
            protocol_id=p.id,
            name=name,
            source="manual",
            color=None,
        )
        s.add(t)
        await s.commit()
        return p.id, t.id


# ============================================================================
# Direct unit test: _to_response() helper
# ============================================================================


async def test_to_response_helper_copies_fields(seed_sm):
    """_to_response() copies id/protocol_id/name/source/color/created_at."""
    async with seed_sm() as s:
        p = Protocol(**_protocol_kwargs())
        s.add(p)
        await s.flush()

        tag = Tag(
            id=uuid.uuid4(),
            protocol_id=p.id,
            name="helper-tag",
            source="manual",
            color="#123456",
        )
        s.add(tag)
        await s.flush()
        await s.refresh(tag)

        resp = _to_response(tag)

    assert resp.id == tag.id
    assert resp.protocol_id == p.id
    assert resp.name == "helper-tag"
    assert resp.source == "manual"
    assert resp.color == "#123456"
    # created_at is serialized as ISO string
    assert isinstance(resp.created_at, str)
    # Must be parseable as ISO datetime
    datetime.fromisoformat(resp.created_at)


# ============================================================================
# GET /protocols/{id}/tags
# ============================================================================


async def test_list_tags_returns_alphabetical_order(seed_sm, client):
    """Tags are returned sorted by name (ascending)."""
    proto_id = await _insert_protocol(seed_sm)

    # Create three tags out of alphabetical order
    for name in ("charlie", "alpha", "bravo"):
        r = await client.post(
            f"{PREFIX}/tags",
            json={"protocol_id": str(proto_id), "name": name},
        )
        assert r.status_code == 201, r.text

    r = await client.get(f"{PREFIX}/protocols/{proto_id}/tags")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    names = [item["name"] for item in body["items"]]
    assert names == ["alpha", "bravo", "charlie"]


async def test_list_tags_response_shape(seed_sm, client):
    """Response includes 'total' (int) and 'items' (list) with documented fields."""
    proto_id, tag_id = await _insert_protocol_with_tag(seed_sm, name="shape-tag")

    r = await client.get(f"{PREFIX}/protocols/{proto_id}/tags")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["total"], int)
    assert body["total"] == 1
    assert isinstance(body["items"], list)
    item = body["items"][0]
    # All TagResponse fields present
    assert set(item.keys()) >= {
        "id", "protocol_id", "name", "source", "color", "created_at"
    }
    assert item["id"] == str(tag_id)
    assert item["protocol_id"] == str(proto_id)
    assert item["name"] == "shape-tag"
    assert item["source"] == "manual"


async def test_list_tags_404_missing_protocol(client):
    """GET /tags for unknown protocol → 404 with Russian detail."""
    missing = uuid.uuid4()
    r = await client.get(f"{PREFIX}/protocols/{missing}/tags")
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"].lower()


async def test_list_tags_invalid_uuid_returns_422(client):
    """GET /tags with malformed UUID path param → 422 from FastAPI validation."""
    r = await client.get(f"{PREFIX}/protocols/not-a-uuid/tags")
    assert r.status_code == 422


# ============================================================================
# POST /tags
# ============================================================================


async def test_create_tag_with_lowercase_hex_color(seed_sm, client):
    """Lowercase 6-digit hex color (#abcdef) is accepted by the pattern."""
    proto_id = await _insert_protocol(seed_sm)
    r = await client.post(
        f"{PREFIX}/tags",
        json={
            "protocol_id": str(proto_id),
            "name": "lowercase",
            "color": "#abcdef",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["color"] == "#abcdef"


async def test_create_tag_max_length_name(seed_sm, client):
    """Tag with name of exactly 50 chars is accepted (boundary)."""
    proto_id = await _insert_protocol(seed_sm)
    name_50 = "a" * 50
    r = await client.post(
        f"{PREFIX}/tags",
        json={"protocol_id": str(proto_id), "name": name_50},
    )
    assert r.status_code == 201, r.text
    assert r.json()["name"] == name_50


async def test_create_tag_oversized_name_returns_422(seed_sm, client):
    """Tag with name of 51 chars is rejected by max_length validator."""
    proto_id = await _insert_protocol(seed_sm)
    r = await client.post(
        f"{PREFIX}/tags",
        json={"protocol_id": str(proto_id), "name": "a" * 51},
    )
    assert r.status_code == 422


async def test_create_tag_invalid_uuid_in_body_returns_422(client):
    """POST /tags with non-UUID protocol_id → 422 from pydantic validation."""
    r = await client.post(
        f"{PREFIX}/tags",
        json={"protocol_id": "not-a-uuid", "name": "x"},
    )
    assert r.status_code == 422


async def test_create_tag_duplicate_within_protocol_returns_409(seed_sm, client):
    """POST /tags with duplicate (protocol_id, name) → 409 from unique violation."""
    proto_id = await _insert_protocol(seed_sm)

    r1 = await client.post(
        f"{PREFIX}/tags",
        json={"protocol_id": str(proto_id), "name": "dup"},
    )
    assert r1.status_code == 201, r1.text

    r2 = await client.post(
        f"{PREFIX}/tags",
        json={"protocol_id": str(proto_id), "name": "dup"},
    )
    assert r2.status_code == 409, r2.text
    assert "уже существует" in r2.json()["detail"].lower()


async def test_create_tag_same_name_different_protocol_allowed(seed_sm, client):
    """Tag name uniqueness is per-protocol: same name in another protocol is OK.

    This exercises the Index/UniqueConstraint branch without hitting the
    409 path — confirming the constraint is scoped to protocol_id.
    """
    proto_a = await _insert_protocol(seed_sm)
    proto_b = await _insert_protocol(seed_sm)

    r1 = await client.post(
        f"{PREFIX}/tags",
        json={"protocol_id": str(proto_a), "name": "shared-name"},
    )
    assert r1.status_code == 201, r1.text

    r2 = await client.post(
        f"{PREFIX}/tags",
        json={"protocol_id": str(proto_b), "name": "shared-name"},
    )
    assert r2.status_code == 201, r2.text


# ============================================================================
# DELETE /tags/{id}
# ============================================================================


async def test_delete_tag_removes_and_decrements_count(seed_sm, client):
    """DELETE returns 200 and the tag no longer appears in subsequent GET."""
    proto_id, tag_id = await _insert_protocol_with_tag(seed_sm, name="to-delete")

    # Verify it's listed
    r = await client.get(f"{PREFIX}/protocols/{proto_id}/tags")
    assert r.status_code == 200
    assert r.json()["total"] == 1

    # Delete it
    r = await client.delete(f"{PREFIX}/tags/{tag_id}")
    assert r.status_code == 200, r.text

    # Confirm gone
    r = await client.get(f"{PREFIX}/protocols/{proto_id}/tags")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["items"] == []


async def test_delete_tag_invalid_uuid_returns_422(client):
    """DELETE with malformed UUID path param → 422 from FastAPI validation."""
    r = await client.delete(f"{PREFIX}/tags/not-a-uuid")
    assert r.status_code == 422


async def test_delete_tag_404_for_unknown_id(client):
    """DELETE on unknown tag id → 404 with Russian detail."""
    r = await client.delete(f"{PREFIX}/tags/{uuid.uuid4()}")
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"].lower()
