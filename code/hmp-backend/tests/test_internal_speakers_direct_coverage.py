"""Direct-handler-call coverage tests for app/routers/speakers.py.

WORKAROUND for `cov-tracking-anomaly-fastapi-lazy-imports`:
Calls `list_speakers`, `update_speaker`, `merge_speakers`, `delete_speaker`
directly as Python async functions instead of through the FastAPI HTTP layer
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
from app.routers import speakers as speakers_module
from app.routers.speakers import SpeakerMergeRequest, SpeakerUpdate

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
        title="Speakers direct-coverage Protocol",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return defaults


async def _insert_protocol(direct_db, **overrides) -> Protocol:
    p = Protocol(**_protocol_kwargs(**overrides))
    direct_db.add(p)
    await direct_db.commit()
    await direct_db.refresh(p)
    return p


async def _insert_speaker(
    direct_db,
    protocol_id: uuid.UUID,
    label: str = "SPK_001",
    display_name: str | None = None,
    color: str | None = None,
    is_user: bool = False,
) -> Speaker:
    s = Speaker(
        id=uuid.uuid4(),
        protocol_id=protocol_id,
        speaker_label=label,
        display_name=display_name,
        color=color,
        is_user=is_user,
    )
    direct_db.add(s)
    await direct_db.commit()
    await direct_db.refresh(s)
    return s


async def _insert_utterance(
    direct_db,
    speaker_id: uuid.UUID,
    protocol_id: uuid.UUID,
    text: str = "hello",
    start_sec: float = 0.0,
    end_sec: float = 1.0,
) -> Utterance:
    u = Utterance(
        id=uuid.uuid4(),
        speaker_id=speaker_id,
        protocol_id=protocol_id,
        start_sec=start_sec,
        end_sec=end_sec,
        text=text,
    )
    direct_db.add(u)
    await direct_db.commit()
    return u


# Minimal Request stand-in for handlers that read correlation_id.
class _FakeRequest:
    class _State:
        correlation_id = None

    def __init__(self, correlation_id: str | None = "test-corr-id"):
        self.state = self._State()
        self.state.correlation_id = correlation_id


# ----------------------------------------------------------------------------
# list_speakers — direct call
# ----------------------------------------------------------------------------


async def test_list_speakers_direct_happy_path(direct_db):
    proto = await _insert_protocol(direct_db)
    await _insert_speaker(direct_db, proto.id, "SPK_B")
    await _insert_speaker(direct_db, proto.id, "SPK_A")
    await _insert_speaker(direct_db, proto.id, "SPK_C")

    result = await speakers_module.list_speakers(
        protocol_id=proto.id, skip=0, limit=100, db=direct_db
    )

    assert result["total"] == 3
    assert result["skip"] == 0
    assert result["limit"] == 100
    labels = [item.speaker_label for item in result["items"]]
    assert labels == ["SPK_A", "SPK_B", "SPK_C"]


async def test_list_speakers_direct_with_utterance_count(direct_db):
    """Speakers with utterances expose utterance_count via the aggregate subq."""
    proto = await _insert_protocol(direct_db)
    sp = await _insert_speaker(direct_db, proto.id, "SPK_TALK")
    # two utterances on this speaker
    await _insert_utterance(direct_db, sp.id, proto.id, text="one")
    await _insert_utterance(direct_db, sp.id, proto.id, text="two")
    # silent speaker (utterance_count should be 0)
    await _insert_speaker(direct_db, proto.id, "SPK_SILENT")

    result = await speakers_module.list_speakers(
        protocol_id=proto.id, skip=0, limit=100, db=direct_db
    )

    items_by_label = {item.speaker_label: item for item in result["items"]}
    assert items_by_label["SPK_TALK"].utterance_count == 2
    assert items_by_label["SPK_SILENT"].utterance_count == 0


async def test_list_speakers_direct_404_missing_protocol(direct_db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await speakers_module.list_speakers(
            protocol_id=uuid.uuid4(), skip=0, limit=100, db=direct_db
        )
    assert exc_info.value.status_code == 404
    assert "не найден" in exc_info.value.detail.lower()


# ----------------------------------------------------------------------------
# update_speaker — direct call
# ----------------------------------------------------------------------------


async def test_update_speaker_direct_happy_path(direct_db):
    proto = await _insert_protocol(direct_db)
    sp = await _insert_speaker(direct_db, proto.id, "SPK_001", display_name="Old")

    resp = await speakers_module.update_speaker(
        speaker_id=sp.id,
        body=SpeakerUpdate(display_name="New", color="#aabbcc", is_user=True),
        request=_FakeRequest("corr-1"),
        db=direct_db,
    )

    assert resp.id == sp.id
    assert resp.display_name == "New"
    assert resp.color == "#aabbcc"
    assert resp.is_user is True


async def test_update_speaker_direct_404_missing(direct_db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await speakers_module.update_speaker(
            speaker_id=uuid.uuid4(),
            body=SpeakerUpdate(display_name="x"),
            request=_FakeRequest(),
            db=direct_db,
        )
    assert exc_info.value.status_code == 404
    assert "не найден" in exc_info.value.detail.lower()


async def test_update_speaker_direct_422_empty_body(direct_db):
    """Empty body (no fields set) → 422."""
    from fastapi import HTTPException
    proto = await _insert_protocol(direct_db)
    sp = await _insert_speaker(direct_db, proto.id, "SPK_001")

    with pytest.raises(HTTPException) as exc_info:
        await speakers_module.update_speaker(
            speaker_id=sp.id,
            body=SpeakerUpdate(),  # nothing set
            request=_FakeRequest(),
            db=direct_db,
        )
    assert exc_info.value.status_code == 422
    assert "полей" in exc_info.value.detail.lower()


# ----------------------------------------------------------------------------
# merge_speakers — direct call
# ----------------------------------------------------------------------------


async def test_merge_speakers_direct_422_same_id(direct_db):
    """source_id == target_id → 422."""
    from fastapi import HTTPException
    proto = await _insert_protocol(direct_db)
    sp = await _insert_speaker(direct_db, proto.id, "SPK_001")

    with pytest.raises(HTTPException) as exc_info:
        await speakers_module.merge_speakers(
            body=SpeakerMergeRequest(source_id=sp.id, target_id=sp.id),
            request=_FakeRequest(),
            db=direct_db,
        )
    assert exc_info.value.status_code == 422
    assert "различаться" in exc_info.value.detail.lower()


async def test_merge_speakers_direct_400_cross_protocol(direct_db):
    """Speakers from different protocols → 400."""
    from fastapi import HTTPException
    proto_a = await _insert_protocol(direct_db)
    proto_b = await _insert_protocol(direct_db)
    sp_a = await _insert_speaker(direct_db, proto_a.id, "SPK_A")
    sp_b = await _insert_speaker(direct_db, proto_b.id, "SPK_B")

    with pytest.raises(HTTPException) as exc_info:
        await speakers_module.merge_speakers(
            body=SpeakerMergeRequest(source_id=sp_a.id, target_id=sp_b.id),
            request=_FakeRequest(),
            db=direct_db,
        )
    assert exc_info.value.status_code == 400


async def test_merge_speakers_direct_happy_path(direct_db):
    """Reassigns utterances from source → target, deletes source, optionally renames."""
    proto = await _insert_protocol(direct_db)
    src = await _insert_speaker(direct_db, proto.id, "SPK_SRC")
    tgt = await _insert_speaker(direct_db, proto.id, "SPK_TGT")
    # 3 utterances on source
    await _insert_utterance(direct_db, src.id, proto.id, text="u1")
    await _insert_utterance(direct_db, src.id, proto.id, text="u2")
    await _insert_utterance(direct_db, src.id, proto.id, text="u3")
    # 1 utterance on target
    await _insert_utterance(direct_db, tgt.id, proto.id, text="existing")

    resp = await speakers_module.merge_speakers(
        body=SpeakerMergeRequest(
            source_id=src.id,
            target_id=tgt.id,
            new_display_name="Merged Speaker",
        ),
        request=_FakeRequest("corr-merge"),
        db=direct_db,
    )

    assert resp.id == tgt.id
    assert resp.utterance_count == 4  # 3 reassigned + 1 original
    assert resp.display_name == "Merged Speaker"

    # source row gone
    from sqlalchemy import select
    result = await direct_db.execute(select(Speaker).where(Speaker.id == src.id))
    assert result.scalar_one_or_none() is None


# ----------------------------------------------------------------------------
# delete_speaker — direct call
# ----------------------------------------------------------------------------


async def test_delete_speaker_direct_409_when_has_utterances(direct_db):
    """Speaker with utterances → 409."""
    from fastapi import HTTPException
    proto = await _insert_protocol(direct_db)
    sp = await _insert_speaker(direct_db, proto.id, "SPK_BUSY")
    await _insert_utterance(direct_db, sp.id, proto.id)

    with pytest.raises(HTTPException) as exc_info:
        await speakers_module.delete_speaker(
            speaker_id=sp.id, request=_FakeRequest(), db=direct_db
        )
    assert exc_info.value.status_code == 409
    assert "реплик" in exc_info.value.detail.lower()


async def test_delete_speaker_direct_happy_path(direct_db):
    """Speaker with no utterances → deleted silently."""
    from sqlalchemy import select
    proto = await _insert_protocol(direct_db)
    sp = await _insert_speaker(direct_db, proto.id, "SPK_BYE")

    # Should not raise
    await speakers_module.delete_speaker(
        speaker_id=sp.id, request=_FakeRequest("corr-del"), db=direct_db
    )

    result = await direct_db.execute(select(Speaker).where(Speaker.id == sp.id))
    assert result.scalar_one_or_none() is None


async def test_delete_speaker_direct_404_missing(direct_db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await speakers_module.delete_speaker(
            speaker_id=uuid.uuid4(), request=_FakeRequest(), db=direct_db
        )
    assert exc_info.value.status_code == 404