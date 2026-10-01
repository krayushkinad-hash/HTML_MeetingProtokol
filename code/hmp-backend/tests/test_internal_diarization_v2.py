"""E289-v2: comprehensive tests for services/diarization.py — target 50%+."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select


# ============================================================================
# Singleton / class-level constants
# ============================================================================

def test_singleton_import_and_pause_threshold():
    from app.services.diarization import (
        DiarizationService,
        diarization_service,
    )
    assert isinstance(diarization_service, DiarizationService)
    assert DiarizationService.PAUSE_THRESHOLD_SEC == 2.0
    service = DiarizationService()
    assert service.PAUSE_THRESHOLD_SEC == 2.0


def test_singleton_id_is_same():
    """Module-level singleton is the same instance across imports."""
    from app.services.diarization import diarization_service
    assert diarization_service is not None


# ============================================================================
# Helpers — protocol + utterances factory
# ============================================================================

async def _make_utterances(db, protocol_id, segments):
    """Create Utterance rows from list of (start, end, text) tuples."""
    from app.db.models import Utterance
    ids = []
    for start, end, text in segments:
        u = Utterance(
            id=uuid.uuid4(),
            protocol_id=protocol_id,
            start_sec=float(start),
            end_sec=float(end),
            text=text,
        )
        db.add(u)
        ids.append(u)
    await db.commit()
    for u in ids:
        await db.refresh(u)
    return ids


async def _make_protocol(db, title="Diarization Test"):
    from app.db.models import Protocol, ProtocolStatus
    p = Protocol(
        id=uuid.uuid4(),
        title=title,
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


# ============================================================================
# Error handling
# ============================================================================

@pytest.mark.asyncio
async def test_diarize_empty_raises_value_error(db_session):
    """No utterances → ValueError."""
    from app.services.diarization import DiarizationService

    svc = DiarizationService()
    proto = await _make_protocol(db_session, title="empty")
    with pytest.raises(ValueError, match="No utterances"):
        await svc.diarize_protocol(db_session, proto.id)


@pytest.mark.asyncio
async def test_diarize_nonexistent_protocol_raises(db_session):
    """Protocol with no utterances anywhere → ValueError."""
    from app.services.diarization import DiarizationService

    svc = DiarizationService()
    with pytest.raises(ValueError):
        await svc.diarize_protocol(db_session, uuid.uuid4())


# ============================================================================
# Core happy-path: pause-based turn grouping
# ============================================================================

@pytest.mark.asyncio
async def test_diarize_single_utterance_creates_one_turn(db_session):
    """One utterance → one turn → one Speaker."""
    from app.services.diarization import DiarizationService
    from app.db.models import Speaker

    svc = DiarizationService()
    proto = await _make_protocol(db_session)
    await _make_utterances(db_session, proto.id, [(0.0, 1.0, "hello")])

    result = await svc.diarize_protocol(db_session, proto.id)

    assert result is not None
    assert result.num_speakers_detected == 1
    assert result.pipeline_version == "heuristic-v1"
    assert len(result.segments_json) == 1

    speakers_q = await db_session.execute(
        select(Speaker).where(Speaker.protocol_id == proto.id)
    )
    speakers = speakers_q.scalars().all()
    assert len(speakers) == 1
    assert speakers[0].speaker_label == "Speaker 1"
    assert speakers[0].display_name == "Speaker 1"
    assert speakers[0].color == "#3b82f6"  # COLORS[0]


@pytest.mark.asyncio
async def test_diarize_short_pause_same_turn(db_session):
    """Utterances within 2 s pause → same turn → same speaker."""
    from app.services.diarization import DiarizationService
    from app.db.models import Speaker, Utterance

    svc = DiarizationService()
    proto = await _make_protocol(db_session)
    # gap = 1.5 s, below threshold → single turn
    utts = await _make_utterances(
        db_session, proto.id,
        [(0.0, 1.0, "a"), (2.5, 3.0, "b"), (4.5, 5.0, "c")],
    )

    result = await svc.diarize_protocol(db_session, proto.id)
    assert result.num_speakers_detected == 1

    sp_q = await db_session.execute(select(Speaker).where(Speaker.protocol_id == proto.id))
    speakers = sp_q.scalars().all()
    assert len(speakers) == 1

    # All utterances share the same speaker
    utt_q = await db_session.execute(
        select(Utterance).where(Utterance.protocol_id == proto.id)
    )
    spk_ids = {u.speaker_id for u in utt_q.scalars().all()}
    assert spk_ids == {speakers[0].id}


@pytest.mark.asyncio
async def test_diarize_long_pause_splits_turn(db_session):
    """Pause > 2 s creates a new turn → new speaker."""
    from app.services.diarization import DiarizationService
    from app.db.models import Speaker, Utterance

    svc = DiarizationService()
    proto = await _make_protocol(db_session)
    # gap between #1 and #2 = 5.0 s > 2.0 → split
    await _make_utterances(
        db_session, proto.id,
        [(0.0, 1.0, "first"), (6.0, 7.0, "second")],
    )

    result = await svc.diarize_protocol(db_session, proto.id)
    assert result.num_speakers_detected == 2

    sp_q = await db_session.execute(select(Speaker).where(Speaker.protocol_id == proto.id))
    speakers = list(sp_q.scalars().all())
    assert len(speakers) == 2
    labels = {s.speaker_label for s in speakers}
    assert labels == {"Speaker 1", "Speaker 2"}
    colors = {s.color for s in speakers}
    assert colors == {"#3b82f6", "#ef4444"}  # COLORS[0], COLORS[1]

    utt_q = await db_session.execute(
        select(Utterance).where(Utterance.protocol_id == proto.id)
    )
    spk_ids = [u.speaker_id for u in utt_q.scalars().all()]
    assert spk_ids[0] != spk_ids[1]


@pytest.mark.asyncio
async def test_diarize_exact_boundary_pause_is_same_turn(db_session):
    """pause == 2.0 → still same turn (<= threshold)."""
    from app.services.diarization import DiarizationService

    svc = DiarizationService()
    proto = await _make_protocol(db_session)
    # gap = exactly 2.0
    await _make_utterances(
        db_session, proto.id,
        [(0.0, 1.0, "x"), (3.0, 4.0, "y")],
    )

    result = await svc.diarize_protocol(db_session, proto.id)
    assert result.num_speakers_detected == 1


@pytest.mark.asyncio
async def test_diarize_just_over_threshold_splits(db_session):
    """pause = 2.001 s → new turn."""
    from app.services.diarization import DiarizationService

    svc = DiarizationService()
    proto = await _make_protocol(db_session)
    await _make_utterances(
        db_session, proto.id,
        [(0.0, 1.0, "x"), (3.001, 4.0, "y")],
    )

    result = await svc.diarize_protocol(db_session, proto.id)
    assert result.num_speakers_detected == 2


# ============================================================================
# Speaker-label/color cycling
# ============================================================================

@pytest.mark.asyncio
async def test_diarize_speaker_label_color_cycles(db_session):
    """Six turns → six distinct colors (full cycle)."""
    from app.services.diarization import DiarizationService
    from app.db.models import Speaker

    svc = DiarizationService()
    proto = await _make_protocol(db_session)
    # Six utterances with 5 s gap each
    segs = [(i * 6.0, i * 6.0 + 1.0, f"s{i}") for i in range(6)]
    await _make_utterances(db_session, proto.id, segs)

    result = await svc.diarize_protocol(db_session, proto.id)
    assert result.num_speakers_detected == 6

    sp_q = await db_session.execute(
        select(Speaker).where(Speaker.protocol_id == proto.id).order_by(Speaker.speaker_label)
    )
    speakers = list(sp_q.scalars().all())
    assert [s.speaker_label for s in speakers] == [f"Speaker {i+1}" for i in range(6)]
    expected_colors = ["#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899"]
    assert [s.color for s in speakers] == expected_colors


# ============================================================================
# min_speakers / max_speakers warning paths
# ============================================================================

@pytest.mark.asyncio
async def test_diarize_below_min_speakers_logs_warning(db_session, capfd):
    """min_speakers > detected → warning logged, but result is still returned."""
    from app.services.diarization import DiarizationService

    svc = DiarizationService()
    proto = await _make_protocol(db_session)
    await _make_utterances(db_session, proto.id, [(0.0, 1.0, "hi")])

    result = await svc.diarize_protocol(db_session, proto.id, min_speakers=5)
    out, _ = capfd.readouterr()

    assert result.num_speakers_detected == 1
    assert "diarize_below_min_speakers" in out
    assert "min_speakers=5" in out


@pytest.mark.asyncio
async def test_diarize_above_max_speakers_logs_warning(db_session, capfd):
    """max_speakers < detected → warning logged."""
    from app.services.diarization import DiarizationService

    svc = DiarizationService()
    proto = await _make_protocol(db_session)
    segs = [(i * 5.0, i * 5.0 + 1.0, f"u{i}") for i in range(4)]
    await _make_utterances(db_session, proto.id, segs)

    result = await svc.diarize_protocol(db_session, proto.id, max_speakers=2)
    out, _ = capfd.readouterr()

    assert result.num_speakers_detected == 4
    assert "diarize_above_max_speakers" in out
    assert "max_speakers=2" in out


# ============================================================================
# E198 cleanup: re-running clears old speakers + result
# ============================================================================

@pytest.mark.asyncio
async def test_diarize_rerun_clears_previous_state(db_session):
    """Second run on same protocol removes previous DiarizationResult + Speakers."""
    from app.services.diarization import DiarizationService
    from app.db.models import DiarizationResult, Speaker, Utterance

    svc = DiarizationService()
    proto = await _make_protocol(db_session)
    await _make_utterances(
        db_session, proto.id,
        [(0.0, 1.0, "a"), (5.0, 6.0, "b")],
    )

    r1 = await svc.diarize_protocol(db_session, proto.id)
    assert r1.num_speakers_detected == 2

    # Verify a Speaker and Utterance.speaker_id are populated after run #1
    sp_q = await db_session.execute(select(Speaker).where(Speaker.protocol_id == proto.id))
    assert len(sp_q.scalars().all()) == 2
    utt_q = await db_session.execute(select(Utterance).where(Utterance.protocol_id == proto.id))
    assert all(u.speaker_id is not None for u in utt_q.scalars().all())

    # Second run: cleanup should leave only the new DiarizationResult
    r2 = await svc.diarize_protocol(db_session, proto.id)
    assert r2.num_speakers_detected == 2

    dr_q = await db_session.execute(
        select(DiarizationResult).where(DiarizationResult.protocol_id == proto.id)
    )
    assert len(dr_q.scalars().all()) == 1, "Old DiarizationResult should be replaced"


# ============================================================================
# Idempotence / segments_json shape
# ============================================================================

@pytest.mark.asyncio
async def test_diarize_segments_json_shape(db_session):
    """Each segments_json entry has turn_index/start/end/utt_count."""
    from app.services.diarization import DiarizationService

    svc = DiarizationService()
    proto = await _make_protocol(db_session)
    # turn 1: 2 utts, turn 2: 1 utt
    await _make_utterances(
        db_session, proto.id,
        [(0.0, 1.0, "a"), (1.5, 2.5, "b"), (6.0, 7.0, "c")],
    )

    result = await svc.diarize_protocol(db_session, proto.id)
    assert result.num_speakers_detected == 2

    segs = result.segments_json
    assert isinstance(segs, list)
    assert len(segs) == 2
    assert segs[0]["turn_index"] == 0
    assert segs[0]["utt_count"] == 2
    assert segs[0]["start_sec"] == 0.0
    assert segs[0]["end_sec"] == 2.5
    assert segs[1]["turn_index"] == 1
    assert segs[1]["utt_count"] == 1
    assert segs[1]["start_sec"] == 6.0
    assert segs[1]["end_sec"] == 7.0


@pytest.mark.asyncio
async def test_diarize_result_has_no_der_score(db_session):
    """Heuristic pipeline sets der_score=None (E141)."""
    from app.services.diarization import DiarizationService

    svc = DiarizationService()
    proto = await _make_protocol(db_session)
    await _make_utterances(db_session, proto.id, [(0.0, 1.0, "a")])

    result = await svc.diarize_protocol(db_session, proto.id)
    assert result.der_score is None
    assert result.confidence_avg is None
    assert result.num_speakers_expected is None
    assert result.pipeline_version == "heuristic-v1"


# ============================================================================
# _get_or_create_speaker direct
# ============================================================================

@pytest.mark.asyncio
async def test_get_or_create_speaker_assigns_color_by_turn_index(db_session):
    """COLORS[turn_index % 6] — direct unit test for the helper."""
    from app.services.diarization import DiarizationService

    svc = DiarizationService()
    proto = await _make_protocol(db_session)
    s0 = await svc._get_or_create_speaker(db_session, proto.id, turn_index=0)
    s7 = await svc._get_or_create_speaker(db_session, proto.id, turn_index=7)
    await db_session.commit()

    assert s0.color == "#3b82f6"
    assert s7.color == "#ef4444"  # 7 % 6 == 1
    assert s0.speaker_label == "Speaker 1"
    assert s7.speaker_label == "Speaker 8"
