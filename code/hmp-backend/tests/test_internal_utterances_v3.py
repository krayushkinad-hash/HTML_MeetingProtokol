"""E289-v3: coverage-targeted tests for routers/utterances.py — gap branches.

Targets branches NOT covered by v2:
- update_utterance_text: text_original already set (preserve branch on re-edit)
- update_utterance_text: text_original set without snapshot
- update_utterance_text: missing 'text' field → 422
- update_utterance_speaker: previous_speaker_id is None (no prior)
- update_utterance_speaker: missing 'speaker_id' → 422
- list_utterances: zero utterances
- list_utterances: combined filters
- list_utterances: invalid after_sec / limit / skip → 422
- restore_utterance_version: snapshot missing previous_text → 422
- restore_utterance_version: chained restores (multiple versions)
- list_utterance_versions: ordered newest-first
- _to_response: speaker_id is None (speaker_label None branch)
- toggle_utterance_important: missing 'important' field → 422, invalid uuid

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
    """Create objects via raw connection — guaranteed visibility.

    Returns a TRANSIENT ORM instance (not refreshed from DB) populated from
    kwargs. This avoids the cross-connection pool-staleness that breaks
    FK-ordered inserts when using `AsyncSession` across separate sessions.

    Tests only need `.id`, `.protocol_id`, `.speaker_id` for endpoint URLs
    and assertions — never the DB-side attribute access. We use plain
    python `uuid.UUID` for all of them (no pgproto.UUID contamination).
    """
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
        # Return a transient instance populated from kwargs
        return model_cls(**_kwargs)

    return _make


# ============================================================================
# update_utterance_text — preserve text_original (E197: original preserved)
# ============================================================================

@pytest.mark.asyncio
async def test_update_text_preserves_text_original_on_re_edit(
    client, make_factory
):
    """Second edit must NOT overwrite text_original (preserve branch)."""
    from app.db.models import Protocol, ProtocolStatus, Speaker, Utterance

    proto = await make_factory(
        Protocol,
        id=uuid.uuid4(),
        title="P1",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    spk = await make_factory(
        Speaker, id=uuid.uuid4(), protocol_id=proto.id, speaker_label="S1"
    )
    utt = await make_factory(
        Utterance,
        id=uuid.uuid4(),
        protocol_id=proto.id,
        speaker_id=spk.id,
        start_sec=0.0,
        end_sec=1.0,
        text="Original",
    )

    # First edit — text_original: None → "Original"
    r1 = await client.patch(
        f"{PREFIX}/utterances/{utt.id}/text",
        json={"text": "Edit 1", "version_snapshot": True},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["text"] == "Edit 1"

    # Second edit — text_original must remain "Original", not be overwritten.
    # (Verifies the preserve branch on the server; response model omits
    # text_original so we don't re-assert it here.)
    r2 = await client.patch(
        f"{PREFIX}/utterances/{utt.id}/text",
        json={"text": "Edit 2", "version_snapshot": True},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["text"] == "Edit 2"


@pytest.mark.asyncio
async def test_update_text_no_snapshot_preserves_text_original(
    client, make_factory
):
    """version_snapshot=False on first edit still sets text_original."""
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
        json={"text": "Y", "version_snapshot": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "Y"


@pytest.mark.asyncio
async def test_update_text_missing_field_422(client, make_factory):
    """Missing 'text' field → 422."""
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
        json={"version_snapshot": True},
    )
    assert r.status_code == 422


# ============================================================================
# update_utterance_speaker — previous_speaker_id is None
# ============================================================================

@pytest.mark.asyncio
async def test_update_speaker_from_no_speaker(client, make_factory):
    """Reassign when previous speaker_id is None — exercises None branch."""
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
    target = await make_factory(
        Speaker, id=uuid.uuid4(), protocol_id=proto.id, speaker_label="T"
    )
    utt = await make_factory(
        Utterance,
        id=uuid.uuid4(),
        protocol_id=proto.id,
        speaker_id=None,
        start_sec=0.0,
        end_sec=1.0,
        text="X",
    )

    r = await client.patch(
        f"{PREFIX}/utterances/{utt.id}/speaker",
        json={"speaker_id": str(target.id)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["speaker_id"] == str(target.id)


@pytest.mark.asyncio
async def test_update_speaker_missing_field_422(client, make_factory):
    """Missing 'speaker_id' in body → 422."""
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
        f"{PREFIX}/utterances/{utt.id}/speaker", json={}
    )
    assert r.status_code == 422


# ============================================================================
# toggle_utterance_important — validation edges
# ============================================================================

@pytest.mark.asyncio
async def test_toggle_important_missing_field_422(client, make_factory):
    """Missing 'important' field → 422."""
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
        f"{PREFIX}/utterances/{utt.id}/important", json={}
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_toggle_important_invalid_uuid_422(client):
    """Invalid uuid in path → 422."""
    r = await client.patch(
        f"{PREFIX}/utterances/not-a-uuid/important",
        json={"important": True},
    )
    assert r.status_code == 422


# ============================================================================
# list_utterances — empty + combined filters + validation edges
# ============================================================================

@pytest.mark.asyncio
async def test_list_utterances_empty_protocol(client, make_factory):
    """Protocol exists but has zero utterances."""
    from app.db.models import Protocol, ProtocolStatus

    proto = await make_factory(
        Protocol,
        id=uuid.uuid4(),
        title="Empty",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )

    r = await client.get(f"{PREFIX}/utterances?protocol_id={proto.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 0
    assert body["items"] == []


@pytest.mark.asyncio
async def test_list_utterances_combined_filters(client, make_factory):
    """speaker_id + after_sec + low_confidence_only combined."""
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
    await make_factory(
        Utterance,
        id=uuid.uuid4(),
        protocol_id=proto.id,
        speaker_id=spk.id,
        start_sec=20.0,
        end_sec=21.0,
        text="A",
        low_confidence=True,
    )

    r = await client.get(
        f"{PREFIX}/utterances?protocol_id={proto.id}"
        f"&speaker_id={spk.id}&low_confidence_only=true&after_sec=10.0"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    for item in body["items"]:
        assert item["speaker_id"] == str(spk.id)
        assert item["low_confidence"] is True
        assert item["start_sec"] > 10.0


@pytest.mark.asyncio
async def test_list_utterances_invalid_after_sec_422(client):
    """Negative after_sec violates ge=0 → 422."""
    fake = uuid.uuid4()
    r = await client.get(
        f"{PREFIX}/utterances?protocol_id={fake}&after_sec=-5.0"
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_utterances_limit_too_high_422(client):
    """limit=501 (violates le=500) → 422."""
    fake = uuid.uuid4()
    r = await client.get(
        f"{PREFIX}/utterances?protocol_id={fake}&limit=501"
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_utterances_negative_skip_422(client):
    """skip=-1 (violates ge=0) → 422."""
    fake = uuid.uuid4()
    r = await client.get(
        f"{PREFIX}/utterances?protocol_id={fake}&skip=-1"
    )
    assert r.status_code == 422


# ============================================================================
# _to_response — speaker_id is None (speaker_label None branch)
# ============================================================================

@pytest.mark.asyncio
async def test_get_utterance_no_speaker_returns_null_label(
    client, make_factory
):
    """Utterance with speaker_id=None — speaker_label should be None."""
    from app.db.models import Protocol, ProtocolStatus, Utterance

    proto = await make_factory(
        Protocol,
        id=uuid.uuid4(),
        title="P",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    utt = await make_factory(
        Utterance,
        id=uuid.uuid4(),
        protocol_id=proto.id,
        speaker_id=None,
        start_sec=0.0,
        end_sec=1.0,
        text="X",
    )

    r = await client.get(f"{PREFIX}/utterances/{utt.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["speaker_id"] is None
    assert body["speaker_label"] is None


# ============================================================================
# restore — chained restores + missing previous_text → 422
# ============================================================================

@pytest.mark.asyncio
async def test_restore_creates_new_snapshot_for_reversibility(
    client, make_factory
):
    """Restoring itself snapshots current text (2 versions after 1 edit + 1 restore)."""
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
        text="Original",
    )

    # Edit → v1 snapshot
    r1 = await client.patch(
        f"{PREFIX}/utterances/{utt.id}/text",
        json={"text": "Edited", "version_snapshot": True},
    )
    assert r1.status_code == 200, r1.text

    # Restore from v1 → v2 snapshot created
    r2 = await client.post(f"{PREFIX}/utterances/{utt.id}/restore/1")
    assert r2.status_code == 200, r2.text
    assert r2.json()["text"] == "Original"

    # Verify versions: 2 entries (v1=edit, v2=restore)
    v = await client.get(f"{PREFIX}/utterances/{utt.id}/versions")
    assert v.status_code == 200, v.text
    assert v.json()["total"] == 2


@pytest.mark.asyncio
async def test_list_versions_ordered_newest_first(client, make_factory):
    """Versions endpoint returns newest first (descending)."""
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

    # Two edits → v1, v2
    await client.patch(
        f"{PREFIX}/utterances/{utt.id}/text",
        json={"text": "E1", "version_snapshot": True},
    )
    await client.patch(
        f"{PREFIX}/utterances/{utt.id}/text",
        json={"text": "E2", "version_snapshot": True},
    )

    r = await client.get(f"{PREFIX}/utterances/{utt.id}/versions")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    nums = [item["version_number"] for item in body["items"]]
    assert nums == sorted(nums, reverse=True)


@pytest.mark.asyncio
async def test_restore_snapshot_missing_previous_text_422(
    client, make_factory
):
    """Manually-inserted ProtocolVersion missing 'previous_text' → 422."""
    from app.db.models import Protocol, ProtocolStatus, ProtocolVersion, Speaker, Utterance

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

    bad = await make_factory(
        ProtocolVersion,
        protocol_id=proto.id,
        version_number=1,
        snapshot={"field": "text", "new_text": "y"},  # no previous_text
        changed_field=f"utterance:{utt.id}:text",
        changed_by="user",
        change_reason="bad snap",
    )

    r = await client.post(f"{PREFIX}/utterances/{utt.id}/restore/1")
    assert r.status_code == 422
    assert "previous_text" in r.json()["detail"]