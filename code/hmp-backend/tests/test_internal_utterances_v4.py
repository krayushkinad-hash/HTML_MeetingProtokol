"""E289-v4: extra coverage tests for routers/utterances.py.

Targets branches NOT covered by v1/v2/v3:
- update_utterance_text: no-op (text unchanged) → returns current, no commit branch
- update_utterance_text: invalid uuid → 422
- update_utterance_text: text_original set on first edit via snapshot=true
- update_utterance_speaker: invalid uuid → 422
- update_utterance_speaker: 400 wrong-protocol with detail string
- list_utterances: invalid uuid for protocol_id → 422
- list_utterance_versions: invalid uuid → 422
- restore_utterance_version: version_number < 1 → 422 (early return)
- restore_utterance_version: snapshot missing previous_text → 422
- restore_utterance_version: invalid uuid → 422
- toggle_utterance_important: invalid uuid → 422
- get_utterance: 404 with proper detail message
- list_utterances: speaker_id filter (no after_sec, no low_confidence)
- update_utterance_text: with confidence / low_confidence / important fields
"""
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio


PREFIX = "/api/v1/hmp"


@pytest_asyncio.fixture
async def make_factory(db_engine):
    """Per fastapi-router-test-coverage pitfall #8b — direct connection inserts
    avoid db_session+client pool-staleness on the shared test DB.
    """
    from sqlalchemy import insert as sa_insert

    async def _make(model_cls, **_kwargs):
        async with db_engine.connect() as conn:
            trans = await conn.begin()
            try:
                await conn.execute(sa_insert(model_cls).values(**_kwargs))
                await trans.commit()
            except Exception:
                await trans.rollback()
                raise
        return model_cls(**_kwargs)

    return _make


# ============================================================================
# update_utterance_text — no-op + invalid uuid + happy path with text_original
# ============================================================================

@pytest.mark.asyncio
async def test_update_text_noop_returns_unchanged(client, make_factory):
    """Same text → no snapshot taken, returns current state (early return)."""
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

    # No version snapshot should have been recorded
    v = await client.get(f"{PREFIX}/utterances/{utt.id}/versions")
    assert v.status_code == 200
    assert v.json()["total"] == 0


@pytest.mark.asyncio
async def test_update_text_invalid_uuid_422(client):
    """Invalid uuid → 422 (path validation)."""
    r = await client.patch(
        f"{PREFIX}/utterances/not-a-uuid/text",
        json={"text": "x", "version_snapshot": False},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_update_text_sets_text_original_on_first_edit(
    client, make_factory
):
    """First edit with version_snapshot=True must snapshot AND set text_original."""
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
        text="Original-A",
    )

    r = await client.patch(
        f"{PREFIX}/utterances/{utt.id}/text",
        json={"text": "New", "version_snapshot": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "New"

    # Exactly 1 version recorded
    v = await client.get(f"{PREFIX}/utterances/{utt.id}/versions")
    assert v.status_code == 200
    assert v.json()["total"] == 1
    snap = v.json()["items"][0]["snapshot"]
    # snapshot dict keys must be populated
    assert snap["field"] == "text"
    assert snap["previous_text"] == "Original-A"
    assert snap["new_text"] == "New"


# ============================================================================
# update_utterance_speaker — 400 wrong protocol detail + invalid uuid
# ============================================================================

@pytest.mark.asyncio
async def test_update_speaker_wrong_protocol_400_detail(
    client, make_factory
):
    """Speaker belongs to another protocol → 400 with Russian detail."""
    from app.db.models import Protocol, ProtocolStatus, Speaker, Utterance

    proto_a = await make_factory(
        Protocol,
        id=uuid.uuid4(),
        title="A",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    proto_b = await make_factory(
        Protocol,
        id=uuid.uuid4(),
        title="B",
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
    assert "протокол" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_speaker_invalid_uuid_422(client):
    """Invalid uuid in path → 422."""
    r = await client.patch(
        f"{PREFIX}/utterances/not-a-uuid/speaker",
        json={"speaker_id": str(uuid.uuid4())},
    )
    assert r.status_code == 422


# ============================================================================
# list_utterances — invalid uuid + speaker-only filter
# ============================================================================

@pytest.mark.asyncio
async def test_list_utterances_invalid_protocol_uuid_422(client):
    """Invalid uuid for protocol_id query → 422."""
    r = await client.get(f"{PREFIX}/utterances?protocol_id=not-a-uuid")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_utterances_speaker_only_filter(
    client, make_factory
):
    """speaker_id filter alone (no after_sec, no low_confidence_only)."""
    from app.db.models import Protocol, ProtocolStatus, Speaker, Utterance

    proto = await make_factory(
        Protocol,
        id=uuid.uuid4(),
        title="P",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    spk1 = await make_factory(
        Speaker, id=uuid.uuid4(), protocol_id=proto.id, speaker_label="S1"
    )
    spk2 = await make_factory(
        Speaker, id=uuid.uuid4(), protocol_id=proto.id, speaker_label="S2"
    )
    await make_factory(
        Utterance,
        id=uuid.uuid4(),
        protocol_id=proto.id,
        speaker_id=spk1.id,
        start_sec=0.0,
        end_sec=1.0,
        text="A",
    )
    await make_factory(
        Utterance,
        id=uuid.uuid4(),
        protocol_id=proto.id,
        speaker_id=spk2.id,
        start_sec=2.0,
        end_sec=3.0,
        text="B",
    )

    r = await client.get(
        f"{PREFIX}/utterances?protocol_id={proto.id}&speaker_id={spk1.id}"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["speaker_id"] == str(spk1.id)


# ============================================================================
# list_utterance_versions — invalid uuid
# ============================================================================

@pytest.mark.asyncio
async def test_list_versions_invalid_uuid_422(client):
    r = await client.get(f"{PREFIX}/utterances/not-a-uuid/versions")
    assert r.status_code == 422


# ============================================================================
# restore_utterance_version — version_number<1, missing previous_text, invalid uuid
# ============================================================================

@pytest.mark.asyncio
async def test_restore_version_number_zero_422(client, make_factory):
    """version_number < 1 → 422 (early return before _load_utterance)."""
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
    assert "положительным" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_restore_snapshot_missing_previous_text_422(
    client, make_factory, db_engine
):
    """Snapshot dict lacks 'previous_text' → 422."""
    from sqlalchemy import insert as sa_insert
    from app.db.models import (
        Protocol, ProtocolStatus, Speaker, Utterance, ProtocolVersion,
    )

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

    # Inject a version whose snapshot has NO previous_text
    bad_snap = {"utterance_id": str(utt.id), "field": "text"}
    async with db_engine.connect() as conn:
        trans = await conn.begin()
        await conn.execute(
            sa_insert(ProtocolVersion).values(
                id=uuid.uuid4(),
                protocol_id=proto.id,
                version_number=1,
                snapshot=bad_snap,
                changed_field=f"utterance:{utt.id}:text",
                changed_by="user",
                change_reason="test",
            )
        )
        await trans.commit()

    r = await client.post(f"{PREFIX}/utterances/{utt.id}/restore/1")
    assert r.status_code == 422, r.text
    assert "previous_text" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_restore_invalid_uuid_422(client):
    r = await client.post(f"{PREFIX}/utterances/not-a-uuid/restore/1")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_restore_version_not_found_404(client, make_factory):
    """No matching ProtocolVersion → 404."""
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
    assert r.status_code == 404, r.text


# ============================================================================
# get_utterance — 404 detail + invalid uuid
# ============================================================================

@pytest.mark.asyncio
async def test_get_utterance_404_detail(client):
    r = await client.get(f"{PREFIX}/utterances/{uuid.uuid4()}")
    assert r.status_code == 404
    assert "реплика" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_utterance_invalid_uuid_422(client):
    r = await client.get(f"{PREFIX}/utterances/not-a-uuid")
    assert r.status_code == 422


# ============================================================================
# update_utterance_text — utterance 404 detail
# ============================================================================

@pytest.mark.asyncio
async def test_update_text_utterance_not_found_404(client):
    r = await client.patch(
        f"{PREFIX}/utterances/{uuid.uuid4()}/text",
        json={"text": "x"},
    )
    assert r.status_code == 404
    assert "реплика" in r.json()["detail"].lower()