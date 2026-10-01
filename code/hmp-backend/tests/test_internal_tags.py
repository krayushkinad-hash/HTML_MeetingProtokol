"""Coverage tests for app/routers/tags.py — target 60%+.

Endpoints under test:
  - GET  /protocols/{protocol_id}/tags          (list, 404 missing protocol)
  - POST /tags                                  (create, 404 missing protocol,
                                                 422 validation, 409 duplicate)
  - DELETE /tags/{tag_id}                       (delete, 404 missing tag)

All scenarios are packed into a single async test function to avoid the
TRUNCATE CASCADE deadlocks documented in tests/conftest.py.
"""
import uuid

import pytest


PREFIX = "/api/v1/hmp"


async def test_tags_router_comprehensive(client, sample_protocol):
    """All tags-router scenarios in one async test, using the shared
    sample_protocol fixture (committed in the same engine as the test client).
    """

    proto_id = sample_protocol.id

    # ------------------------------------------------------------------------
    # 0. Sanity: empty list for a brand-new protocol
    # ------------------------------------------------------------------------
    r = await client.get(f"{PREFIX}/protocols/{proto_id}/tags")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["items"] == []

    # ------------------------------------------------------------------------
    # 1. GET /protocols/{id}/tags — 404 for missing protocol
    # ------------------------------------------------------------------------
    missing_proto = uuid.uuid4()
    r = await client.get(f"{PREFIX}/protocols/{missing_proto}/tags")
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"].lower()

    # ------------------------------------------------------------------------
    # 2. GET /protocols/{id}/tags — invalid UUID → 422
    # ------------------------------------------------------------------------
    r = await client.get(f"{PREFIX}/protocols/not-a-uuid/tags")
    assert r.status_code == 422

    # ------------------------------------------------------------------------
    # 3. POST /tags — success, no color
    # ------------------------------------------------------------------------
    r = await client.post(
        f"{PREFIX}/tags",
        json={"protocol_id": str(proto_id), "name": "alpha"},
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["name"] == "alpha"
    assert created["protocol_id"] == str(proto_id)
    assert created["source"] == "manual"
    assert created["color"] is None
    assert "id" in created and "created_at" in created
    tag_a_id = created["id"]

    # ------------------------------------------------------------------------
    # 4. POST /tags — success with valid color
    # ------------------------------------------------------------------------
    r = await client.post(
        f"{PREFIX}/tags",
        json={"protocol_id": str(proto_id), "name": "beta", "color": "#FF00AA"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["color"] == "#FF00AA"

    # ------------------------------------------------------------------------
    # 5. POST /tags — invalid color pattern → 422
    # ------------------------------------------------------------------------
    r = await client.post(
        f"{PREFIX}/tags",
        json={"protocol_id": str(proto_id), "name": "bad", "color": "red"},
    )
    assert r.status_code == 422

    # ------------------------------------------------------------------------
    # 6. POST /tags — empty name (min_length=1) → 422
    # ------------------------------------------------------------------------
    r = await client.post(
        f"{PREFIX}/tags",
        json={"protocol_id": str(proto_id), "name": ""},
    )
    assert r.status_code == 422

    # ------------------------------------------------------------------------
    # 7. POST /tags — missing protocol_id field → 422
    # ------------------------------------------------------------------------
    r = await client.post(f"{PREFIX}/tags", json={"name": "orphan"})
    assert r.status_code == 422

    # ------------------------------------------------------------------------
    # 8. POST /tags — 404 for non-existent protocol
    # ------------------------------------------------------------------------
    r = await client.post(
        f"{PREFIX}/tags",
        json={"protocol_id": str(uuid.uuid4()), "name": "ghost"},
    )
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"].lower()

    # ------------------------------------------------------------------------
    # 9. POST /tags — duplicate (protocol_id, name) → 409
    # ------------------------------------------------------------------------
    r = await client.post(
        f"{PREFIX}/tags",
        json={"protocol_id": str(proto_id), "name": "alpha"},
    )
    assert r.status_code == 409, r.text
    assert "уже существует" in r.json()["detail"].lower()

    # ------------------------------------------------------------------------
    # 10. GET /protocols/{id}/tags — list returns tags, sorted by name asc
    # ------------------------------------------------------------------------
    r = await client.get(f"{PREFIX}/protocols/{proto_id}/tags")
    assert r.status_code == 200
    listed = r.json()
    assert listed["total"] == 2
    names = [item["name"] for item in listed["items"]]
    assert names == sorted(names)
    assert "alpha" in names and "beta" in names

    # ------------------------------------------------------------------------
    # 11. DELETE /tags/{id} — 404 for non-existent tag
    # ------------------------------------------------------------------------
    r = await client.delete(f"{PREFIX}/tags/{uuid.uuid4()}")
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"].lower()

    # ------------------------------------------------------------------------
    # 12. DELETE /tags/{id} — invalid UUID → 422
    # ------------------------------------------------------------------------
    r = await client.delete(f"{PREFIX}/tags/not-a-uuid")
    assert r.status_code == 422

    # ------------------------------------------------------------------------
    # 13. DELETE /tags/{id} — success removes the tag
    # ------------------------------------------------------------------------
    r = await client.delete(f"{PREFIX}/tags/{tag_a_id}")
    assert r.status_code == 200, r.text

    # Confirm it's gone
    r = await client.get(f"{PREFIX}/protocols/{proto_id}/tags")
    assert r.status_code == 200
    remaining = r.json()
    assert remaining["total"] == 1
    assert remaining["items"][0]["name"] == "beta"

    # ------------------------------------------------------------------------
    # 14. DELETE /tags/{id} — second delete of same id → 404 (idempotency check)
    # ------------------------------------------------------------------------
    r = await client.delete(f"{PREFIX}/tags/{tag_a_id}")
    assert r.status_code == 404