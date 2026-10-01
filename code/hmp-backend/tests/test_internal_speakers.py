"""Tests for app/routers/speakers.py — covers GET/PATCH/DELETE/merge.

Strategy: create test data via a private async session using `db_engine`
directly so we don't request the `db_session` fixture (which opens a
transaction that conflicts with the client fixture's session).
"""
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.db.models import Protocol, ProtocolStatus, Speaker, Utterance


PREFIX = "/api/v1/hmp"


# ============================================================================
# Helpers
# ============================================================================

@pytest_asyncio.fixture
async def make_factory(db_engine):
    """Return an async factory that creates objects in their own session."""
    sm = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def _make(model, **kwargs):
        async with sm() as s:
            obj = model(**kwargs)
            s.add(obj)
            await s.commit()
            await s.refresh(obj)
            return obj

    return _make


@pytest_asyncio.fixture
async def make_protocol(make_factory):
    p = await make_factory(
        Protocol,
        id=uuid.uuid4(),
        title="Test Protocol",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    return p


# ============================================================================
# GET /speakers
# ============================================================================

@pytest.mark.asyncio
async def test_list_speakers_empty(client: AsyncClient, make_protocol):
    """GET /speakers returns empty list when no speakers exist."""
    resp = await client.get(
        f"{PREFIX}/speakers",
        params={"protocol_id": str(make_protocol.id)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


@pytest.mark.asyncio
async def test_list_speakers_with_items(client: AsyncClient, make_protocol, make_factory):
    """GET /speakers returns speakers with utterance_count and total."""
    sp1 = await make_factory(
        Speaker,
        id=uuid.uuid4(),
        protocol_id=make_protocol.id,
        speaker_label="SPK_A",
        display_name="Alice",
    )
    sp2 = await make_factory(
        Speaker,
        id=uuid.uuid4(),
        protocol_id=make_protocol.id,
        speaker_label="SPK_B",
        display_name="Bob",
    )
    for i in range(3):
        await make_factory(
            Utterance,
            id=uuid.uuid4(),
            protocol_id=make_protocol.id,
            speaker_id=sp1.id,
            start_sec=0.0,
            end_sec=1.0,
            text=f"line {i}",
        )

    resp = await client.get(
        f"{PREFIX}/speakers",
        params={"protocol_id": str(make_protocol.id)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["skip"] == 0
    assert body["limit"] == 100
    items = body["items"]
    assert len(items) == 2
    # ordered by speaker_label ascending → SPK_A first
    assert items[0]["speaker_label"] == "SPK_A"
    assert items[0]["utterance_count"] == 3
    assert items[1]["speaker_label"] == "SPK_B"
    assert items[1]["utterance_count"] == 0


@pytest.mark.asyncio
async def test_list_speakers_protocol_not_found(client: AsyncClient):
    """GET /speakers with unknown protocol → 404."""
    resp = await client.get(
        f"{PREFIX}/speakers",
        params={"protocol_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
    assert "Протокол не найден" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_list_speakers_pagination(client: AsyncClient, make_protocol, make_factory):
    """GET /speakers respects skip/limit."""
    for i in range(3):
        await make_factory(
            Speaker,
            id=uuid.uuid4(),
            protocol_id=make_protocol.id,
            speaker_label=f"SPK_{i:02d}",
        )

    resp = await client.get(
        f"{PREFIX}/speakers",
        params={
            "protocol_id": str(make_protocol.id),
            "skip": 1,
            "limit": 1,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert body["skip"] == 1
    assert body["limit"] == 1
    assert len(body["items"]) == 1


# ============================================================================
# PATCH /speakers/{id}
# ============================================================================

@pytest.mark.asyncio
async def test_update_speaker_display_name_and_color(client: AsyncClient, make_protocol, make_factory):
    """PATCH /speakers/{id} updates display_name + color."""
    sp = await make_factory(
        Speaker,
        id=uuid.uuid4(),
        protocol_id=make_protocol.id,
        speaker_label="SPK_X",
    )

    resp = await client.patch(
        f"{PREFIX}/speakers/{sp.id}",
        json={"display_name": "Alice", "color": "#FF0000"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "Alice"
    assert body["color"] == "#FF0000"
    assert body["id"] == str(sp.id)


@pytest.mark.asyncio
async def test_update_speaker_is_user_flag(client: AsyncClient, make_protocol, make_factory):
    """PATCH /speakers/{id} can toggle is_user."""
    sp = await make_factory(
        Speaker,
        id=uuid.uuid4(),
        protocol_id=make_protocol.id,
        speaker_label="SPK_Y",
    )

    resp = await client.patch(
        f"{PREFIX}/speakers/{sp.id}",
        json={"is_user": True},
    )
    assert resp.status_code == 200
    assert resp.json()["is_user"] is True


@pytest.mark.asyncio
async def test_update_speaker_empty_body_422(client: AsyncClient, make_protocol, make_factory):
    """PATCH with no fields → 422."""
    sp = await make_factory(
        Speaker,
        id=uuid.uuid4(),
        protocol_id=make_protocol.id,
        speaker_label="SPK_Z",
    )

    resp = await client.patch(f"{PREFIX}/speakers/{sp.id}", json={})
    assert resp.status_code == 422
    assert "Нет полей" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_update_speaker_not_found_404(client: AsyncClient):
    """PATCH with unknown id → 404."""
    resp = await client.patch(
        f"{PREFIX}/speakers/{uuid.uuid4()}",
        json={"display_name": "X"},
    )
    assert resp.status_code == 404
    assert "Оратор не найден" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_update_speaker_invalid_color_422(client: AsyncClient, make_protocol, make_factory):
    """PATCH with bad color format → 422 from Pydantic."""
    sp = await make_factory(
        Speaker,
        id=uuid.uuid4(),
        protocol_id=make_protocol.id,
        speaker_label="SPK_W",
    )

    resp = await client.patch(
        f"{PREFIX}/speakers/{sp.id}",
        json={"color": "not-a-color"},
    )
    assert resp.status_code == 422


# ============================================================================
# DELETE /speakers/{id}
# ============================================================================

@pytest.mark.asyncio
async def test_delete_speaker_with_no_utterances_succeeds(
    client: AsyncClient, make_protocol, make_factory
):
    """DELETE speaker with no utterances → 200 and gone."""
    sp = await make_factory(
        Speaker,
        id=uuid.uuid4(),
        protocol_id=make_protocol.id,
        speaker_label="SPK_DEL",
    )

    resp = await client.delete(f"{PREFIX}/speakers/{sp.id}")
    assert resp.status_code == 200

    list_resp = await client.get(
        f"{PREFIX}/speakers",
        params={"protocol_id": str(make_protocol.id)},
    )
    assert list_resp.status_code == 200
    ids = [item["id"] for item in list_resp.json()["items"]]
    assert str(sp.id) not in ids


@pytest.mark.asyncio
async def test_delete_speaker_with_utterances_409(
    client: AsyncClient, make_protocol, make_factory
):
    """DELETE speaker with utterances → 409 conflict."""
    sp = await make_factory(
        Speaker,
        id=uuid.uuid4(),
        protocol_id=make_protocol.id,
        speaker_label="SPK_HAS_U",
    )
    await make_factory(
        Utterance,
        id=uuid.uuid4(),
        protocol_id=make_protocol.id,
        speaker_id=sp.id,
        start_sec=0.0,
        end_sec=1.0,
        text="u",
    )

    resp = await client.delete(f"{PREFIX}/speakers/{sp.id}")
    assert resp.status_code == 409
    assert "реплик" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_delete_speaker_not_found_404(client: AsyncClient):
    """DELETE unknown id → 404."""
    resp = await client.delete(f"{PREFIX}/speakers/{uuid.uuid4()}")
    assert resp.status_code == 404


# ============================================================================
# POST /speakers/merge
# ============================================================================

@pytest.mark.asyncio
async def test_merge_speakers_reassigns_utterances(
    client: AsyncClient, make_protocol, make_factory
):
    """POST /speakers/merge reassigns utterances source→target and deletes source."""
    source = await make_factory(
        Speaker,
        id=uuid.uuid4(),
        protocol_id=make_protocol.id,
        speaker_label="SPK_SRC",
    )
    target = await make_factory(
        Speaker,
        id=uuid.uuid4(),
        protocol_id=make_protocol.id,
        speaker_label="SPK_TGT",
        display_name="Target",
    )
    for i in range(2):
        await make_factory(
            Utterance,
            id=uuid.uuid4(),
            protocol_id=make_protocol.id,
            speaker_id=source.id,
            start_sec=float(i),
            end_sec=float(i) + 1.0,
            text=f"u{i}",
        )

    resp = await client.post(
        f"{PREFIX}/speakers/merge",
        json={"source_id": str(source.id), "target_id": str(target.id)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(target.id)
    assert body["utterance_count"] == 2

    list_resp = await client.get(
        f"{PREFIX}/speakers",
        params={"protocol_id": str(make_protocol.id)},
    )
    ids = [item["id"] for item in list_resp.json()["items"]]
    assert str(source.id) not in ids
    assert str(target.id) in ids


@pytest.mark.asyncio
async def test_merge_speakers_same_id_422(client: AsyncClient, make_protocol, make_factory):
    """POST /speakers/merge with source_id == target_id → 422."""
    sp = await make_factory(
        Speaker,
        id=uuid.uuid4(),
        protocol_id=make_protocol.id,
        speaker_label="SPK_DUP",
    )

    resp = await client.post(
        f"{PREFIX}/speakers/merge",
        json={"source_id": str(sp.id), "target_id": str(sp.id)},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_merge_speakers_different_protocols_400(
    client: AsyncClient, make_protocol, make_factory
):
    """POST /speakers/merge across protocols → 400."""
    sp = await make_factory(
        Speaker,
        id=uuid.uuid4(),
        protocol_id=make_protocol.id,
        speaker_label="SPK_M1",
    )
    other_p = await make_factory(
        Protocol,
        id=uuid.uuid4(),
        title="Other",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    other_speaker = await make_factory(
        Speaker,
        id=uuid.uuid4(),
        protocol_id=other_p.id,
        speaker_label="OTHER",
    )

    resp = await client.post(
        f"{PREFIX}/speakers/merge",
        json={"source_id": str(sp.id), "target_id": str(other_speaker.id)},
    )
    assert resp.status_code == 400
    assert "разные протоколы" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_merge_speakers_with_rename(
    client: AsyncClient, make_protocol, make_factory
):
    """POST /speakers/merge with new_display_name renames target."""
    source = await make_factory(
        Speaker,
        id=uuid.uuid4(),
        protocol_id=make_protocol.id,
        speaker_label="SPK_A",
    )
    target = await make_factory(
        Speaker,
        id=uuid.uuid4(),
        protocol_id=make_protocol.id,
        speaker_label="SPK_B",
        display_name="OldName",
    )

    resp = await client.post(
        f"{PREFIX}/speakers/merge",
        json={
            "source_id": str(source.id),
            "target_id": str(target.id),
            "new_display_name": "NewName",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "NewName"


@pytest.mark.asyncio
async def test_merge_speakers_source_not_found_404(
    client: AsyncClient, make_protocol, make_factory
):
    """POST /speakers/merge with missing source → 404."""
    target = await make_factory(
        Speaker,
        id=uuid.uuid4(),
        protocol_id=make_protocol.id,
        speaker_label="SPK_T",
    )

    resp = await client.post(
        f"{PREFIX}/speakers/merge",
        json={"source_id": str(uuid.uuid4()), "target_id": str(target.id)},
    )
    assert resp.status_code == 404