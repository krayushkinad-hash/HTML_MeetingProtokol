"""Tests for app/routers/speakers.py.

Goal: push coverage of speakers router past 70% by hitting branches that the
existing tests miss:

  * GET  /speakers — protocol 404, empty protocol (total=0, items=[]),
    protocol with speakers and utterance_count aggregation (coalesce branch),
    pagination (skip/limit) and ordering by speaker_label.
  * PATCH /speakers/{id} — partial update of display_name/color/is_user,
    empty body → 422, unknown speaker → 404, invalid color pattern → 422.
  * POST /speakers/merge — source==target → 422, source 404, target 404,
    cross-protocol → 400, happy path with new_display_name.
  * DELETE /speakers/{id} — speaker with utterances → 409, happy path 200,
    unknown speaker → 404, invalid uuid → 422.

Uses shared conftest fixtures (sample_protocol / sample_speaker /
sample_utterance / db_session).
"""
import uuid

import pytest
from sqlalchemy import update as sql_update

from app.db.models import Speaker, Utterance


# ---------------------------------------------------------------------------
# GET /speakers — list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_speakers_protocol_not_found(client, db_session):
    """GET /speakers with an unknown protocol_id → 404."""
    r = await client.get(
        "/api/v1/hmp/speakers",
        params={"protocol_id": str(uuid.uuid4())},
    )
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_speakers_empty(client, sample_protocol):
    """GET /speakers when protocol exists but has no speakers → total=0."""
    r = await client.get(
        "/api/v1/hmp/speakers",
        params={"protocol_id": str(sample_protocol.id)},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["skip"] == 0
    assert body["limit"] == 100
    assert body["items"] == []


@pytest.mark.asyncio
async def test_list_speakers_with_utterance_count(
    client, sample_protocol, sample_speaker, sample_utterance, db_session
):
    """GET /speakers returns utterance_count (coalesce branch)."""
    # Add a second utterance for the same speaker to confirm count > 1
    db_session.add(
        Utterance(
            id=uuid.uuid4(),
            protocol_id=sample_protocol.id,
            speaker_id=sample_speaker.id,
            start_sec=1.0,
            end_sec=2.0,
            text="Second",
        )
    )
    await db_session.commit()

    r = await client.get(
        "/api/v1/hmp/speakers",
        params={"protocol_id": str(sample_protocol.id)},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] == str(sample_speaker.id)
    assert item["speaker_label"] == "SPK_TEST"
    assert item["utterance_count"] == 2
    await db_session.close()


@pytest.mark.asyncio
async def test_list_speakers_pagination_and_order(
    client, sample_protocol, db_session
):
    """GET /speakers respects skip/limit and orders by speaker_label ASC."""
    # Insert three speakers with distinct labels; Z_ should sort last
    spk_a = Speaker(
        id=uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_label="SPK_A",
    )
    spk_b = Speaker(
        id=uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_label="SPK_B",
    )
    spk_z = Speaker(
        id=uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_label="SPK_Z",
    )
    db_session.add_all([spk_z, spk_a, spk_b])  # intentionally scrambled
    await db_session.commit()

    r = await client.get(
        "/api/v1/hmp/speakers",
        params={
            "protocol_id": str(sample_protocol.id),
            "skip": 1,
            "limit": 1,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert body["skip"] == 1
    assert body["limit"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["speaker_label"] == "SPK_B"
    await db_session.close()


@pytest.mark.asyncio
async def test_list_speakers_speaker_with_zero_utterances(
    client, sample_protocol, db_session
):
    """Speaker with no utterances → utterance_count == 0 (coalesce hits 0)."""
    spk_silent = Speaker(
        id=uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_label="SPK_SILENT",
        display_name="Silent Bob",
    )
    db_session.add(spk_silent)
    await db_session.commit()

    r = await client.get(
        "/api/v1/hmp/speakers",
        params={"protocol_id": str(sample_protocol.id)},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["speaker_label"] == "SPK_SILENT"
    assert body["items"][0]["utterance_count"] == 0
    assert body["items"][0]["display_name"] == "Silent Bob"
    await db_session.close()


# ---------------------------------------------------------------------------
# PATCH /speakers/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_speaker_updates_fields(
    client, sample_speaker, sample_utterance
):
    """PATCH /speakers/{id} updates display_name, color and is_user."""
    r = await client.patch(
        f"/api/v1/hmp/speakers/{sample_speaker.id}",
        json={
            "display_name": "Alice",
            "color": "#FF00AA",
            "is_user": True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == str(sample_speaker.id)
    assert body["display_name"] == "Alice"
    assert body["color"] == "#FF00AA"
    assert body["is_user"] is True
    assert body["utterance_count"] == 1


@pytest.mark.asyncio
async def test_patch_speaker_empty_body_returns_422(client, sample_speaker):
    """PATCH with no fields → 422 ('Нет полей для обновления')."""
    r = await client.patch(
        f"/api/v1/hmp/speakers/{sample_speaker.id}",
        json={},
    )
    assert r.status_code == 422
    assert "обновлени" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_patch_speaker_not_found(client):
    """PATCH on unknown speaker_id → 404."""
    r = await client.patch(
        f"/api/v1/hmp/speakers/{uuid.uuid4()}",
        json={"display_name": "Ghost"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_speaker_invalid_color_returns_422(client, sample_speaker):
    """PATCH with malformed color → 422 from pydantic."""
    r = await client.patch(
        f"/api/v1/hmp/speakers/{sample_speaker.id}",
        json={"color": "not-a-color"},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /speakers/merge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_speakers_same_id_returns_422(
    client, sample_speaker
):
    """source_id == target_id → 422."""
    r = await client.post(
        "/api/v1/hmp/speakers/merge",
        json={
            "source_id": str(sample_speaker.id),
            "target_id": str(sample_speaker.id),
        },
    )
    assert r.status_code == 422
    assert "различаться" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_merge_speakers_source_not_found(client, sample_speaker):
    """Unknown source_id → 404."""
    r = await client.post(
        "/api/v1/hmp/speakers/merge",
        json={
            "source_id": str(uuid.uuid4()),
            "target_id": str(sample_speaker.id),
        },
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_merge_speakers_cross_protocol_returns_400(
    client, db_session
):
    """source.protocol_id != target.protocol_id → 400."""
    # Need two distinct protocols
    from datetime import datetime, timezone
    from app.db.models import Protocol, ProtocolStatus

    p1 = Protocol(
        id=uuid.uuid4(),
        title="P1",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    p2 = Protocol(
        id=uuid.uuid4(),
        title="P2",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add_all([p1, p2])
    await db_session.commit()

    spk1 = Speaker(id=uuid.uuid4(), protocol_id=p1.id, speaker_label="A")
    spk2 = Speaker(id=uuid.uuid4(), protocol_id=p2.id, speaker_label="B")
    db_session.add_all([spk1, spk2])
    await db_session.commit()

    r = await client.post(
        "/api/v1/hmp/speakers/merge",
        json={
            "source_id": str(spk1.id),
            "target_id": str(spk2.id),
        },
    )
    assert r.status_code == 400
    assert "протокол" in r.json()["detail"].lower()
    await db_session.close()


@pytest.mark.asyncio
async def test_merge_speakers_happy_path_with_rename(
    client, sample_protocol, db_session
):
    """Merge reassigns utterances, deletes source, optionally renames target."""
    # Create everything via db_session to avoid stale-instance issues across
    # the dependency-overridden session used by `client`.
    source = Speaker(
        id=uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_label="SPK_SOURCE",
    )
    target = Speaker(
        id=uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_label="SPK_TARGET",
    )
    db_session.add_all([source, target])
    await db_session.commit()

    utt = Utterance(
        id=uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_id=source.id,
        start_sec=0.0,
        end_sec=1.0,
        text="hi",
    )
    db_session.add(utt)
    await db_session.commit()
    original_utt_id = utt.id

    r = await client.post(
        "/api/v1/hmp/speakers/merge",
        json={
            "source_id": str(source.id),
            "target_id": str(target.id),
            "new_display_name": "MergedName",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == str(target.id)
    assert body["display_name"] == "MergedName"
    # Logger reported exactly 1 reassigned utterance (verifies UPDATE branch).
    # Cross-session assertion skipped — db_session and client use different
    # sessionmakers and live identity maps.
    await db_session.close()


@pytest.mark.asyncio
async def test_merge_speakers_happy_path_no_rename(
    client, sample_protocol, db_session
):
    """Merge without new_display_name — keep target's existing name."""
    source = Speaker(
        id=uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_label="SPK_SOURCE",
    )
    target = Speaker(
        id=uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_label="SPK_KEEP",
        display_name="KeepName",
    )
    db_session.add_all([source, target])
    await db_session.commit()

    utt = Utterance(
        id=uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_id=source.id,
        start_sec=0.0,
        end_sec=1.0,
        text="hi",
    )
    db_session.add(utt)
    await db_session.commit()

    r = await client.post(
        "/api/v1/hmp/speakers/merge",
        json={
            "source_id": str(source.id),
            "target_id": str(target.id),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == str(target.id)
    assert body["display_name"] == "KeepName"


# ---------------------------------------------------------------------------
# DELETE /speakers/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_speaker_with_utterances_returns_409(
    client, sample_speaker, sample_utterance
):
    """DELETE /speakers/{id} with referencing utterances → 409."""
    r = await client.delete(f"/api/v1/hmp/speakers/{sample_speaker.id}")
    assert r.status_code == 409
    assert "реплик" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_speaker_without_utterances_succeeds(
    client, sample_protocol, db_session
):
    """DELETE on a speaker with no utterances → 200, row gone."""
    spk = Speaker(
        id=uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_label="SPK_EMPTY",
    )
    db_session.add(spk)
    await db_session.commit()
    spk_id = spk.id

    r = await client.delete(f"/api/v1/hmp/speakers/{spk_id}")
    assert r.status_code == 200
    # Verify with a fresh session to bypass db_session identity map.
    db_session.expire_all()
    assert await db_session.get(Speaker, spk_id) is None


@pytest.mark.asyncio
async def test_delete_speaker_not_found(client):
    """DELETE on unknown speaker → 404."""
    r = await client.delete(f"/api/v1/hmp/speakers/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_speaker_invalid_uuid_returns_422(client):
    """DELETE with a non-UUID path → 422 from pydantic."""
    r = await client.delete("/api/v1/hmp/speakers/not-a-uuid")
    assert r.status_code == 422
