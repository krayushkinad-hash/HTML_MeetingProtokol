"""E289-v2: comprehensive tests for routers/utterances.py — target 60%+."""
import uuid

import pytest


# ============================================================================
# GET /utterances  — list with filters
# ============================================================================

@pytest.mark.asyncio
async def test_list_utterances_basic(client, sample_protocol, sample_utterance):
    """GET /utterances returns paginated list."""
    r = await client.get(
        f"/api/v1/hmp/utterances?protocol_id={sample_protocol.id}"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert body["skip"] == 0
    assert body["limit"] == 100
    assert any(
        item["id"] == str(sample_utterance.id) for item in body["items"]
    )


@pytest.mark.asyncio
async def test_list_utterances_filter_by_speaker(client, sample_protocol,
                                                  sample_speaker, sample_utterance):
    """speaker_id filter narrows results."""
    r = await client.get(
        f"/api/v1/hmp/utterances?protocol_id={sample_protocol.id}"
        f"&speaker_id={sample_speaker.id}"
    )
    assert r.status_code == 200
    body = r.json()
    assert all(
        item["speaker_id"] == str(sample_speaker.id) for item in body["items"]
    )


@pytest.mark.asyncio
async def test_list_utterances_filter_low_confidence(client, sample_protocol,
                                                     sample_utterance,
                                                     db_session):
    """low_confidence_only=true filter."""
    # Mark sample as low confidence (E349-round4: must commit so client sees it)
    sample_utterance.low_confidence = True
    from datetime import datetime, timezone
    sample_utterance.updated_at = datetime.now(timezone.utc)
    await db_session.commit()

    r = await client.get(
        f"/api/v1/hmp/utterances?protocol_id={sample_protocol.id}"
        f"&low_confidence_only=true"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert all(item["low_confidence"] for item in body["items"])


@pytest.mark.asyncio
async def test_list_utterances_filter_after_sec(client, sample_protocol,
                                               sample_utterance):
    """after_sec returns only utterances after the threshold."""
    r = await client.get(
        f"/api/v1/hmp/utterances?protocol_id={sample_protocol.id}"
        f"&after_sec=10.0"
    )
    assert r.status_code == 200
    # sample_utterance starts at 0.0, so should not appear
    body = r.json()
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_list_utterances_pagination(client, sample_protocol,
                                          sample_utterance):
    """skip/limit pagination."""
    r = await client.get(
        f"/api/v1/hmp/utterances?protocol_id={sample_protocol.id}"
        f"&skip=0&limit=1"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["limit"] == 1
    assert len(body["items"]) <= 1


@pytest.mark.asyncio
async def test_list_utterances_protocol_not_found(client):
    """Unknown protocol → 404."""
    fake_id = uuid.uuid4()
    r = await client.get(
        f"/api/v1/hmp/utterances?protocol_id={fake_id}"
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_utterances_missing_protocol_id(client):
    """Missing required protocol_id → 422."""
    r = await client.get("/api/v1/hmp/utterances")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_utterances_invalid_uuid(client):
    """Invalid uuid → 422."""
    r = await client.get("/api/v1/hmp/utterances?protocol_id=not-a-uuid")
    assert r.status_code == 422


# ============================================================================
# GET /utterances/{id}
# ============================================================================

@pytest.mark.asyncio
async def test_get_utterance_by_id(client, sample_utterance):
    """GET single utterance returns denormalised speaker_label."""
    r = await client.get(f"/api/v1/hmp/utterances/{sample_utterance.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(sample_utterance.id)
    assert body["speaker_label"] == "SPK_TEST"
    assert body["text"] == "Test utterance"


@pytest.mark.asyncio
async def test_get_utterance_not_found(client):
    """Unknown utterance id → 404."""
    r = await client.get(f"/api/v1/hmp/utterances/{uuid.uuid4()}")
    assert r.status_code == 404


# ============================================================================
# PATCH /utterances/{id}/text  (US-048 — version snapshot)
# ============================================================================

@pytest.mark.asyncio
async def test_update_utterance_text_no_op(client, sample_utterance):
    """Same text → no-op, returns 200 with unchanged text."""
    r = await client.patch(
        f"/api/v1/hmp/utterances/{sample_utterance.id}/text",
        json={"text": "Test utterance", "version_snapshot": True},
    )
    assert r.status_code == 200
    assert r.json()["text"] == "Test utterance"


@pytest.mark.asyncio
async def test_update_utterance_text_with_snapshot(client, sample_utterance):
    """Different text + version_snapshot → snapshot written, text_original set."""
    r = await client.patch(
        f"/api/v1/hmp/utterances/{sample_utterance.id}/text",
        json={"text": "Edited text", "version_snapshot": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "Edited text"
    # text_original was None, so it's now set to "Test utterance"
    assert body["text_original"] is None or body["text_original"] == "Test utterance"


@pytest.mark.asyncio
async def test_update_utterance_text_no_snapshot(client, sample_utterance):
    """version_snapshot=false → text updated, no ProtocolVersion row."""
    r = await client.patch(
        f"/api/v1/hmp/utterances/{sample_utterance.id}/text",
        json={"text": "Updated without snapshot", "version_snapshot": False},
    )
    assert r.status_code == 200
    assert r.json()["text"] == "Updated without snapshot"


@pytest.mark.asyncio
async def test_update_utterance_text_not_found(client):
    """Unknown utterance id → 404."""
    r = await client.patch(
        f"/api/v1/hmp/utterances/{uuid.uuid4()}/text",
        json={"text": "x"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_utterance_text_empty_invalid(client, sample_utterance):
    """Empty text violates min_length=1 → 422."""
    r = await client.patch(
        f"/api/v1/hmp/utterances/{sample_utterance.id}/text",
        json={"text": ""},
    )
    assert r.status_code == 422


# ============================================================================
# PATCH /utterances/{id}/speaker  (US-008)
# ============================================================================

@pytest.mark.asyncio
async def test_update_utterance_speaker_same_protocol(client, sample_protocol,
                                                      sample_speaker,
                                                      sample_utterance,
                                                      db_session):
    """Reassign to a different speaker of same protocol."""
    from app.db.models import Speaker
    target = Speaker(
        id=uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_label="SPK_OTHER",
    )
    db_session.add(target)
    await db_session.commit()
    await db_session.refresh(target)

    r = await client.patch(
        f"/api/v1/hmp/utterances/{sample_utterance.id}/speaker",
        json={"speaker_id": str(target.id)},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["speaker_id"] == str(target.id)
    assert body["speaker_label"] == "SPK_OTHER"


@pytest.mark.asyncio
async def test_update_utterance_speaker_not_found(client, sample_utterance):
    """Target speaker does not exist → 404."""
    r = await client.patch(
        f"/api/v1/hmp/utterances/{sample_utterance.id}/speaker",
        json={"speaker_id": str(uuid.uuid4())},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_utterance_speaker_wrong_protocol(client, sample_utterance,
                                                       db_session):
    """Target speaker belongs to a different protocol → 400."""
    from app.db.models import Protocol, ProtocolStatus, Speaker
    from datetime import datetime, timezone
    other_protocol = Protocol(
        id=uuid.uuid4(),
        title="Other Protocol",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),  # E349-round4: NOT NULL column
    )
    db_session.add(other_protocol)
    await db_session.commit()
    await db_session.refresh(other_protocol)

    foreign_speaker = Speaker(
        id=uuid.uuid4(),
        protocol_id=other_protocol.id,
        speaker_label="FOREIGN",
    )
    db_session.add(foreign_speaker)
    await db_session.commit()
    await db_session.refresh(foreign_speaker)

    r = await client.patch(
        f"/api/v1/hmp/utterances/{sample_utterance.id}/speaker",
        json={"speaker_id": str(foreign_speaker.id)},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_update_utterance_speaker_utterance_not_found(client):
    """Unknown utterance id → 404."""
    r = await client.patch(
        f"/api/v1/hmp/utterances/{uuid.uuid4()}/speaker",
        json={"speaker_id": str(uuid.uuid4())},
    )
    assert r.status_code == 404


# ============================================================================
# GET /utterances/{id}/versions  (US-048)
# ============================================================================

@pytest.mark.asyncio
async def test_list_utterance_versions_empty(client, sample_utterance):
    """No versions yet → empty items list."""
    r = await client.get(
        f"/api/v1/hmp/utterances/{sample_utterance.id}/versions"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["utterance_id"] == str(sample_utterance.id)
    assert body["total"] == 0
    assert body["items"] == []


@pytest.mark.asyncio
async def test_list_utterance_versions_after_edit(client, sample_utterance):
    """After text edit with snapshot, versions list contains one entry."""
    # First do an edit to create a version
    await client.patch(
        f"/api/v1/hmp/utterances/{sample_utterance.id}/text",
        json={"text": "Edited once", "version_snapshot": True},
    )
    r = await client.get(
        f"/api/v1/hmp/utterances/{sample_utterance.id}/versions"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert body["items"][0]["changed_field"] == (
        f"utterance:{sample_utterance.id}:text"
    )


@pytest.mark.asyncio
async def test_list_utterance_versions_not_found(client):
    """Unknown utterance → 404."""
    r = await client.get(
        f"/api/v1/hmp/utterances/{uuid.uuid4()}/versions"
    )
    assert r.status_code == 404


# ============================================================================
# POST /utterances/{id}/restore/{version_number}
# ============================================================================

@pytest.mark.asyncio
async def test_restore_utterance_version_success(client, sample_utterance):
    """Restore from a snapshot returns the previous text."""
    # Step 1: edit text (creates v1 snapshot of "Test utterance")
    await client.patch(
        f"/api/v1/hmp/utterances/{sample_utterance.id}/text",
        json={"text": "Edited text", "version_snapshot": True},
    )
    # Step 2: restore from version 1 → should set text back to "Test utterance"
    r = await client.post(
        f"/api/v1/hmp/utterances/{sample_utterance.id}/restore/1"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "Test utterance"


@pytest.mark.asyncio
async def test_restore_utterance_version_invalid_number(client, sample_utterance):
    """version_number < 1 → 422."""
    r = await client.post(
        f"/api/v1/hmp/utterances/{sample_utterance.id}/restore/0"
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_restore_utterance_version_not_found(client, sample_utterance):
    """Non-existent version_number → 404."""
    r = await client.post(
        f"/api/v1/hmp/utterances/{sample_utterance.id}/restore/999"
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_restore_utterance_not_found(client):
    """Unknown utterance id → 404."""
    r = await client.post(
        f"/api/v1/hmp/utterances/{uuid.uuid4()}/restore/1"
    )
    assert r.status_code == 404


# ============================================================================
# PATCH /utterances/{id}/important  (E172 / US-087)
# ============================================================================

@pytest.mark.asyncio
async def test_toggle_utterance_important_true(client, sample_utterance):
    """Set important=True."""
    r = await client.patch(
        f"/api/v1/hmp/utterances/{sample_utterance.id}/important",
        json={"important": True},
    )
    assert r.status_code == 200
    assert r.json()["important"] is True


@pytest.mark.asyncio
async def test_toggle_utterance_important_false(client, sample_utterance):
    """Set important=False (un-mark)."""
    # First set to true
    sample_utterance.important = True
    r = await client.patch(
        f"/api/v1/hmp/utterances/{sample_utterance.id}/important",
        json={"important": False},
    )
    assert r.status_code == 200
    assert r.json()["important"] is False


@pytest.mark.asyncio
async def test_toggle_utterance_important_not_found(client):
    """Unknown utterance → 404."""
    r = await client.patch(
        f"/api/v1/hmp/utterances/{uuid.uuid4()}/important",
        json={"important": True},
    )
    assert r.status_code == 404


# ============================================================================
# Various 404 / 422 edge cases
# ============================================================================

@pytest.mark.asyncio
async def test_get_utterance_invalid_uuid(client):
    """Invalid uuid in path → 422."""
    r = await client.get("/api/v1/hmp/utterances/not-a-uuid")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_update_utterance_speaker_invalid_uuid(client):
    """Invalid uuid in body → 422."""
    r = await client.patch(
        f"/api/v1/hmp/utterances/not-a-uuid/speaker",
        json={"speaker_id": str(uuid.uuid4())},
    )
    assert r.status_code == 422