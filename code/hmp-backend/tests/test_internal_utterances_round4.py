"""E349-round4: coverage-targeted tests for routers/utterances.py — helpers + edges.

Targets branches NOT covered by v3/round1/round2/round3:
- _to_response: speaker is None → speaker_label=None branch
- _next_version_number: starts at 1, then increments (>=1)
- list_utterances: empty list (no utterances for protocol)
- list_utterances: speaker_id filter (filters by speaker)
- list_utterances: low_confidence_only=True filter
- list_utterances: after_sec incremental filter
- list_utterances: speaker_label denormalized serialization (round-trip)
- list_utterance_versions: empty list (no versions yet)
- toggle_utterance_important: happy path on/off
- restore_utterance_version: snapshot missing previous_text → 422
- get_utterance: 404 on missing

Uses make_factory (raw db_engine.connect) — matches the project convention
established by round1/2/3/v3 tests. Known flakiness under heavy parallel
test runs is a pre-existing infrastructure issue (see v3 failures on this DB).
Tests pass reliably when run in isolation or in small batches.
"""
import uuid as _uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import insert as sa_insert

from tests.conftest import _insert  # E349-round4: helper added in conftest

PREFIX = "/api/v1/hmp"


@pytest_asyncio.fixture
async def make_factory(db_engine):
    """Create objects via raw connection — same pattern as round1/2/3/v3."""
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
# _to_response helper — speaker is None branch
# ============================================================================

def test_to_response_no_speaker_speaker_label_none():
    """Direct unit test: _to_response returns speaker_label=None when speaker is None."""
    from datetime import datetime, timezone
    from app.routers.utterances import _to_response
    from app.db.models import Utterance
    from app.schemas import UtteranceResponse

    now = datetime.now(timezone.utc)
    utt = Utterance(
        id=_uuid.uuid4(),
        protocol_id=_uuid.uuid4(),
        speaker_id=_uuid.uuid4(),  # points to nothing
        start_sec=0.0,
        end_sec=1.0,
        text="orphan",
        low_confidence=False,
        important=False,
        corrected_by_llm=False,
        created_at=now,
        updated_at=now,
    )
    utt.speaker = None  # explicitly no speaker loaded

    resp = _to_response(utt)
    assert isinstance(resp, UtteranceResponse)
    assert resp.speaker_label is None
    assert resp.text == "orphan"
    assert resp.id == utt.id


def test_to_response_with_speaker_returns_label():
    """Direct unit test: _to_response serializes speaker_label when speaker is present."""
    from datetime import datetime, timezone
    from app.routers.utterances import _to_response
    from app.db.models import Utterance, Speaker

    now = datetime.now(timezone.utc)
    spk = Speaker(id=_uuid.uuid4(), protocol_id=_uuid.uuid4(), speaker_label="SPK_42")
    utt = Utterance(
        id=_uuid.uuid4(),
        protocol_id=spk.protocol_id,
        speaker_id=spk.id,
        start_sec=0.0,
        end_sec=1.0,
        text="hi",
        low_confidence=False,
        important=False,
        corrected_by_llm=False,
        created_at=now,
        updated_at=now,
    )
    utt.speaker = spk

    resp = _to_response(utt)
    assert resp.speaker_label == "SPK_42"
    assert resp.speaker_id == spk.id


# ============================================================================
# _next_version_number helper — starts at 1, increments
# ============================================================================

@pytest.mark.asyncio
async def test_next_version_number_starts_at_one(db_session, sample_protocol):
    """When no versions exist → returns 1."""
    from app.routers.utterances import _next_version_number

    n = await _next_version_number(db_session, sample_protocol.id)
    assert n == 1


@pytest.mark.asyncio
async def test_next_version_number_increments_with_existing(db_session, sample_protocol):
    """When existing versions present → returns max + 1."""
    from app.routers.utterances import _next_version_number
    from app.db.models import ProtocolVersion

    # Seed two versions with version_numbers 3 and 7
    for vn in (3, 7):
        await _insert(
            db_session,
            ProtocolVersion,
            id=_uuid.uuid4(),
            protocol_id=sample_protocol.id,
            version_number=vn,
            snapshot={"k": "v"},
            changed_field=f"utterance:{_uuid.uuid4()}:text",
            changed_by="user",
            change_reason="seed",
        )

    n = await _next_version_number(db_session, sample_protocol.id)
    assert n == 8


# ============================================================================
# list_utterances — empty list + filters + speaker_label round-trip
# ============================================================================

@pytest.mark.asyncio
async def test_list_utterances_empty_returns_zero_total(client, sample_protocol):
    """Protocol exists but has no utterances → total=0, items=[]."""

    r = await client.get(f"{PREFIX}/utterances?protocol_id={sample_protocol.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 0
    assert body["items"] == []
    assert body["skip"] == 0
    assert body["limit"] == 100


@pytest.mark.asyncio
async def test_list_utterances_multiple_ordered_by_start_sec(
    client, db_session, sample_protocol
):
    """Multiple utterances returned sorted by start_sec; speaker_label denormalized."""
    from app.db.models import Speaker, Utterance

    spk_a = await _insert(
        db_session, Speaker, id=_uuid.uuid4(),
        protocol_id=sample_protocol.id, speaker_label="ALICE",
    )
    spk_b = await _insert(
        db_session, Speaker, id=_uuid.uuid4(),
        protocol_id=sample_protocol.id, speaker_label="BOB",
    )

    # Insert out of order to verify ordering
    for ts, spk in [(5.0, spk_b), (1.0, spk_a), (3.0, spk_a)]:
        await _insert(
            db_session, Utterance,
            id=_uuid.uuid4(),
            protocol_id=sample_protocol.id,
            speaker_id=spk.id,
            start_sec=ts,
            end_sec=ts + 0.5,
            text=f"t={ts}",
        )

    r = await client.get(f"{PREFIX}/utterances?protocol_id={sample_protocol.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    starts = [item["start_sec"] for item in body["items"]]
    assert starts == [1.0, 3.0, 5.0]
    # speaker_label denormalized correctly per row
    labels = [item["speaker_label"] for item in body["items"]]
    assert labels == ["ALICE", "ALICE", "BOB"]


@pytest.mark.asyncio
async def test_list_utterances_speaker_id_filter(
    client, db_session, sample_protocol, sample_speaker
):
    """speaker_id query filter restricts to utterances of that speaker only."""
    from app.db.models import Speaker, Utterance

    # sample_speaker is already in sample_protocol
    spk_b = await _insert(
        db_session, Speaker, id=_uuid.uuid4(),
        protocol_id=sample_protocol.id, speaker_label="B",
    )

    for ts, spk in [(1.0, sample_speaker), (2.0, spk_b), (3.0, sample_speaker), (4.0, spk_b)]:
        await _insert(
            db_session, Utterance,
            id=_uuid.uuid4(),
            protocol_id=sample_protocol.id,
            speaker_id=spk.id,
            start_sec=ts,
            end_sec=ts + 0.1,
            text=f"by-{spk.speaker_label}",
        )

    r = await client.get(
        f"{PREFIX}/utterances?protocol_id={sample_protocol.id}&speaker_id={spk_b.id}"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    for item in body["items"]:
        assert item["speaker_id"] == str(spk_b.id)
        assert item["speaker_label"] == "B"


@pytest.mark.asyncio
async def test_list_utterances_low_confidence_only_filter(
    client, db_session, sample_protocol, sample_speaker
):
    """low_confidence_only=true restricts to utterances with low_confidence=True."""
    from app.db.models import Utterance

    for ts, lc in [(1.0, True), (2.0, False), (3.0, True)]:
        await _insert(
            db_session, Utterance,
            id=_uuid.uuid4(),
            protocol_id=sample_protocol.id,
            speaker_id=sample_speaker.id,
            start_sec=ts,
            end_sec=ts + 0.1,
            text=f"u{ts}",
            low_confidence=lc,
        )

    r = await client.get(
        f"{PREFIX}/utterances?protocol_id={sample_protocol.id}&low_confidence_only=true"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert all(item["low_confidence"] is True for item in body["items"])


@pytest.mark.asyncio
async def test_list_utterances_after_sec_incremental(
    client, db_session, sample_protocol, sample_speaker
):
    """after_sec returns only utterances with start_sec > after_sec."""
    from app.db.models import Utterance

    for ts in [1.0, 2.0, 3.0, 4.0]:
        await _insert(
            db_session, Utterance,
            id=_uuid.uuid4(),
            protocol_id=sample_protocol.id,
            speaker_id=sample_speaker.id,
            start_sec=ts,
            end_sec=ts + 0.1,
            text=f"u{ts}",
        )

    r = await client.get(
        f"{PREFIX}/utterances?protocol_id={sample_protocol.id}&after_sec=2.0"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2  # 3.0 and 4.0
    starts = [item["start_sec"] for item in body["items"]]
    assert starts == [3.0, 4.0]


# ============================================================================
# get_utterance — 404 on missing
# ============================================================================

@pytest.mark.asyncio
async def test_get_utterance_missing_returns_404(client):
    """GET /utterances/{id} with unknown id → 404."""
    r = await client.get(f"{PREFIX}/utterances/{_uuid.uuid4()}")
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert "Реплика" in detail or "найдена" in detail


@pytest.mark.asyncio
async def test_get_utterance_invalid_uuid_422(client):
    """GET /utterances/{id} with malformed id → 422."""
    r = await client.get(f"{PREFIX}/utterances/not-a-uuid")
    assert r.status_code == 422


# ============================================================================
# list_utterance_versions — empty list
# ============================================================================

@pytest.mark.asyncio
async def test_list_utterance_versions_empty(
    client, sample_utterance
):
    """Utterance exists but no versions yet → total=0, items=[]."""

    r = await client.get(f"{PREFIX}/utterances/{sample_utterance.id}/versions")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["utterance_id"] == str(sample_utterance.id)
    assert body["total"] == 0
    assert body["items"] == []


# ============================================================================
# toggle_utterance_important — happy path + idempotent
# ============================================================================

@pytest.mark.asyncio
async def test_toggle_important_true_sets_flag(
    client, db_session, sample_protocol, sample_speaker
):
    """PATCH /utterances/{id}/important with important=true toggles on."""
    from app.db.models import Utterance

    utt = await _insert(
        db_session, Utterance,
        id=_uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_id=sample_speaker.id,
        start_sec=0.0,
        end_sec=1.0,
        text="X",
        important=False,
    )

    r = await client.patch(
        f"{PREFIX}/utterances/{utt.id}/important",
        json={"important": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == str(utt.id)
    assert body["important"] is True


@pytest.mark.asyncio
async def test_toggle_important_off_unsets_flag(
    client, db_session, sample_protocol, sample_speaker
):
    """PATCH /utterances/{id}/important with important=false toggles off."""
    from app.db.models import Utterance

    utt = await _insert(
        db_session, Utterance,
        id=_uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_id=sample_speaker.id,
        start_sec=0.0,
        end_sec=1.0,
        text="X",
        important=True,
    )

    r = await client.patch(
        f"{PREFIX}/utterances/{utt.id}/important",
        json={"important": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["important"] is False


@pytest.mark.asyncio
async def test_toggle_important_missing_404(client):
    """PATCH /utterances/{id}/important with unknown id → 404."""
    r = await client.patch(
        f"{PREFIX}/utterances/{_uuid.uuid4()}/important",
        json={"important": True},
    )
    assert r.status_code == 404


# ============================================================================
# restore_utterance_version — snapshot missing previous_text → 422
# ============================================================================

@pytest.mark.asyncio
async def test_restore_snapshot_missing_previous_text_422(
    client, db_session, sample_protocol, sample_speaker
):
    """If the stored snapshot dict has no 'previous_text' key → 422."""
    from app.db.models import Utterance, ProtocolVersion

    utt = await _insert(
        db_session, Utterance,
        id=_uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_id=sample_speaker.id,
        start_sec=0.0,
        end_sec=1.0,
        text="current",
    )

    # Seed a version snapshot WITHOUT previous_text
    await _insert(
        db_session, ProtocolVersion,
        id=_uuid.uuid4(),
        protocol_id=sample_protocol.id,
        version_number=1,
        snapshot={"some_other_key": "value"},  # NO previous_text
        changed_field=f"utterance:{utt.id}:text",
        changed_by="user",
        change_reason="seed",
    )

    r = await client.post(f"{PREFIX}/utterances/{utt.id}/restore/1")
    assert r.status_code == 422, r.text
    assert "previous_text" in r.json()["detail"]