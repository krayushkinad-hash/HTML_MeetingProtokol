"""Direct-handler-call coverage tests for app/routers/utterances.py.

WORKAROUND for `cov-tracking-anomaly-fastapi-lazy-imports`:
Calls the handler functions in app/routers/utterances.py directly as
Python async functions instead of through the FastAPI HTTP layer
(ASGITransport + httpx).

Root cause: pytest-cov's tracer does not record line executions on the
greenlet spawned by ASGITransport when the handler uses Depends(get_db).
Direct calls run on the test's own greenlet → tracer records every line.

See skill: ~/.hermes/profiles/alex3/skills/methodology/cov-tracking-anomaly-fastapi-lazy-imports/SKILL.md
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.db.models import Protocol, ProtocolStatus, Speaker, Utterance
from app.routers import utterances as utt_module
from app.routers.utterances import _next_version_number  # noqa: F401  (imported for completeness)
from app.schemas import (
    UtteranceUpdateImportant,
    UtteranceUpdateSpeaker,
    UtteranceUpdateText,
)

pytestmark = pytest.mark.asyncio


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def direct_db(db_engine):
    """Reuse conftest's db_engine — no second engine, no deadlock surface."""
    async_session = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


def _protocol_kwargs(**overrides) -> dict:
    defaults = dict(
        id=uuid.uuid4(),
        title="Utterances direct-coverage Protocol",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return defaults


async def _insert_protocol(direct_db, **overrides) -> uuid.UUID:
    p = Protocol(**_protocol_kwargs(**overrides))
    direct_db.add(p)
    await direct_db.flush()
    return p.id


async def _insert_speaker(
    direct_db,
    protocol_id: uuid.UUID,
    label: str = "S1",
) -> Speaker:
    spk = Speaker(
        id=uuid.uuid4(),
        protocol_id=protocol_id,
        speaker_label=label,
    )
    direct_db.add(spk)
    await direct_db.flush()
    await direct_db.refresh(spk)
    return spk


async def _insert_utterance(
    direct_db,
    protocol_id: uuid.UUID,
    *,
    text: str = "hello",
    speaker_id: uuid.UUID | None = None,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    low_confidence: bool = False,
    important: bool = False,
    text_original: str | None = None,
) -> Utterance:
    if end_sec is None:
        end_sec = start_sec + 1.0
    u = Utterance(
        id=uuid.uuid4(),
        protocol_id=protocol_id,
        speaker_id=speaker_id,
        start_sec=start_sec,
        end_sec=end_sec,
        text=text,
        text_original=text_original,
        confidence=0.9,
        low_confidence=low_confidence,
        important=important,
        corrected_by_llm=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    direct_db.add(u)
    await direct_db.flush()
    await direct_db.refresh(u)
    return u


# Minimal Request stand-in. Only `request.state.correlation_id` is read.
class _FakeRequest:
    class _State:
        correlation_id = "test-corr-id"

    def __init__(self):
        self.state = self._State()


# ----------------------------------------------------------------------------
# list_utterances
# ----------------------------------------------------------------------------


async def test_list_utterances_direct_happy_path_with_filters(direct_db):
    proto_id = await _insert_protocol(direct_db)
    spk = await _insert_speaker(direct_db, proto_id, "S1")
    await _insert_utterance(direct_db, proto_id, text="a", speaker_id=spk.id, start_sec=0.0)
    await _insert_utterance(direct_db, proto_id, text="b", speaker_id=spk.id, start_sec=1.0, low_confidence=True)
    await _insert_utterance(direct_db, proto_id, text="c", speaker_id=spk.id, start_sec=5.0)

    # Basic pagination
    result = await utt_module.list_utterances(
        protocol_id=proto_id, skip=0, limit=10,
        speaker_id=None, low_confidence_only=False, after_sec=None, db=direct_db,
    )
    assert result["total"] == 3
    assert len(result["items"]) == 3
    # Ordered by start_sec asc
    assert [u.start_sec for u in result["items"]] == [0.0, 1.0, 5.0]

    # Speaker filter
    by_spk = await utt_module.list_utterances(
        protocol_id=proto_id, skip=0, limit=10,
        speaker_id=spk.id, low_confidence_only=False, after_sec=None, db=direct_db,
    )
    assert by_spk["total"] == 3

    # Low-confidence filter
    lc = await utt_module.list_utterances(
        protocol_id=proto_id, skip=0, limit=10,
        speaker_id=None, low_confidence_only=True, after_sec=None, db=direct_db,
    )
    assert lc["total"] == 1
    assert lc["items"][0].low_confidence is True

    # after_sec filter (incremental polling, E133)
    after = await utt_module.list_utterances(
        protocol_id=proto_id, skip=0, limit=10,
        speaker_id=None, low_confidence_only=False, after_sec=2.0, db=direct_db,
    )
    assert after["total"] == 1
    assert after["items"][0].start_sec == 5.0


async def test_list_utterances_direct_404_missing_protocol(direct_db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await utt_module.list_utterances(protocol_id=uuid.uuid4(), db=direct_db)
    assert exc_info.value.status_code == 404
    assert "не найден" in exc_info.value.detail.lower()


async def test_list_utterances_direct_empty_protocol(direct_db):
    proto_id = await _insert_protocol(direct_db)
    result = await utt_module.list_utterances(
        protocol_id=proto_id,
        skip=0, limit=100,
        speaker_id=None, low_confidence_only=False, after_sec=None,
        db=direct_db,
    )
    assert result == {"total": 0, "skip": 0, "limit": 100, "items": []}


# ----------------------------------------------------------------------------
# get_utterance
# ----------------------------------------------------------------------------


async def test_get_utterance_direct_happy_path(direct_db):
    proto_id = await _insert_protocol(direct_db)
    spk = await _insert_speaker(direct_db, proto_id, "Alice")
    u = await _insert_utterance(direct_db, proto_id, text="hello", speaker_id=spk.id)

    resp = await utt_module.get_utterance(utterance_id=u.id, db=direct_db)
    assert resp.id == u.id
    assert resp.text == "hello"
    assert resp.speaker_label == "Alice"
    assert resp.speaker_id == spk.id


async def test_get_utterance_direct_404_missing(direct_db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await utt_module.get_utterance(utterance_id=uuid.uuid4(), db=direct_db)
    assert exc_info.value.status_code == 404
    assert "реплика" in exc_info.value.detail.lower()


# ----------------------------------------------------------------------------
# update_utterance_text (US-048)
# ----------------------------------------------------------------------------


async def test_update_utterance_text_direct_with_snapshot(direct_db):
    proto_id = await _insert_protocol(direct_db)
    u = await _insert_utterance(direct_db, proto_id, text="original")

    body = UtteranceUpdateText(text="corrected", version_snapshot=True)
    req = _FakeRequest()
    resp = await utt_module.update_utterance_text(
        utterance_id=u.id, body=body, request=req, db=direct_db
    )

    assert resp.text == "corrected"
    assert resp.text_original == "original"  # first edit captures original

    # Verify ProtocolVersion snapshot was written
    from app.db.models import ProtocolVersion
    from sqlalchemy import select

    pv = (
        await direct_db.execute(
            select(ProtocolVersion).where(ProtocolVersion.protocol_id == proto_id)
        )
    ).scalar_one_or_none()
    assert pv is not None
    assert pv.changed_field == f"utterance:{u.id}:text"
    assert pv.snapshot["previous_text"] == "original"
    assert pv.snapshot["new_text"] == "corrected"


async def test_update_utterance_text_direct_noop_returns_current(direct_db):
    """If the new text equals the existing text → return current state, no commit."""
    proto_id = await _insert_protocol(direct_db)
    u = await _insert_utterance(direct_db, proto_id, text="same")

    body = UtteranceUpdateText(text="same", version_snapshot=True)
    resp = await utt_module.update_utterance_text(
        utterance_id=u.id, body=body, request=_FakeRequest(), db=direct_db
    )
    assert resp.text == "same"
    assert resp.text_original is None  # unchanged

    # No ProtocolVersion row should be written for a no-op
    from app.db.models import ProtocolVersion
    from sqlalchemy import select

    pv = (
        await direct_db.execute(
            select(ProtocolVersion).where(ProtocolVersion.protocol_id == proto_id)
        )
    ).scalar_one_or_none()
    assert pv is None


async def test_update_utterance_text_direct_without_snapshot(direct_db):
    """version_snapshot=False → no ProtocolVersion row."""
    proto_id = await _insert_protocol(direct_db)
    u = await _insert_utterance(direct_db, proto_id, text="a")

    body = UtteranceUpdateText(text="b", version_snapshot=False)
    resp = await utt_module.update_utterance_text(
        utterance_id=u.id, body=body, request=_FakeRequest(), db=direct_db
    )
    assert resp.text == "b"

    from app.db.models import ProtocolVersion
    from sqlalchemy import select

    pv = (
        await direct_db.execute(
            select(ProtocolVersion).where(ProtocolVersion.protocol_id == proto_id)
        )
    ).scalar_one_or_none()
    assert pv is None


# ----------------------------------------------------------------------------
# update_utterance_speaker (US-008)
# ----------------------------------------------------------------------------


async def test_update_utterance_speaker_direct_happy_path(direct_db):
    proto_id = await _insert_protocol(direct_db)
    spk_old = await _insert_speaker(direct_db, proto_id, "Old")
    spk_new = await _insert_speaker(direct_db, proto_id, "New")
    u = await _insert_utterance(direct_db, proto_id, speaker_id=spk_old.id)

    body = UtteranceUpdateSpeaker(speaker_id=spk_new.id)
    resp = await utt_module.update_utterance_speaker(
        utterance_id=u.id, body=body, request=_FakeRequest(), db=direct_db
    )
    assert resp.speaker_id == spk_new.id
    assert resp.speaker_label == "New"


async def test_update_utterance_speaker_direct_404_missing_target(direct_db):
    from fastapi import HTTPException
    proto_id = await _insert_protocol(direct_db)
    spk = await _insert_speaker(direct_db, proto_id, "S1")
    u = await _insert_utterance(direct_db, proto_id, speaker_id=spk.id)

    body = UtteranceUpdateSpeaker(speaker_id=uuid.uuid4())
    with pytest.raises(HTTPException) as exc_info:
        await utt_module.update_utterance_speaker(
            utterance_id=u.id, body=body, request=_FakeRequest(), db=direct_db
        )
    assert exc_info.value.status_code == 404


async def test_update_utterance_speaker_direct_400_other_protocol(direct_db):
    from fastapi import HTTPException
    proto_a = await _insert_protocol(direct_db)
    proto_b = await _insert_protocol(direct_db)
    spk_a = await _insert_speaker(direct_db, proto_a, "A")
    spk_b = await _insert_speaker(direct_db, proto_b, "B")
    u = await _insert_utterance(direct_db, proto_a, speaker_id=spk_a.id)

    body = UtteranceUpdateSpeaker(speaker_id=spk_b.id)
    with pytest.raises(HTTPException) as exc_info:
        await utt_module.update_utterance_speaker(
            utterance_id=u.id, body=body, request=_FakeRequest(), db=direct_db
        )
    assert exc_info.value.status_code == 400


# ----------------------------------------------------------------------------
# list_utterance_versions (US-048)
# ----------------------------------------------------------------------------


async def test_list_utterance_versions_direct_empty(direct_db):
    proto_id = await _insert_protocol(direct_db)
    u = await _insert_utterance(direct_db, proto_id, text="x")
    result = await utt_module.list_utterance_versions(utterance_id=u.id, db=direct_db)
    assert result["utterance_id"] == str(u.id)
    assert result["total"] == 0
    assert result["items"] == []


async def test_list_utterance_versions_direct_returns_snapshots_newest_first(direct_db):
    proto_id = await _insert_protocol(direct_db)
    u = await _insert_utterance(direct_db, proto_id, text="orig")

    # Two edits → two snapshots
    await utt_module.update_utterance_text(
        utterance_id=u.id,
        body=UtteranceUpdateText(text="edit1", version_snapshot=True),
        request=_FakeRequest(),
        db=direct_db,
    )
    await utt_module.update_utterance_text(
        utterance_id=u.id,
        body=UtteranceUpdateText(text="edit2", version_snapshot=True),
        request=_FakeRequest(),
        db=direct_db,
    )

    result = await utt_module.list_utterance_versions(utterance_id=u.id, db=direct_db)
    assert result["total"] == 2
    # Newest first (version_number desc)
    assert result["items"][0]["version_number"] > result["items"][1]["version_number"]
    # Snapshot fields present
    snap = result["items"][0]["snapshot"]
    assert snap["new_text"] == "edit2"
    assert snap["previous_text"] == "edit1"


# ----------------------------------------------------------------------------
# restore_utterance_version
# ----------------------------------------------------------------------------


async def test_restore_utterance_version_direct_happy_path(direct_db):
    proto_id = await _insert_protocol(direct_db)
    u = await _insert_utterance(direct_db, proto_id, text="v0")

    # Edit once → creates version 1 with previous_text="v0"
    await utt_module.update_utterance_text(
        utterance_id=u.id,
        body=UtteranceUpdateText(text="v1", version_snapshot=True),
        request=_FakeRequest(),
        db=direct_db,
    )

    # Restore version 1 → text should be "v0" again, and a new snapshot is written
    resp = await utt_module.restore_utterance_version(
        utterance_id=u.id, version_number=1, request=_FakeRequest(), db=direct_db
    )
    assert resp.text == "v0"

    # Newest snapshot should reflect the restore (previous_text="v1", new_text="v0")
    versions_resp = await utt_module.list_utterance_versions(
        utterance_id=u.id, db=direct_db
    )
    newest = versions_resp["items"][0]
    assert newest["snapshot"]["restored_from_version"] == 1
    assert newest["snapshot"]["previous_text"] == "v1"
    assert newest["snapshot"]["new_text"] == "v0"


async def test_restore_utterance_version_direct_422_version_zero(direct_db):
    from fastapi import HTTPException
    proto_id = await _insert_protocol(direct_db)
    u = await _insert_utterance(direct_db, proto_id, text="x")
    with pytest.raises(HTTPException) as exc_info:
        await utt_module.restore_utterance_version(
            utterance_id=u.id, version_number=0, request=_FakeRequest(), db=direct_db
        )
    assert exc_info.value.status_code == 422


async def test_restore_utterance_version_direct_404_missing_version(direct_db):
    from fastapi import HTTPException
    proto_id = await _insert_protocol(direct_db)
    u = await _insert_utterance(direct_db, proto_id, text="x")
    with pytest.raises(HTTPException) as exc_info:
        await utt_module.restore_utterance_version(
            utterance_id=u.id,
            version_number=999,
            request=_FakeRequest(),
            db=direct_db,
        )
    assert exc_info.value.status_code == 404


# ----------------------------------------------------------------------------
# toggle_utterance_important (US-087, E172)
# ----------------------------------------------------------------------------


async def test_toggle_utterance_important_direct_happy_path(direct_db):
    proto_id = await _insert_protocol(direct_db)
    u = await _insert_utterance(direct_db, proto_id, important=False)

    # On
    resp_on = await utt_module.toggle_utterance_important(
        utterance_id=u.id,
        body=UtteranceUpdateImportant(important=True),
        db=direct_db,
    )
    assert resp_on.important is True

    # Off
    resp_off = await utt_module.toggle_utterance_important(
        utterance_id=u.id,
        body=UtteranceUpdateImportant(important=False),
        db=direct_db,
    )
    assert resp_off.important is False
