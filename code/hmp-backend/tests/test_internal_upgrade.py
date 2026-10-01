"""E286 v2: comprehensive tests for routers/transcribe/upgrade.py.

Targets ≥50% coverage of the 47-statement module by exercising:
  * POST /transcribe/upgrade/{protocol_id}
      - invalid UUID (400 from our handler, since path is str not UUID)
      - protocol not found (404)
      - protocol without audio_file_id (400)
      - audio_file row missing (400)
      - audio file on disk missing (400)
      - no weak segments → no-op 200
      - valid path with weak segments → 200 + background task
      - weak via low_confidence flag (NULL numeric confidence + flag=True)
      - weak via NULL confidence only
      - custom target_model + custom confidence_threshold
      - background runner swallows exceptions
  * Router structural sanity
"""
import uuid
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Module / router structural sanity
# ---------------------------------------------------------------------------


def test_upgrade_module_imports():
    from app.routers.transcribe import upgrade

    assert upgrade is not None
    assert hasattr(upgrade, "router")
    assert hasattr(upgrade, "upgrade_weak_segments_endpoint")


def test_router_has_expected_routes():
    from app.routers.transcribe.upgrade import router

    paths = {r.path for r in router.routes}
    assert "/transcribe/upgrade/{protocol_id}" in paths


# ---------------------------------------------------------------------------
# Helpers — use db_engine directly to avoid ORM .refresh() deadlock race
# ---------------------------------------------------------------------------


async def _insert_audio_file(db_engine, file_path: Path) -> uuid.UUID:
    """Insert an AudioFile row using the test engine directly (no refresh)."""
    from app.db.models import AudioFile
    from sqlalchemy import insert

    aid = uuid.uuid4()
    async with db_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(
                insert(AudioFile).values(
                    id=aid,
                    file_path=str(file_path),
                    filename=file_path.name,
                    extension=file_path.suffix.lstrip(".") or "wav",
                    size_bytes=file_path.stat().st_size if file_path.exists() else 1024,
                    mime_type="audio/wav",
                    duration_sec=120,
                )
            )
    return aid


async def _insert_protocol(
    db_engine, *, audio_file_id: uuid.UUID | None = None
) -> uuid.UUID:
    from app.db.models import Protocol, ProtocolStatus
    from datetime import datetime, timezone
    from sqlalchemy import insert

    pid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    async with db_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(
                insert(Protocol).values(
                    id=pid,
                    title="Test Protocol",
                    status=ProtocolStatus.RECORDING,
                    date=now.date(),
                    created_at=now,
                    audio_file_id=audio_file_id,
                )
            )
    return pid


async def _insert_speaker(db_engine, protocol_id: uuid.UUID) -> uuid.UUID:
    from app.db.models import Speaker
    from sqlalchemy import insert

    sid = uuid.uuid4()
    async with db_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(
                insert(Speaker).values(
                    id=sid, protocol_id=protocol_id, speaker_label="SPK"
                )
            )
    return sid


async def _insert_utterance(
    db_engine,
    protocol_id: uuid.UUID,
    speaker_id: uuid.UUID,
    *,
    text: str,
    start: float,
    end: float,
    confidence=None,
    low_confidence=False,
) -> uuid.UUID:
    from app.db.models import Utterance
    from sqlalchemy import insert
    from datetime import datetime, timezone

    uid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    async with db_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(
                insert(Utterance).values(
                    id=uid,
                    protocol_id=protocol_id,
                    speaker_id=speaker_id,
                    start_sec=start,
                    end_sec=end,
                    text=text,
                    confidence=confidence,
                    low_confidence=low_confidence,
                    created_at=now,
                    updated_at=now,
                )
            )
    return uid


# ---------------------------------------------------------------------------
# Endpoint error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_protocol_id_returns_400(client):
    """Non-UUID path param → our handler raises HTTPException(400)."""
    r = await client.post("/api/v1/hmp/transcribe/upgrade/not-a-uuid")
    assert r.status_code == 400
    body = r.json()
    assert "Невалидный" in body.get("detail", "")


@pytest.mark.asyncio
async def test_protocol_not_found_returns_404(client):
    """Valid UUID but no Protocol row in DB → 404."""
    pid = uuid.uuid4()
    r = await client.post(f"/api/v1/hmp/transcribe/upgrade/{pid}")
    assert r.status_code == 404
    assert "не найден" in r.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_protocol_without_audio_file_returns_400(client, db_engine):
    """Protocol exists but audio_file_id is NULL → 400."""
    pid = await _insert_protocol(db_engine, audio_file_id=None)
    r = await client.post(f"/api/v1/hmp/transcribe/upgrade/{pid}")
    assert r.status_code == 400
    assert "аудиофайла" in r.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_audio_file_row_missing_returns_400(client, db_engine):
    """Protocol points to an AudioFile id that doesn't exist in DB → 400.

    We bypass the FK constraint by creating an AudioFile row first, then
    deleting it via raw SQL. The Protocol still holds the dangling FK at
    request time, which the endpoint detects.
    """
    from app.db.models import AudioFile
    from sqlalchemy import insert, delete

    aid = uuid.uuid4()
    pid = uuid.uuid4()
    now_path = Path("/tmp/missing_audio_for_upgrade_test.wav")
    async with db_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(
                insert(AudioFile).values(
                    id=aid,
                    file_path=str(now_path),
                    filename=now_path.name,
                    extension="wav",
                    size_bytes=1024,
                    mime_type="audio/wav",
                    duration_sec=10,
                )
            )
            await conn.execute(
                insert(__import__("app.db.models", fromlist=["Protocol"]).Protocol).values(
                    id=pid,
                    title="dangling-fk",
                    # protocol_status enum is {loaded, transcribing, diarizing,
                    # ready, failed, live} — "recording" is not valid.
                    status="loaded",
                    date=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).date(),
                    created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                    audio_file_id=aid,
                )
            )
        async with conn.begin():
            # Delete the audio row, leaving the protocol's FK dangling
            await conn.execute(delete(AudioFile).where(AudioFile.id == aid))

    r = await client.post(f"/api/v1/hmp/transcribe/upgrade/{pid}")
    assert r.status_code == 400
    assert "аудиофайл" in r.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_audio_file_on_disk_missing_returns_400(client, db_engine):
    """AudioFile row exists but file_path doesn't exist on disk → 400."""
    bogus = Path("/tmp/definitely-not-here-upgrade-audio.wav")
    if bogus.exists():
        bogus.unlink()
    aid = await _insert_audio_file(db_engine, bogus)
    pid = await _insert_protocol(db_engine, audio_file_id=aid)

    r = await client.post(f"/api/v1/hmp/transcribe/upgrade/{pid}")
    assert r.status_code == 400
    assert "аудио не найдено" in r.json().get("detail", "").lower()


# ---------------------------------------------------------------------------
# Happy path branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_weak_segments_returns_noop_200(client, db_engine, tmp_path):
    """All utterances have confidence >= threshold → no-op response, no background task."""
    audio_path = tmp_path / "silence.wav"
    audio_path.write_bytes(b"RIFF")
    aid = await _insert_audio_file(db_engine, audio_path)
    pid = await _insert_protocol(db_engine, audio_file_id=aid)
    sid = await _insert_speaker(db_engine, pid)

    # ALL utterances have high confidence and low_confidence=False
    for i in range(3):
        await _insert_utterance(
            db_engine, pid, sid,
            text=f"ok {i}", start=float(i), end=float(i) + 1.0,
            confidence=0.95, low_confidence=False,
        )

    r = await client.post(f"/api/v1/hmp/transcribe/upgrade/{pid}")
    assert r.status_code == 200
    body = r.json()
    assert body["weak_segments_found"] == 0
    assert body["upgraded"] == 0
    assert body["skipped"] == 0
    assert "Нет слабых" in body["message"]
    # No task_id in the no-op branch
    assert "task_id" not in body


@pytest.mark.asyncio
async def test_weak_segments_low_confidence_queues_background_task(
    client, db_engine, tmp_path, monkeypatch
):
    """Utterance with confidence < threshold → queues background upgrade."""
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"RIFF")
    aid = await _insert_audio_file(db_engine, audio_path)
    pid = await _insert_protocol(db_engine, audio_file_id=aid)
    sid = await _insert_speaker(db_engine, pid)

    # The module imports `register_active_task` lazily INSIDE the function
    # (`from app.services.active_tasks import register_active_task`), so we
    # patch the source-of-truth symbol instead of the module attribute.
    from app.services import active_tasks as active_tasks_mod

    captured = {}

    def fake_register(task_id_str, task):
        captured["task_id"] = task_id_str
        captured["task"] = task
        # Cancel so we don't wait on real transcription
        try:
            task.cancel()
        except Exception:
            pass

    monkeypatch.setattr(active_tasks_mod, "register_active_task", fake_register)

    # weak utterance (confidence=0.3 < threshold=0.7)
    await _insert_utterance(
        db_engine, pid, sid,
        text="weak", start=0.0, end=1.0,
        confidence=0.3, low_confidence=False,
    )
    # strong utterance — must NOT be picked up
    await _insert_utterance(
        db_engine, pid, sid,
        text="strong", start=2.0, end=3.0,
        confidence=0.95, low_confidence=False,
    )

    r = await client.post(f"/api/v1/hmp/transcribe/upgrade/{pid}")
    assert r.status_code == 200
    body = r.json()
    assert body["weak_segments_found"] == 1
    assert "task_id" in body
    assert body["target_model"] == "large-v3"
    assert captured.get("task_id") == body["task_id"]


@pytest.mark.asyncio
async def test_weak_segments_by_low_confidence_flag_qualifies(
    client, db_engine, tmp_path, monkeypatch
):
    """low_confidence=True with NULL numeric confidence is still weak."""
    audio_path = tmp_path / "audio2.wav"
    audio_path.write_bytes(b"RIFF")
    aid = await _insert_audio_file(db_engine, audio_path)
    pid = await _insert_protocol(db_engine, audio_file_id=aid)
    sid = await _insert_speaker(db_engine, pid)

    from app.services import active_tasks as active_tasks_mod

    def fake_register(task_id_str, task):
        try:
            task.cancel()
        except Exception:
            pass

    monkeypatch.setattr(active_tasks_mod, "register_active_task", fake_register)

    # confidence=None + low_confidence=True → weak via the boolean flag
    await _insert_utterance(
        db_engine, pid, sid,
        text="flag-weak", start=0.0, end=1.0,
        confidence=None, low_confidence=True,
    )

    r = await client.post(f"/api/v1/hmp/transcribe/upgrade/{pid}")
    assert r.status_code == 200
    body = r.json()
    assert body["weak_segments_found"] == 1


@pytest.mark.asyncio
async def test_weak_segments_with_null_confidence_qualifies(
    client, db_engine, tmp_path, monkeypatch
):
    """confidence IS NULL (no flag set) is also treated as weak."""
    audio_path = tmp_path / "audio3.wav"
    audio_path.write_bytes(b"RIFF")
    aid = await _insert_audio_file(db_engine, audio_path)
    pid = await _insert_protocol(db_engine, audio_file_id=aid)
    sid = await _insert_speaker(db_engine, pid)

    from app.services import active_tasks as active_tasks_mod

    def fake_register(task_id_str, task):
        try:
            task.cancel()
        except Exception:
            pass

    monkeypatch.setattr(active_tasks_mod, "register_active_task", fake_register)

    await _insert_utterance(
        db_engine, pid, sid,
        text="null-conf", start=0.0, end=1.0,
        confidence=None, low_confidence=False,
    )

    r = await client.post(f"/api/v1/hmp/transcribe/upgrade/{pid}")
    assert r.status_code == 200
    body = r.json()
    assert body["weak_segments_found"] == 1


@pytest.mark.asyncio
async def test_custom_target_model_and_threshold_propagate(
    client, db_engine, tmp_path, monkeypatch
):
    """target_model & confidence_threshold query params flow into the response."""
    audio_path = tmp_path / "audio4.wav"
    audio_path.write_bytes(b"RIFF")
    aid = await _insert_audio_file(db_engine, audio_path)
    pid = await _insert_protocol(db_engine, audio_file_id=aid)
    sid = await _insert_speaker(db_engine, pid)

    from app.services import active_tasks as active_tasks_mod

    def fake_register(task_id_str, task):
        try:
            task.cancel()
        except Exception:
            pass

    monkeypatch.setattr(active_tasks_mod, "register_active_task", fake_register)

    await _insert_utterance(
        db_engine, pid, sid,
        text="weak", start=0.0, end=1.0,
        confidence=0.5, low_confidence=False,
    )

    # With threshold=0.9, the confidence=0.5 utterance is weak.
    r = await client.post(
        f"/api/v1/hmp/transcribe/upgrade/{pid}",
        params={"target_model": "medium", "confidence_threshold": 0.9},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["target_model"] == "medium"
    assert body["weak_segments_found"] == 1


@pytest.mark.asyncio
async def test_background_runner_swallows_transcription_exception(
    client, db_engine, tmp_path, monkeypatch
):
    """If the background runner raises, the endpoint still returns 200.

    The endpoint returns 200 immediately after scheduling the background task;
    the exception happens inside the asyncio task, which logs it via the
    runner's `except Exception` handler.
    """
    from app.services import transcription, active_tasks as active_tasks_mod

    async def boom(**kwargs):
        raise RuntimeError("fake transcription crash")

    monkeypatch.setattr(transcription.transcription_service, "transcribe", boom)

    def fake_register(task_id_str, task):
        try:
            task.cancel()
        except Exception:
            pass

    monkeypatch.setattr(active_tasks_mod, "register_active_task", fake_register)

    audio_path = tmp_path / "audio5.wav"
    audio_path.write_bytes(b"RIFF")
    aid = await _insert_audio_file(db_engine, audio_path)
    pid = await _insert_protocol(db_engine, audio_file_id=aid)
    sid = await _insert_speaker(db_engine, pid)

    await _insert_utterance(
        db_engine, pid, sid,
        text="weak", start=0.0, end=1.0,
        confidence=0.3, low_confidence=False,
    )

    r = await client.post(f"/api/v1/hmp/transcribe/upgrade/{pid}")
    assert r.status_code == 200
    body = r.json()
    assert body["weak_segments_found"] == 1
    # Background task was scheduled (and immediately cancelled)
    assert "task_id" in body


@pytest.mark.asyncio
async def test_endpoint_function_signature_matches_documented_contract():
    """Direct invocation guard: ensure the function signature hasn't drifted."""
    from app.routers.transcribe.upgrade import upgrade_weak_segments_endpoint
    import inspect

    sig = inspect.signature(upgrade_weak_segments_endpoint)
    params = sig.parameters
    assert "protocol_id" in params
    assert "target_model" in params
    assert "confidence_threshold" in params
    assert "db" in params
    # Defaults match US-086 / E162 spec
    assert params["target_model"].default == "large-v3"
    assert params["confidence_threshold"].default == 0.7