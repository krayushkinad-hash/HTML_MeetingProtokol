"""E349-round3: coverage-targeted tests for routers/utterances.py — edge branches.

Targets branches NOT covered by v3 / round1 / round2:
- update_utterance_text: no-op (text == body.text) → returns without commit
- update_utterance_text: empty text → 422 (min_length=1)
- update_utterance_text: text > 10000 chars → 422 (max_length=10000)
- update_utterance_text: invalid uuid → 422
- update_utterance_text: nonexistent utterance → 404
- update_utterance_speaker: target from different protocol → 400
- update_utterance_speaker: nonexistent target speaker → 404
- update_utterance_speaker: invalid uuid → 422
- list_utterances: nonexistent protocol → 404
- list_utterances: invalid protocol_id uuid → 422
- list_utterances: pagination with skip/limit returns subset
- restore_utterance_version: version_number < 1 → 422
- restore_utterance_version: version not found → 404

Uses make_factory fixture (per fastapi-router-test-coverage pitfall #8b)
to avoid db_session+client deadlock on the shared test DB.
"""
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio


PREFIX = "/api/v1/hmp"


@pytest_asyncio.fixture
async def make_factory(db_engine):
    """Create objects via raw connection — guaranteed visibility."""
    from sqlalchemy import insert as sa_insert

    async def _make(model_cls, **_kwargs):
        async with db_engine.connect() as conn:
            trans = await conn.begin()
            try:
                await conn.execute(
                    sa_insert(model_cls).values(**_kwargs)
                )
                await trans.commit()
            except Exception:
                await trans.rollback()
                raise
        return model_cls(**_kwargs)

    return _make


# ============================================================================
# update_utterance_text — no-op branch + length validation + 404/422
# ============================================================================

@pytest.mark.asyncio
async def test_update_text_noop_returns_current_state(client, make_factory):
    """When body.text == utterance.text → returns _to_response without commit."""
    from app.db.models import Protocol, ProtocolStatus, Speaker, Utterance

    proto = await make_factory(
        Protocol,
        id=uuid.uuid4(),
        title="P",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    spk = await make_factory(
        Speaker, id=uuid.uuid4(), protocol_id=proto.id, speaker_label="S"
    )
    utt = await make_factory(
        Utterance,
        id=uuid.uuid4(),
        protocol_id=proto.id,
        speaker_id=spk.id,
        start_sec=0.0,
        end_sec=1.0,
        text="Same",
    )

    r = await client.patch(
        f"{PREFIX}/utterances/{utt.id}/text",
        json={"text": "Same", "version_snapshot": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "Same"
    # No version snapshot should have been written
    v = await client.get(f"{PREFIX}/utterances/{utt.id}/versions")
    assert v.status_code == 200
    assert v.json()["total"] == 0


@pytest.mark.asyncio
async def test_update_text_empty_422(client, make_factory):
    """Empty text violates min_length=1 → 422."""
    from app.db.models import Protocol, ProtocolStatus, Speaker, Utterance

    proto = await make_factory(
        Protocol,
        id=uuid.uuid4(),
        title="P",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    spk = await make_factory(
        Speaker, id=uuid.uuid4(), protocol_id=proto.id, speaker_label="S"
    )
    utt = await make_factory(
        Utterance,
        id=uuid.uuid4(),
        protocol_id=proto.id,
        speaker_id=spk.id,
        start_sec=0.0,
        end_sec=1.0,
        text="X",
    )

    r = await client.patch(
        f"{PREFIX}/utterances/{utt.id}/text",
        json={"text": "", "version_snapshot": False},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_update_text_too_long_422(client, make_factory):
    """text > 10000 chars violates max_length=10000 → 422."""
    from app.db.models import Protocol, ProtocolStatus, Speaker, Utterance

    proto = await make_factory(
        Protocol,
        id=uuid.uuid4(),
        title="P",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    spk = await make_factory(
        Speaker, id=uuid.uuid4(), protocol_id=proto.id, speaker_label="S"
    )
    utt = await make_factory(
        Utterance,
        id=uuid.uuid4(),
        protocol_id=proto.id,
        speaker_id=spk.id,
        start_sec=0.0,
        end_sec=1.0,
        text="X",
    )

    r = await client.patch(
        f"{PREFIX}/utterances/{utt.id}/text",
        json={"text": "a" * 10001, "version_snapshot": False},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_update_text_invalid_uuid_422(client):
    """Invalid uuid in path → 422."""
    r = await client.patch(
        f"{PREFIX}/utterances/not-a-uuid/text",
        json={"text": "Hello", "version_snapshot": False},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_update_text_nonexistent_utterance_404(client):
    """Valid uuid but no such utterance → 404."""
    r = await client.patch(
        f"{PREFIX}/utterances/{uuid.uuid4()}/text",
        json={"text": "Hello", "version_snapshot": False},
    )
    assert r.status_code == 404


# ============================================================================
# update_utterance_speaker — cross-protocol 400 + 404 + invalid uuid
# ============================================================================

@pytest.mark.asyncio
async def test_update_speaker_cross_protocol_400(client, make_factory):
    """Target speaker from a DIFFERENT protocol → 400."""
    from app.db.models import Protocol, ProtocolStatus, Speaker, Utterance

    proto_a = await make_factory(
        Protocol,
        id=uuid.uuid4(),
        title="PA",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    proto_b = await make_factory(
        Protocol,
        id=uuid.uuid4(),
        title="PB",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    spk_a = await make_factory(
        Speaker, id=uuid.uuid4(), protocol_id=proto_a.id, speaker_label="A"
    )
    spk_b = await make_factory(
        Speaker, id=uuid.uuid4(), protocol_id=proto_b.id, speaker_label="B"
    )
    utt = await make_factory(
        Utterance,
        id=uuid.uuid4(),
        protocol_id=proto_a.id,
        speaker_id=spk_a.id,
        start_sec=0.0,
        end_sec=1.0,
        text="X",
    )

    r = await client.patch(
        f"{PREFIX}/utterances/{utt.id}/speaker",
        json={"speaker_id": str(spk_b.id)},
    )
    assert r.status_code == 400, r.text
    assert "другому протоколу" in r.json()["detail"]


@pytest.mark.asyncio
async def test_update_speaker_target_not_found_404(client, make_factory):
    """speaker_id points to non-existent speaker → 404."""
    from app.db.models import Protocol, ProtocolStatus, Speaker, Utterance

    proto = await make_factory(
        Protocol,
        id=uuid.uuid4(),
        title="P",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    spk = await make_factory(
        Speaker, id=uuid.uuid4(), protocol_id=proto.id, speaker_label="S"
    )
    utt = await make_factory(
        Utterance,
        id=uuid.uuid4(),
        protocol_id=proto.id,
        speaker_id=spk.id,
        start_sec=0.0,
        end_sec=1.0,
        text="X",
    )

    r = await client.patch(
        f"{PREFIX}/utterances/{utt.id}/speaker",
        json={"speaker_id": str(uuid.uuid4())},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_speaker_invalid_uuid_422(client):
    """Invalid uuid in path → 422."""
    r = await client.patch(
        f"{PREFIX}/utterances/garbage/speaker",
        json={"speaker_id": str(uuid.uuid4())},
    )
    assert r.status_code == 422


# ============================================================================
# list_utterances — pagination edges + 404 + invalid uuid
# ============================================================================

@pytest.mark.asyncio
async def test_list_utterances_protocol_not_found_404(client):
    """Valid uuid but no such protocol → 404."""
    r = await client.get(f"{PREFIX}/utterances?protocol_id={uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_utterances_invalid_protocol_uuid_422(client):
    """Invalid protocol_id → 422."""
    r = await client.get(f"{PREFIX}/utterances?protocol_id=not-a-uuid")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_utterances_pagination_skip_limit(client, make_factory):
    """skip=1 limit=2 returns the 2nd and 3rd items, total reflects all."""
    from app.db.models import Protocol, ProtocolStatus, Speaker, Utterance

    proto = await make_factory(
        Protocol,
        id=uuid.uuid4(),
        title="P",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    spk = await make_factory(
        Speaker, id=uuid.uuid4(), protocol_id=proto.id, speaker_label="S"
    )
    for i, ts in enumerate([1.0, 2.0, 3.0, 4.0, 5.0]):
        await make_factory(
            Utterance,
            id=uuid.uuid4(),
            protocol_id=proto.id,
            speaker_id=spk.id,
            start_sec=ts,
            end_sec=ts + 0.5,
            text=f"U{i}",
        )

    r = await client.get(
        f"{PREFIX}/utterances?protocol_id={proto.id}&skip=1&limit=2"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 5
    assert body["skip"] == 1
    assert body["limit"] == 2
    assert len(body["items"]) == 2
    # Page 1 = items at index 1,2 (texts U1, U2)
    assert body["items"][0]["text"] == "U1"
    assert body["items"][1]["text"] == "U2"


# ============================================================================
# restore_utterance_version — invalid version + version not found
# ============================================================================

@pytest.mark.asyncio
async def test_restore_version_zero_422(client, make_factory):
    """version_number=0 violates the explicit < 1 check → 422."""
    from app.db.models import Protocol, ProtocolStatus, Speaker, Utterance

    proto = await make_factory(
        Protocol,
        id=uuid.uuid4(),
        title="P",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    spk = await make_factory(
        Speaker, id=uuid.uuid4(), protocol_id=proto.id, speaker_label="S"
    )
    utt = await make_factory(
        Utterance,
        id=uuid.uuid4(),
        protocol_id=proto.id,
        speaker_id=spk.id,
        start_sec=0.0,
        end_sec=1.0,
        text="X",
    )

    r = await client.post(f"{PREFIX}/utterances/{utt.id}/restore/0")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_restore_version_not_found_404(client, make_factory):
    """version_number that doesn't exist → 404."""
    from app.db.models import Protocol, ProtocolStatus, Speaker, Utterance

    proto = await make_factory(
        Protocol,
        id=uuid.uuid4(),
        title="P",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    spk = await make_factory(
        Speaker, id=uuid.uuid4(), protocol_id=proto.id, speaker_label="S"
    )
    utt = await make_factory(
        Utterance,
        id=uuid.uuid4(),
        protocol_id=proto.id,
        speaker_id=spk.id,
        start_sec=0.0,
        end_sec=1.0,
        text="X",
    )

    r = await client.post(f"{PREFIX}/utterances/{utt.id}/restore/999")
    assert r.status_code == 404
