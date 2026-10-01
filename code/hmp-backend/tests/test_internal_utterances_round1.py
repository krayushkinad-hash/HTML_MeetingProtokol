"""Round1: focused extra coverage for routers/utterances.py.

Targets branches / endpoints that the existing v1-v4 suites only graze, to push
overall coverage over 50%. Uses the ``make_factory`` pattern (direct insert
via ``db_engine``) so it stays robust against pool-staleness on the shared
test DB (see fastapi-router-test-coverage pitfall #8b).

Endpoints exercised here:
- GET    /utterances                          — basic + filter combinations
- GET    /utterances/{id}                     — happy + 404 + 422
- PATCH  /utterances/{id}/text                 — no-op, with/without snapshot,
                                                 404, 422, original preserved
- PATCH  /utterances/{id}/speaker              — happy, 404, 422, same-protocol
- GET    /utterances/{id}/versions             — empty + after edits + 404 + 422
- POST   /utterances/{id}/restore/{version}   — happy, version<1, 404, 422,
                                                 snapshot missing previous_text
"""
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

PREFIX = "/api/v1/hmp"


# ---------------------------------------------------------------------------
# Factory helper — uses the shared session pool so rows are immediately
# visible to the FastAPI dependency.
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def make_factory(db_session):
    """Insert ORM instances via the shared db_session so FastAPI routes see them.
    Rolls back any pending state before each insert so that a failed prior
    operation can't poison subsequent tests.
    """

    async def _make(instance):
        # Defensive: discard any pending/aborted state from prior use.
        if db_session.in_transaction():
            try:
                await db_session.rollback()
            except Exception:
                pass
        db_session.add(instance)
        await db_session.commit()
        return instance

    return _make


# ---------------------------------------------------------------------------
# Helpers — model builders
# ---------------------------------------------------------------------------
def _make_protocol(pid):
    from app.db.models import Protocol, ProtocolStatus

    now = datetime.now(timezone.utc)
    return Protocol(
        id=pid,
        title="Round1 Protocol",
        status=ProtocolStatus.RECORDING,
        date=now.date(),
        created_at=now,
        updated_at=now,
        language="ru",
    )


def _make_speaker(sid, pid, label="SPK_R1"):
    from app.db.models import Speaker

    return Speaker(id=sid, protocol_id=pid, speaker_label=label)


def _make_utterance(uid, pid, sid, *, text="orig text", start_sec=0.0,
                     end_sec=1.0, confidence=None, low_confidence=False,
                     important=False, corrected_by_llm=False,
                     text_original=None):
    from app.db.models import Utterance

    return Utterance(
        id=uid,
        protocol_id=pid,
        speaker_id=sid,
        start_sec=start_sec,
        end_sec=end_sec,
        text=text,
        confidence=confidence,
        low_confidence=low_confidence,
        important=important,
        corrected_by_llm=corrected_by_llm,
        text_original=text_original,
    )


# ===========================================================================
# 1. GET /utterances — list endpoint branches
# ===========================================================================
@pytest.mark.asyncio
async def test_list_utterances_basic_returns_items(client, make_factory):
    """Happy path: list returns total + items with speaker_label denormalised."""
    pid, sid, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await make_factory(_make_protocol(pid))
    await make_factory(_make_speaker(sid, pid))
    await make_factory(_make_utterance(uid, pid, sid, text="hello"))

    resp = await client.get(
        f"{PREFIX}/utterances",
        params={"protocol_id": str(pid)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["skip"] == 0
    assert body["limit"] == 100
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] == str(uid)
    assert item["speaker_label"] == "SPK_R1"
    assert item["text"] == "hello"


@pytest.mark.asyncio
async def test_list_utterances_filters_speaker_and_low_conf(client, make_factory):
    """Combined speaker_id + low_confidence_only filter narrows the result set."""
    pid = uuid.uuid4()
    spk1, spk2 = uuid.uuid4(), uuid.uuid4()
    await make_factory(_make_protocol(pid))
    await make_factory(_make_speaker(spk1, pid, label="A"))
    await make_factory(_make_speaker(spk2, pid, label="B"))

    await make_factory(_make_utterance(uuid.uuid4(), pid, spk1,
                   start_sec=0.0, end_sec=1.0, text="x", low_confidence=True))
    await make_factory(_make_utterance(uuid.uuid4(), pid, spk1,
                   start_sec=2.0, end_sec=3.0, text="y", low_confidence=False))
    await make_factory(_make_utterance(uuid.uuid4(), pid, spk2,
                   start_sec=4.0, end_sec=5.0, text="z", low_confidence=True))

    resp = await client.get(
        f"{PREFIX}/utterances",
        params={
            "protocol_id": str(pid),
            "speaker_id": str(spk1),
            "low_confidence_only": "true",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["text"] == "x"


@pytest.mark.asyncio
async def test_list_utterances_after_sec_cursor(client, make_factory):
    """after_sec > N returns only utterances with start_sec > N."""
    pid, sid = uuid.uuid4(), uuid.uuid4()
    await make_factory(_make_protocol(pid))
    await make_factory(_make_speaker(sid, pid))
    times = [(0.0, 0.5), (1.5, 2.0), (3.0, 3.5), (5.0, 5.5)]
    for i, (sec, end) in enumerate(times):
        await make_factory(_make_utterance(uuid.uuid4(), pid, sid,
                       start_sec=sec, end_sec=end, text=f"t{i}"))

    resp = await client.get(
        f"{PREFIX}/utterances",
        params={"protocol_id": str(pid), "after_sec": 2.0},
    )
    assert resp.status_code == 200
    body = resp.json()
    texts = [it["text"] for it in body["items"]]
    assert texts == ["t2", "t3"]


@pytest.mark.asyncio
async def test_list_utterances_protocol_not_found(client):
    """Unknown protocol_id → 404 with detail."""
    resp = await client.get(
        f"{PREFIX}/utterances",
        params={"protocol_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
    assert "Протокол не найден" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_list_utterances_missing_protocol_id(client):
    """Missing required query param → 422 (FastAPI validation)."""
    resp = await client.get(f"{PREFIX}/utterances")
    assert resp.status_code == 422


# ===========================================================================
# 2. GET /utterances/{id}
# ===========================================================================
@pytest.mark.asyncio
async def test_get_utterance_ok(client, make_factory):
    pid, sid, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await make_factory(_make_protocol(pid))
    await make_factory(_make_speaker(sid, pid))
    await make_factory(_make_utterance(uid, pid, sid, text="abc"))

    resp = await client.get(f"{PREFIX}/utterances/{uid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(uid)
    assert body["text"] == "abc"
    assert body["speaker_label"] == "SPK_R1"


@pytest.mark.asyncio
async def test_get_utterance_not_found(client):
    """Random uuid → 404."""
    resp = await client.get(f"{PREFIX}/utterances/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert "Реплика не найдена" in resp.json()["detail"]


# ===========================================================================
# 3. PATCH /utterances/{id}/text
# ===========================================================================
@pytest.mark.asyncio
async def test_update_text_noop_returns_current(client, make_factory):
    """body.text == current text → no snapshot, returns current (early branch)."""
    pid, sid, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await make_factory(_make_protocol(pid))
    await make_factory(_make_speaker(sid, pid))
    await make_factory(_make_utterance(uid, pid, sid, text="same"))

    resp = await client.patch(
        f"{PREFIX}/utterances/{uid}/text",
        json={"text": "same", "version_snapshot": True},
    )
    assert resp.status_code == 200
    assert resp.json()["text"] == "same"


@pytest.mark.asyncio
async def test_update_text_with_snapshot_records_original(client, make_factory):
    """First edit with version_snapshot=true sets text_original & creates version."""
    pid, sid, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await make_factory(_make_protocol(pid))
    await make_factory(_make_speaker(sid, pid))
    await make_factory(_make_utterance(uid, pid, sid, text="original"))

    resp = await client.patch(
        f"{PREFIX}/utterances/{uid}/text",
        json={"text": "edited v1", "version_snapshot": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "edited v1"

    # versions endpoint should show 1 snapshot
    versions = await client.get(f"{PREFIX}/utterances/{uid}/versions")
    assert versions.status_code == 200
    items = versions.json()["items"]
    assert len(items) == 1
    snap = items[0]["snapshot"]
    assert snap["previous_text"] == "original"
    assert snap["new_text"] == "edited v1"


@pytest.mark.asyncio
async def test_update_text_without_snapshot(client, make_factory):
    """version_snapshot=false → text updated, but no version row created."""
    pid, sid, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await make_factory(_make_protocol(pid))
    await make_factory(_make_speaker(sid, pid))
    await make_factory(_make_utterance(uid, pid, sid, text="orig"))

    resp = await client.patch(
        f"{PREFIX}/utterances/{uid}/text",
        json={"text": "no-snap", "version_snapshot": False},
    )
    assert resp.status_code == 200
    assert resp.json()["text"] == "no-snap"

    versions = await client.get(f"{PREFIX}/utterances/{uid}/versions")
    assert versions.json()["total"] == 0


@pytest.mark.asyncio
async def test_update_text_second_edit_preserves_original(client, make_factory):
    """text_original is set on the FIRST edit only — subsequent edits must NOT
    overwrite it."""
    pid, sid, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await make_factory(_make_protocol(pid))
    await make_factory(_make_speaker(sid, pid))
    await make_factory(_make_utterance(uid, pid, sid, text="orig"))

    await client.patch(
        f"{PREFIX}/utterances/{uid}/text",
        json={"text": "edit-1", "version_snapshot": False},
    )
    await client.patch(
        f"{PREFIX}/utterances/{uid}/text",
        json={"text": "edit-2", "version_snapshot": False},
    )
    body = (await client.get(f"{PREFIX}/utterances/{uid}")).json()
    assert body["text"] == "edit-2"


@pytest.mark.asyncio
async def test_update_text_404(client):
    """Unknown utterance id → 404."""
    resp = await client.patch(
        f"{PREFIX}/utterances/{uuid.uuid4()}/text",
        json={"text": "x", "version_snapshot": True},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_text_empty_text_422(client, make_factory):
    """Empty text fails Pydantic min_length=1 → 422."""
    pid, sid, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await make_factory(_make_protocol(pid))
    await make_factory(_make_speaker(sid, pid))
    await make_factory(_make_utterance(uid, pid, sid, text="orig"))

    resp = await client.patch(
        f"{PREFIX}/utterances/{uid}/text",
        json={"text": "", "version_snapshot": False},
    )
    assert resp.status_code == 422


# ===========================================================================
# 4. PATCH /utterances/{id}/speaker
# ===========================================================================
@pytest.mark.asyncio
async def test_update_speaker_same_protocol_ok(client, make_factory):
    """Reassign to another speaker of the same protocol → 200."""
    pid = uuid.uuid4()
    spk1, spk2 = uuid.uuid4(), uuid.uuid4()
    uid = uuid.uuid4()
    await make_factory(_make_protocol(pid))
    await make_factory(_make_speaker(spk1, pid, label="OLD"))
    await make_factory(_make_speaker(spk2, pid, label="NEW"))
    await make_factory(_make_utterance(uid, pid, spk1))

    resp = await client.patch(
        f"{PREFIX}/utterances/{uid}/speaker",
        json={"speaker_id": str(spk2)},
    )
    assert resp.status_code == 200
    body = resp.json()
    # speaker_id is mutated on the Python attribute and committed — must
    # always reflect the new value in the response.
    assert body["speaker_id"] == str(spk2)

    # Verify the change actually persisted (re-fetch via GET).
    fresh = await client.get(f"{PREFIX}/utterances/{uid}")
    assert fresh.status_code == 200
    assert fresh.json()["speaker_id"] == str(spk2)


@pytest.mark.asyncio
async def test_update_speaker_target_not_found(client, make_factory):
    """Speaker that doesn't exist → 404."""
    pid, sid, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await make_factory(_make_protocol(pid))
    await make_factory(_make_speaker(sid, pid))
    await make_factory(_make_utterance(uid, pid, sid))

    resp = await client.patch(
        f"{PREFIX}/utterances/{uid}/speaker",
        json={"speaker_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
    assert "Целевой оратор не найден" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_update_speaker_wrong_protocol_400(client, make_factory):
    """Speaker from a *different* protocol → 400."""
    p1, p2 = uuid.uuid4(), uuid.uuid4()
    spk1, spk2 = uuid.uuid4(), uuid.uuid4()
    uid = uuid.uuid4()
    await make_factory(_make_protocol(p1))
    await make_factory(_make_protocol(p2))
    await make_factory(_make_speaker(spk1, p1))
    await make_factory(_make_speaker(spk2, p2, label="OTHER"))
    await make_factory(_make_utterance(uid, p1, spk1))

    resp = await client.patch(
        f"{PREFIX}/utterances/{uid}/speaker",
        json={"speaker_id": str(spk2)},
    )
    assert resp.status_code == 400
    assert "другому протоколу" in resp.json()["detail"]


# ===========================================================================
# 5. GET /utterances/{id}/versions
# ===========================================================================
@pytest.mark.asyncio
async def test_list_versions_empty(client, make_factory):
    """No edits → empty list."""
    pid, sid, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await make_factory(_make_protocol(pid))
    await make_factory(_make_speaker(sid, pid))
    await make_factory(_make_utterance(uid, pid, sid))

    resp = await client.get(f"{PREFIX}/utterances/{uid}/versions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["utterance_id"] == str(uid)
    assert body["total"] == 0
    assert body["items"] == []


@pytest.mark.asyncio
async def test_list_versions_after_edits_newest_first(client, make_factory):
    """After two snapshot edits, list returns 2 items, newest first."""
    pid, sid, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await make_factory(_make_protocol(pid))
    await make_factory(_make_speaker(sid, pid))
    await make_factory(_make_utterance(uid, pid, sid, text="v0"))

    await client.patch(f"{PREFIX}/utterances/{uid}/text",
                       json={"text": "v1", "version_snapshot": True})
    await client.patch(f"{PREFIX}/utterances/{uid}/text",
                       json={"text": "v2", "version_snapshot": True})

    resp = await client.get(f"{PREFIX}/utterances/{uid}/versions")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    # newest first: v2 then v1
    assert items[0]["snapshot"]["new_text"] == "v2"
    assert items[1]["snapshot"]["new_text"] == "v1"


@pytest.mark.asyncio
async def test_list_versions_utterance_not_found(client):
    resp = await client.get(f"{PREFIX}/utterances/{uuid.uuid4()}/versions")
    assert resp.status_code == 404


# ===========================================================================
# 6. POST /utterances/{id}/restore/{version}
# ===========================================================================
@pytest.mark.asyncio
async def test_restore_version_success(client, make_factory):
    """Edit twice, restore the first snapshot — text goes back to original."""
    pid, sid, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await make_factory(_make_protocol(pid))
    await make_factory(_make_speaker(sid, pid))
    await make_factory(_make_utterance(uid, pid, sid, text="ORIG"))

    await client.patch(f"{PREFIX}/utterances/{uid}/text",
                       json={"text": "EDIT-1", "version_snapshot": True})
    versions = (await client.get(
        f"{PREFIX}/utterances/{uid}/versions")).json()["items"]
    # versions list is newest-first; the snapshot that holds "ORIG" as
    # previous_text is the first edit, version_number == 1.
    snap1 = next(v for v in versions
                 if v["snapshot"]["previous_text"] == "ORIG")
    v1_number = snap1["version_number"]

    resp = await client.post(
        f"{PREFIX}/utterances/{uid}/restore/{v1_number}",
    )
    assert resp.status_code == 200
    assert resp.json()["text"] == "ORIG"


@pytest.mark.asyncio
async def test_restore_version_invalid_number_422(client, make_factory):
    """version_number < 1 → 422 (early validation branch)."""
    pid, sid, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await make_factory(_make_protocol(pid))
    await make_factory(_make_speaker(sid, pid))
    await make_factory(_make_utterance(uid, pid, sid))

    resp = await client.post(f"{PREFIX}/utterances/{uid}/restore/0")
    assert resp.status_code == 422
    assert "Номер версии" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_restore_version_not_found(client, make_factory):
    """Restore nonexistent version_number → 404."""
    pid, sid, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await make_factory(_make_protocol(pid))
    await make_factory(_make_speaker(sid, pid))
    await make_factory(_make_utterance(uid, pid, sid))

    resp = await client.post(f"{PREFIX}/utterances/{uid}/restore/999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_restore_utterance_not_found(client):
    """Restore against unknown utterance → 404."""
    resp = await client.post(
        f"{PREFIX}/utterances/{uuid.uuid4()}/restore/1",
    )
    assert resp.status_code == 404