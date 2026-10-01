"""Quick verify body code paths can be executed."""
import uuid
from datetime import datetime, timezone
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def make_factory(db_engine):
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


@pytest.mark.asyncio
async def test_text_update_body(client, make_factory):
    """Hit the body of update_utterance_text — exercises lines 180-224."""
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
        text="Old",
    )

    r = await client.patch(
        f"/api/v1/hmp/utterances/{utt.id}/text",
        json={"text": "New", "version_snapshot": True},
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_speaker_update_body(client, make_factory):
    """Hit the body of update_utterance_speaker — exercises lines 242-271."""
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
    utt = await make_factory(
        Utterance,
        id=uuid.uuid4(),
        protocol_id=proto.id,
        speaker_id=spk1.id,
        start_sec=0.0,
        end_sec=1.0,
        text="X",
    )

    r = await client.patch(
        f"/api/v1/hmp/utterances/{utt.id}/speaker",
        json={"speaker_id": str(spk2.id)},
    )
    assert r.status_code == 200, r.text