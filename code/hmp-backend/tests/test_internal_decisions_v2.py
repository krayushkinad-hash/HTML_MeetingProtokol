"""Tests for app/routers/decisions.py (v2).

Goal: push coverage of decisions router past 70% by hitting the branches
that the original test_internal_decisions.py missed:
  * list with NO decisions (empty path)
  * list when source_utterance was removed (utt is None branch)
  * list with priority=None filter (no priority clause)
  * validation 422 on bad source literal, negative timestamp_sec,
    missing protocol_id, oversized decided_by, invalid uuid in path
  * DELETE then DELETE same id → 404 second time

Uses the shared conftest fixtures (sample_protocol / sample_utterance)
to avoid session/transaction entanglement with the client fixture.
"""
import uuid

import pytest
from sqlalchemy import delete as sql_delete


# ---------------------------------------------------------------------------
# List endpoint — additional branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_decisions_empty(client, sample_protocol):
    """GET /protocols/{id}/decisions when no decisions exist → []."""
    r = await client.get(f"/api/v1/hmp/protocols/{sample_protocol.id}/decisions")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_decisions_no_priority_filter(client, sample_protocol):
    """priority=None (no filter clause) → returns all decisions."""
    for prio in ("low", "medium", "high"):
        rr = await client.post(
            "/api/v1/hmp/decisions",
            json={
                "protocol_id": str(sample_protocol.id),
                "text": f"d-{prio}",
                "priority": prio,
            },
        )
        assert rr.status_code == 201, rr.text

    # Legacy query endpoint without priority filter
    r = await client.get(
        "/api/v1/hmp/decisions", params={"protocol_id": str(sample_protocol.id)}
    )
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 3
    texts = {i["text"] for i in items}
    assert texts == {"d-low", "d-medium", "d-high"}


@pytest.mark.asyncio
async def test_list_decisions_with_orphan_utterance_id(
    client, sample_protocol, sample_utterance, db_session
):
    """Decision row whose source_utterance_id no longer exists → timestamp_sec=null.

    Exercises the `if utt:` False branch in _list_decisions_impl.
    """
    # Create decision linked to utterance
    cr = await client.post(
        "/api/v1/hmp/decisions",
        json={
            "protocol_id": str(sample_protocol.id),
            "text": "will lose its utterance",
            "source_utterance_id": str(sample_utterance.id),
        },
    )
    assert cr.status_code == 201, cr.text
    assert cr.json()["timestamp_sec"] == 0.0  # conftest utterance start_sec=0.0

    # Delete the underlying utterance row directly in DB (same session the client uses)
    await db_session.execute(
        sql_delete(__import__("app.db.models", fromlist=["Utterance"]).Utterance).where(
            __import__("app.db.models", fromlist=["Utterance"]).Utterance.id
            == sample_utterance.id
        )
    )
    await db_session.commit()

    # Listing must still succeed and timestamp_sec falls back to None
    r = await client.get(f"/api/v1/hmp/protocols/{sample_protocol.id}/decisions")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    # Decision.source_utterance_id has ondelete=SET NULL in DB, so the FK is
    # cleared when the underlying utterance row is deleted. The list endpoint
    # therefore echoes source_utterance_id=None and timestamp_sec=None.
    assert items[0]["source_utterance_id"] is None
    assert items[0]["timestamp_sec"] is None


@pytest.mark.asyncio
async def test_list_decisions_invalid_uuid_422(client):
    """GET /protocols/{id}/decisions with malformed UUID → 422."""
    r = await client.get("/api/v1/hmp/protocols/not-a-uuid/decisions")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /decisions — additional validation 422 branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_decision_missing_protocol_id_422(client):
    """POST without protocol_id field → 422."""
    r = await client.post("/api/v1/hmp/decisions", json={"text": "orphan"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_decision_invalid_source_literal_422(client, sample_protocol):
    """POST with source not in {transcript, live} → 422."""
    r = await client.post(
        "/api/v1/hmp/decisions",
        json={
            "protocol_id": str(sample_protocol.id),
            "text": "weird source",
            "source": "telepathy",
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_decision_negative_timestamp_422(client, sample_protocol):
    """timestamp_sec with ge=0 — negative value → 422."""
    r = await client.post(
        "/api/v1/hmp/decisions",
        json={
            "protocol_id": str(sample_protocol.id),
            "text": "back to the future",
            "timestamp_sec": -1.0,
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_decision_oversized_decided_by_422(client, sample_protocol):
    """decided_by > 100 chars → 422 (max_length=100)."""
    r = await client.post(
        "/api/v1/hmp/decisions",
        json={
            "protocol_id": str(sample_protocol.id),
            "text": "too long decided_by",
            "decided_by": "x" * 101,
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_decision_text_too_long_422(client, sample_protocol):
    """text > 2000 chars → 422 (max_length=2000)."""
    r = await client.post(
        "/api/v1/hmp/decisions",
        json={"protocol_id": str(sample_protocol.id), "text": "a" * 2001},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_decision_all_fields(
    client, sample_protocol, sample_utterance
):
    """All optional fields populated — coverage for the full create body."""
    r = await client.post(
        "/api/v1/hmp/decisions",
        json={
            "protocol_id": str(sample_protocol.id),
            "text": "full payload",
            "decided_by": "Bob",
            "priority": "low",
            "source_utterance_id": str(sample_utterance.id),
            "source": "transcript",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["decided_by"] == "Bob"
    assert body["priority"] == "low"
    assert body["source_utterance_id"] == str(sample_utterance.id)
    # denormalised from utterance.start_sec (=0.0 from conftest)
    assert body["timestamp_sec"] == 0.0


# ---------------------------------------------------------------------------
# DELETE — double-delete returns 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_decision_twice_returns_404(client, sample_protocol):
    cr = await client.post(
        "/api/v1/hmp/decisions",
        json={"protocol_id": str(sample_protocol.id), "text": "doomed"},
    )
    assert cr.status_code == 201
    did = cr.json()["id"]

    r1 = await client.delete(f"/api/v1/hmp/decisions/{did}")
    assert r1.status_code == 200

    r2 = await client.delete(f"/api/v1/hmp/decisions/{did}")
    assert r2.status_code == 404
    assert "не найдено" in r2.json()["detail"]