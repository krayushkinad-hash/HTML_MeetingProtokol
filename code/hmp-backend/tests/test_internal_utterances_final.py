"""Final coverage push for app/routers/utterances.py — target 70%+.

Targets branches NOT covered by v3/round1/round2/round3/round4:

- list_utterances: protocol 404 (118-122), combined filters (124-136)
- get_utterance: success path (line 168)
- update_utterance_text: no-op when text unchanged (188-192)
- update_utterance_text: first edit sets text_original (194-198)
- update_utterance_text: snapshot_taken=True branch (204-221)
- update_utterance_text: commit + log + reload (223-235)
- update_utterance_speaker: target speaker 404 (254-258)
- update_utterance_speaker: wrong protocol 400 (259-263)
- update_utterance_speaker: happy path (265-286)
- list_utterance_versions: non-empty result (301-323)
- restore_utterance_version: version_number not found (360-365)
- restore_utterance_version: happy path with log (367-412)
- restore_utterance_version: version_number < 1 → 422 (345-349)
- toggle_utterance_important: log path (442-449)
"""
import uuid as _uuid

import pytest
import pytest_asyncio

from tests.conftest import _insert

PREFIX = "/api/v1/hmp"


# ============================================================================
# list_utterances — protocol not found + combined filters
# ============================================================================

@pytest.mark.asyncio
async def test_list_utterances_protocol_not_found_404(client):
    """list_utterances returns 404 when protocol_id is unknown."""
    r = await client.get(f"{PREFIX}/utterances?protocol_id={_uuid.uuid4()}")
    assert r.status_code == 404
    assert "Протокол" in r.json()["detail"]


@pytest.mark.asyncio
async def test_list_utterances_combined_filters_all_three(
    client, db_session, sample_protocol, sample_speaker
):
    """Combined filters: speaker_id + low_confidence_only + after_sec.

    Seeds 6 utterances; only one matches all three filters → verify only it
    is in the result and total reflects the same.
    """
    from app.db.models import Speaker, Utterance

    spk_other = await _insert(
        db_session, Speaker,
        id=_uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_label="OTHER",
    )

    # target row (matches all filters): speaker=sample_speaker, lc=True, sec>2.0
    target = await _insert(
        db_session, Utterance,
        id=_uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_id=sample_speaker.id,
        start_sec=3.0,
        end_sec=3.5,
        text="target",
        low_confidence=True,
    )
    # same speaker, low_conf but before threshold (excluded by after_sec)
    await _insert(
        db_session, Utterance,
        id=_uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_id=sample_speaker.id,
        start_sec=1.0,
        end_sec=1.5,
        text="too-early",
        low_confidence=True,
    )
    # same speaker, after threshold, but NOT low_confidence (excluded)
    await _insert(
        db_session, Utterance,
        id=_uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_id=sample_speaker.id,
        start_sec=4.0,
        end_sec=4.5,
        text="high-conf",
        low_confidence=False,
    )
    # different speaker, after threshold, low_conf (excluded by speaker_id)
    await _insert(
        db_session, Utterance,
        id=_uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_id=spk_other.id,
        start_sec=5.0,
        end_sec=5.5,
        text="other-speaker",
        low_confidence=True,
    )

    r = await client.get(
        f"{PREFIX}/utterances"
        f"?protocol_id={sample_protocol.id}"
        f"&speaker_id={sample_speaker.id}"
        f"&low_confidence_only=true"
        f"&after_sec=2.0"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == str(target.id)
    assert body["items"][0]["speaker_label"] == sample_speaker.speaker_label


# ============================================================================
# get_utterance — happy path
# ============================================================================

@pytest.mark.asyncio
async def test_get_utterance_success(client, sample_utterance):
    """GET /utterances/{id} returns the UtteranceResponse payload."""
    r = await client.get(f"{PREFIX}/utterances/{sample_utterance.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == str(sample_utterance.id)
    assert body["text"] == sample_utterance.text
    assert body["speaker_label"] == sample_utterance.speaker.speaker_label
    assert body["protocol_id"] == str(sample_utterance.protocol_id)


# ============================================================================
# update_utterance_text — no-op, first-edit text_original, snapshot branch
# ============================================================================

@pytest.mark.asyncio
async def test_update_text_no_op_when_text_unchanged(
    client, sample_utterance, db_session
):
    """If new text equals current text → no commit, no snapshot, returns current."""
    r = await client.patch(
        f"{PREFIX}/utterances/{sample_utterance.id}/text",
        json={"text": sample_utterance.text, "version_snapshot": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] == sample_utterance.text
    assert body["id"] == str(sample_utterance.id)


@pytest.mark.asyncio
async def test_update_text_first_edit_sets_text_original(
    client, db_session, sample_protocol, sample_speaker
):
    """On the first edit, text_original is set to the previous text."""
    from app.db.models import Utterance

    original = "first transcription"
    utt = await _insert(
        db_session, Utterance,
        id=_uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_id=sample_speaker.id,
        start_sec=0.0,
        end_sec=1.0,
        text=original,
        text_original=None,  # first edit
    )

    r = await client.patch(
        f"{PREFIX}/utterances/{utt.id}/text",
        json={"text": "edited text", "version_snapshot": False},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] == "edited text"
    assert body["text_original"] == original  # preserved original


@pytest.mark.asyncio
async def test_update_text_with_snapshot_creates_protobuf(
    client, db_session, sample_protocol, sample_speaker
):
    """With version_snapshot=True, a ProtocolVersion row is written."""
    from app.db.models import Utterance, ProtocolVersion
    from sqlalchemy import select, func

    utt = await _insert(
        db_session, Utterance,
        id=_uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_id=sample_speaker.id,
        start_sec=0.0,
        end_sec=1.0,
        text="old-text",
    )

    r = await client.patch(
        f"{PREFIX}/utterances/{utt.id}/text",
        json={"text": "new-text", "version_snapshot": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] == "new-text"

    # Verify ProtocolVersion row was created with the expected fields
    result = await db_session.execute(
        select(ProtocolVersion).where(
            ProtocolVersion.protocol_id == sample_protocol.id,
            ProtocolVersion.changed_field == f"utterance:{utt.id}:text",
        )
    )
    versions = result.scalars().all()
    assert len(versions) == 1
    v = versions[0]
    assert v.snapshot["previous_text"] == "old-text"
    assert v.snapshot["new_text"] == "new-text"
    assert v.changed_by == "user"
    assert "US-048" in v.change_reason

    # version_number should be 1 (no prior versions)
    count_q = select(func.count()).select_from(ProtocolVersion).where(
        ProtocolVersion.protocol_id == sample_protocol.id
    )
    total_versions = (await db_session.execute(count_q)).scalar()
    assert total_versions == 1


# ============================================================================
# update_utterance_speaker — 404, 400, happy path
# ============================================================================

@pytest.mark.asyncio
async def test_update_speaker_target_not_found_404(client, sample_utterance):
    """update_speaker raises 404 when target speaker_id does not exist."""
    r = await client.patch(
        f"{PREFIX}/utterances/{sample_utterance.id}/speaker",
        json={"speaker_id": str(_uuid.uuid4())},
    )
    assert r.status_code == 404
    assert "Целевой" in r.json()["detail"] or "не найден" in r.json()["detail"]


@pytest.mark.asyncio
async def test_update_speaker_wrong_protocol_400(
    client, db_session, sample_utterance
):
    """update_speaker raises 400 when target speaker belongs to a different protocol."""
    from app.db.models import Protocol, Speaker
    from datetime import datetime, timezone

    # Create a different protocol + a speaker that belongs to it
    other_protocol = await _insert(
        db_session, Protocol,
        id=_uuid.uuid4(),
        title="Other Protocol",
        date=datetime.now(timezone.utc).date(),
    )
    other_speaker = await _insert(
        db_session, Speaker,
        id=_uuid.uuid4(),
        protocol_id=other_protocol.id,
        speaker_label="OTHER_SPK",
    )

    r = await client.patch(
        f"{PREFIX}/utterances/{sample_utterance.id}/speaker",
        json={"speaker_id": str(other_speaker.id)},
    )
    assert r.status_code == 400
    assert "другому протоколу" in r.json()["detail"]


@pytest.mark.asyncio
async def test_update_speaker_happy_path_reassigns(
    client, db_session, sample_utterance
):
    """update_speaker successfully reassigns speaker_id."""
    from app.db.models import Speaker

    # Create a second speaker in the same protocol
    spk_b = await _insert(
        db_session, Speaker,
        id=_uuid.uuid4(),
        protocol_id=sample_utterance.protocol_id,
        speaker_label="NEW_SPK",
    )

    r = await client.patch(
        f"{PREFIX}/utterances/{sample_utterance.id}/speaker",
        json={"speaker_id": str(spk_b.id)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["speaker_id"] == str(spk_b.id)
    assert body["speaker_label"] == "NEW_SPK"


# ============================================================================
# list_utterance_versions — non-empty + ordering
# ============================================================================

@pytest.mark.asyncio
async def test_list_utterance_versions_non_empty(
    client, db_session, sample_utterance
):
    """Seed two version rows; list returns them newest-first."""
    from app.db.models import ProtocolVersion

    await _insert(
        db_session, ProtocolVersion,
        id=_uuid.uuid4(),
        protocol_id=sample_utterance.protocol_id,
        version_number=1,
        snapshot={"previous_text": "v1-old", "new_text": "v1-new"},
        changed_field=f"utterance:{sample_utterance.id}:text",
        changed_by="user",
        change_reason="first edit",
    )
    await _insert(
        db_session, ProtocolVersion,
        id=_uuid.uuid4(),
        protocol_id=sample_utterance.protocol_id,
        version_number=2,
        snapshot={"previous_text": "v2-old", "new_text": "v2-new"},
        changed_field=f"utterance:{sample_utterance.id}:text",
        changed_by="user",
        change_reason="second edit",
    )

    r = await client.get(
        f"{PREFIX}/utterances/{sample_utterance.id}/versions"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["utterance_id"] == str(sample_utterance.id)
    assert body["total"] == 2
    assert len(body["items"]) == 2
    # newest-first ordering by version_number DESC
    assert body["items"][0]["version_number"] == 2
    assert body["items"][1]["version_number"] == 1


# ============================================================================
# restore_utterance_version — version_number < 1, version not found, happy path
# ============================================================================

@pytest.mark.asyncio
async def test_restore_version_number_below_one_422(client, sample_utterance):
    """version_number < 1 → 422."""
    r = await client.post(f"{PREFIX}/utterances/{sample_utterance.id}/restore/0")
    assert r.status_code == 422
    assert "положительным" in r.json()["detail"]


@pytest.mark.asyncio
async def test_restore_version_not_found_404(client, sample_utterance):
    """Valid version_number but no matching ProtocolVersion row → 404."""
    r = await client.post(f"{PREFIX}/utterances/{sample_utterance.id}/restore/999")
    assert r.status_code == 404
    assert "999" in r.json()["detail"]


@pytest.mark.asyncio
async def test_restore_version_happy_path(
    client, db_session, sample_utterance
):
    """Happy path: seed a snapshot, restore to previous_text, verify text replaced
    and a new snapshot row is written."""
    from app.db.models import ProtocolVersion

    # Seed a version snapshot with previous_text.
    pv = await _insert(
        db_session, ProtocolVersion,
        id=_uuid.uuid4(),
        protocol_id=sample_utterance.protocol_id,
        version_number=1,
        snapshot={
            "utterance_id": str(sample_utterance.id),
            "field": "text",
            "previous_text": "original-text",
            "new_text": "edited-text",
        },
        changed_field=f"utterance:{sample_utterance.id}:text",
        changed_by="user",
        change_reason="seed",
    )
    # current text starts as sample_utterance.text = "Test utterance"
    r = await client.post(
        f"{PREFIX}/utterances/{sample_utterance.id}/restore/1"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # text should be the restored "original-text"
    assert body["text"] == "original-text"
    assert body["id"] == str(sample_utterance.id)

    # Now confirm via list_utterance_versions that a SECOND snapshot was
    # written by the restore itself (covers lines 379-412).
    r2 = await client.get(
        f"{PREFIX}/utterances/{sample_utterance.id}/versions"
    )
    assert r2.status_code == 200, r2.text
    items = r2.json()["items"]
    assert len(items) == 2
    # Newest-first; the restore snapshot is version_number=2
    restore_snapshot = [v for v in items if v["version_number"] == 2][0]
    assert restore_snapshot["snapshot"]["previous_text"] == "Test utterance"
    assert restore_snapshot["snapshot"]["new_text"] == "original-text"
    assert restore_snapshot["snapshot"]["restored_from_version"] == 1
    assert "restore from version 1" in restore_snapshot["change_reason"]


# ============================================================================
# toggle_utterance_important — log path (commit + log line)
# ============================================================================

@pytest.mark.asyncio
async def test_toggle_important_commit_and_log_path(
    client, db_session, sample_protocol, sample_speaker
):
    """Toggle important: covers commit + log path (lines 437-449)."""
    from app.db.models import Utterance

    utt = await _insert(
        db_session, Utterance,
        id=_uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_id=sample_speaker.id,
        start_sec=0.0,
        end_sec=1.0,
        text="hi",
        important=False,
    )

    # Toggle ON
    r1 = await client.patch(
        f"{PREFIX}/utterances/{utt.id}/important",
        json={"important": True},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["important"] is True

    # Toggle OFF — exercises the same code path again
    r2 = await client.patch(
        f"{PREFIX}/utterances/{utt.id}/important",
        json={"important": False},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["important"] is False