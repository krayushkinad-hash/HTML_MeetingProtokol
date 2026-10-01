"""Tests for app/routers/decisions.py (US-023).

Goal: bring coverage of decisions router above 50%.

Endpoints covered:
  * POST   /decisions
  * GET    /decisions (legacy, query)
  * GET    /protocols/{protocol_id}/decisions
  * DELETE /decisions/{decision_id}
"""
import uuid

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def protocol_with_utterance(db_engine):
    """Protocol + utterance with a non-zero start_sec for timestamp tests.

    Uses the test engine directly to avoid sharing a session with the
    request-scoped `client` fixture (prevents asyncpg deadlock on TRUNCATE).
    """
    from datetime import datetime, timezone

    from app.db.models import Protocol, ProtocolStatus, Speaker, Utterance
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    SessionLocal = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as s:
        p = Protocol(
            id=uuid.uuid4(),
            title="Decision Test Protocol",
            status=ProtocolStatus.RECORDING,
            date=datetime.now(timezone.utc).date(),
            created_at=datetime.now(timezone.utc),
        )
        s.add(p)
        await s.commit()

        sp = Speaker(
            id=uuid.uuid4(),
            protocol_id=p.id,
            speaker_label="SPK_D",
        )
        s.add(sp)
        await s.commit()

        u = Utterance(
            id=uuid.uuid4(),
            protocol_id=p.id,
            speaker_id=sp.id,
            start_sec=42.5,
            end_sec=43.5,
            text="utterance text",
        )
        s.add(u)
        await s.commit()
    return {"protocol": p, "speaker": sp, "utterance": u}


@pytest.fixture
async def other_protocol(db_engine):
    """A second protocol used for cross-protocol conflict test."""
    from datetime import datetime, timezone

    from app.db.models import Protocol, ProtocolStatus
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    SessionLocal = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as s:
        p = Protocol(
            id=uuid.uuid4(),
            title="Other Protocol",
            status=ProtocolStatus.RECORDING,
            date=datetime.now(timezone.utc).date(),
            created_at=datetime.now(timezone.utc),
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)
    return p


# ---------------------------------------------------------------------------
# POST /decisions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_decision_minimal(client, protocol_with_utterance):
    """POST without source_utterance_id — minimal happy path."""
    proto = protocol_with_utterance["protocol"]
    payload = {
        "protocol_id": str(proto.id),
        "text": "We will ship it.",
        "priority": "medium",
        "source": "transcript",
    }
    r = await client.post("/api/v1/hmp/decisions", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["text"] == "We will ship it."
    assert body["priority"] == "medium"
    assert body["protocol_id"] == str(proto.id)
    assert body["source_utterance_id"] is None
    # Without source_utterance_id, timestamp_sec stays None
    assert body["timestamp_sec"] is None
    assert uuid.UUID(body["id"])
    assert body["created_at"]


@pytest.mark.asyncio
async def test_create_decision_with_timestamp_sec(client, protocol_with_utterance):
    """POST with explicit timestamp_sec (Live Mode) — should be echoed back."""
    proto = protocol_with_utterance["protocol"]
    payload = {
        "protocol_id": str(proto.id),
        "text": "Live decision",
        "timestamp_sec": 12.75,
        "source": "live",
        "decided_by": "Alice",
        "priority": "high",
    }
    r = await client.post("/api/v1/hmp/decisions", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["timestamp_sec"] == 12.75
    assert body["source_utterance_id"] is None
    assert body["decided_by"] == "Alice"
    assert body["priority"] == "high"


@pytest.mark.asyncio
async def test_create_decision_with_utterance_propagates_start_sec(
    client, protocol_with_utterance
):
    """When source_utterance_id is set, response.timestamp_sec == utterance.start_sec."""
    proto = protocol_with_utterance["protocol"]
    utt = protocol_with_utterance["utterance"]
    payload = {
        "protocol_id": str(proto.id),
        "text": "Sourced from utterance",
        "source_utterance_id": str(utt.id),
        "priority": "low",
    }
    r = await client.post("/api/v1/hmp/decisions", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    # E146: timestamp_sec denormalised from utterance.start_sec
    assert body["timestamp_sec"] == 42.5
    assert body["source_utterance_id"] == str(utt.id)


@pytest.mark.asyncio
async def test_create_decision_protocol_not_found(client, db_session):
    """POST with non-existent protocol_id → 404."""
    payload = {
        "protocol_id": str(uuid.uuid4()),
        "text": "no protocol",
    }
    r = await client.post("/api/v1/hmp/decisions", json=payload)
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"]


@pytest.mark.asyncio
async def test_create_decision_utterance_not_found(client, protocol_with_utterance):
    """POST with source_utterance_id that doesn't exist → 404."""
    proto = protocol_with_utterance["protocol"]
    payload = {
        "protocol_id": str(proto.id),
        "text": "orphan utterance",
        "source_utterance_id": str(uuid.uuid4()),
    }
    r = await client.post("/api/v1/hmp/decisions", json=payload)
    assert r.status_code == 404
    assert "Реплика" in r.json()["detail"]


@pytest.mark.asyncio
async def test_create_decision_utterance_other_protocol_409(
    client, protocol_with_utterance, other_protocol, db_engine
):
    """POST with source_utterance_id that belongs to a different protocol → 409."""
    # Build an utterance under *other_protocol*
    from app.db.models import Speaker, Utterance
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    SessionLocal = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as s:
        sp = Speaker(
            id=uuid.uuid4(),
            protocol_id=other_protocol.id,
            speaker_label="SPK_X",
        )
        s.add(sp)
        await s.commit()

        other_utt = Utterance(
            id=uuid.uuid4(),
            protocol_id=other_protocol.id,
            speaker_id=sp.id,
            start_sec=1.0,
            end_sec=2.0,
            text="foreign",
        )
        s.add(other_utt)
        await s.commit()

    proto = protocol_with_utterance["protocol"]
    payload = {
        "protocol_id": str(proto.id),  # current protocol
        "text": "cross-protocol",
        "source_utterance_id": str(other_utt.id),  # belongs to other_protocol
    }
    r = await client.post("/api/v1/hmp/decisions", json=payload)
    assert r.status_code == 409
    assert "другому протоколу" in r.json()["detail"]


@pytest.mark.asyncio
async def test_create_decision_validation_error_422(client, protocol_with_utterance):
    """POST with bad payload (empty text + invalid priority) → 422."""
    proto = protocol_with_utterance["protocol"]
    payload = {
        "protocol_id": str(proto.id),
        "text": "",  # min_length=1 violated
        "priority": "urgent",  # not in Literal
    }
    r = await client.post("/api/v1/hmp/decisions", json=payload)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /decisions (legacy query) + GET /protocols/{id}/decisions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_decisions_legacy_query_with_priority_filter(
    client, protocol_with_utterance
):
    """GET /decisions?protocol_id=...&priority=high — only matching items."""
    proto = protocol_with_utterance["protocol"]
    utt = protocol_with_utterance["utterance"]

    # Create one high and one medium decision
    r1 = await client.post(
        "/api/v1/hmp/decisions",
        json={
            "protocol_id": str(proto.id),
            "text": "high one",
            "priority": "high",
            "source_utterance_id": str(utt.id),
        },
    )
    assert r1.status_code == 201
    r2 = await client.post(
        "/api/v1/hmp/decisions",
        json={
            "protocol_id": str(proto.id),
            "text": "medium one",
            "priority": "medium",
        },
    )
    assert r2.status_code == 201

    r = await client.get(
        "/api/v1/hmp/decisions",
        params={"protocol_id": str(proto.id), "priority": "high"},
    )
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["priority"] == "high"
    assert items[0]["text"] == "high one"
    # E146: list returns timestamp_sec from source_utterance.start_sec
    assert items[0]["timestamp_sec"] == 42.5


@pytest.mark.asyncio
async def test_list_decisions_rest_endpoint(client, protocol_with_utterance):
    """GET /protocols/{id}/decisions — returns all decisions (no filter)."""
    proto = protocol_with_utterance["protocol"]
    await client.post(
        "/api/v1/hmp/decisions",
        json={"protocol_id": str(proto.id), "text": "one", "priority": "low"},
    )
    await client.post(
        "/api/v1/hmp/decisions",
        json={"protocol_id": str(proto.id), "text": "two", "priority": "high"},
    )
    r = await client.get(f"/api/v1/hmp/protocols/{proto.id}/decisions")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    texts = {i["text"] for i in items}
    assert texts == {"one", "two"}


@pytest.mark.asyncio
async def test_list_decisions_without_utterance_has_null_timestamp(
    client, protocol_with_utterance
):
    """Decision without source_utterance_id → timestamp_sec=null in list response."""
    proto = protocol_with_utterance["protocol"]
    await client.post(
        "/api/v1/hmp/decisions",
        json={"protocol_id": str(proto.id), "text": "plain", "priority": "medium"},
    )
    r = await client.get(f"/api/v1/hmp/protocols/{proto.id}/decisions")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["timestamp_sec"] is None


@pytest.mark.asyncio
async def test_list_decisions_missing_query_param_422(client):
    """GET /decisions without required protocol_id → 422."""
    r = await client.get("/api/v1/hmp/decisions")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /decisions/{decision_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_decision_success(client, protocol_with_utterance):
    proto = protocol_with_utterance["protocol"]
    # Create a decision first
    create = await client.post(
        "/api/v1/hmp/decisions",
        json={"protocol_id": str(proto.id), "text": "to be deleted"},
    )
    assert create.status_code == 201
    decision_id = create.json()["id"]

    # Delete it
    r = await client.delete(f"/api/v1/hmp/decisions/{decision_id}")
    assert r.status_code == 200

    # Verify it's gone (list should be empty)
    list_r = await client.get(f"/api/v1/hmp/protocols/{proto.id}/decisions")
    assert list_r.status_code == 200
    assert list_r.json() == []


@pytest.mark.asyncio
async def test_delete_decision_not_found(client):
    """DELETE non-existent id → 404."""
    r = await client.delete(f"/api/v1/hmp/decisions/{uuid.uuid4()}")
    assert r.status_code == 404
    assert "не найдено" in r.json()["detail"]


@pytest.mark.asyncio
async def test_delete_decision_invalid_uuid_422(client):
    """DELETE with malformed UUID → 422."""
    r = await client.delete("/api/v1/hmp/decisions/not-a-uuid")
    assert r.status_code == 422