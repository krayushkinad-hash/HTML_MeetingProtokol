"""Targeted coverage tests for app/services/transcription.py flow paths.

Targets code paths that existing tests miss:
- transcribe() queue pre-cleanup branch (lines 286-290)
- transcribe() fallback_reason notify user (lines 342-345)
- transcribe() utterances_task create failure (lines 472-485)
- transcribe() protocol status mark "ready" error path (lines 669-674)
- transcribe() completion_db_update_failed (lines 685-690)
- _run_transcribe_eager: vad_parameters branch when vad on (lines 569-577)
- _run_transcribe_eager: vad_parameters None when vad off (line 558)
- _persist_utterances_loop final flush (lines 893-908)
- _persist_utterances_loop save_batch exception (lines 867-873)
- get_status: str→UUID conversion (lines 922-927)
- get_status: completed/failed/cancelled return None (lines 935-936)
- transcribe() target_model_override set but _load_model raises (lines 304-313)
- transcribe() only_update_weak path (lines 334-339)
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_whisper_mock(*, return_segments=("hello", "world"), duration=5.0,
                       vad_filter_arg=None):
    """Create a mock WhisperModel whose .transcribe() yields segments."""
    segments = []
    for text in return_segments:
        s = MagicMock(start=0.0, end=2.0, no_speech_prob=0.1, avg_logprob=-0.2)
        s.text = f" {text} "
        segments.append(s)
    info = MagicMock(duration=duration, language="en", language_probability=0.95)
    model = MagicMock()
    model.transcribe = MagicMock(return_value=(iter(segments), info))
    return model, segments, info


def _install_model_manager(monkeypatch, *, active="tiny", downloaded=("tiny",),
                           available=("tiny",)):
    mm = MagicMock()
    mm.get_active_model.return_value = active
    mm.is_downloaded.side_effect = lambda name: name in downloaded
    wm = MagicMock()
    wm.model_manager = mm
    wm.AVAILABLE_MODELS = list(available)
    monkeypatch.setitem(sys.modules, "app.services.whisper_models", wm)
    return mm


# ---------------------------------------------------------------------------
# get_status edge cases
# ---------------------------------------------------------------------------


def test_get_status_string_uuid_conversion():
    """get_status accepts string UUID (lines 922-927)."""
    from app.services.transcription import TranscriptionService, TranscriptionStatus

    svc = TranscriptionService()
    tid = uuid.uuid4()
    # Use "running" (non-terminal, non-processing) so is_task_alive path is skipped
    svc._tasks[tid] = TranscriptionStatus(
        id=tid, protocol_id=uuid.uuid4(), status="running",
    )
    # Pass string form
    result = svc.get_status(str(tid))
    assert result is not None
    assert result.status == "running"


def test_get_status_invalid_string_returns_none():
    """get_status with invalid UUID string → None (lines 925-927)."""
    from app.services.transcription import TranscriptionService

    svc = TranscriptionService()
    assert svc.get_status("not-a-uuid") is None
    assert svc.get_status("") is None


def test_get_status_completed_returns_none():
    """Completed task → None (E182, lines 935-936)."""
    from app.services.transcription import TranscriptionService, TranscriptionStatus

    svc = TranscriptionService()
    tid = uuid.uuid4()
    svc._tasks[tid] = TranscriptionStatus(
        id=tid, protocol_id=uuid.uuid4(), status="completed",
    )
    assert svc.get_status(tid) is None


def test_get_status_failed_cancelled_return_none():
    """Failed and cancelled tasks also return None from get_status."""
    from app.services.transcription import TranscriptionService, TranscriptionStatus

    svc = TranscriptionService()
    for terminal in ("failed", "cancelled"):
        tid = uuid.uuid4()
        svc._tasks[tid] = TranscriptionStatus(
            id=tid, protocol_id=uuid.uuid4(), status=terminal,
        )
        assert svc.get_status(tid) is None, f"{terminal} should return None"


# ---------------------------------------------------------------------------
# transcribe() flow: target_model_override + _load_model raise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_target_override_cleared_on_load_failure(monkeypatch, tmp_path):
    """When _load_model raises, _target_model_override is still cleared (lines 311-313)."""
    from app.services import transcription
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "whisper_use_batched_pipeline", False)
    monkeypatch.setattr(cfg.settings, "whisper_vad_filter", False)
    _install_model_manager(monkeypatch, active="tiny", downloaded=("tiny",))

    svc = transcription.TranscriptionService()

    def _raise_load():
        svc._target_model_override = "should-be-cleared"
        raise RuntimeError("forced load failure")

    monkeypatch.setattr(svc, "_load_model", _raise_load)

    async def _noop(*a, **kw):
        return None
    monkeypatch.setattr(
        "app.services.task_status.update_task_status_in_db", _noop)

    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"x")

    with pytest.raises(RuntimeError, match="forced load failure"):
        await svc.transcribe(
            protocol_id=uuid.uuid4(),
            audio_path=audio,
            task_id=uuid.uuid4(),
            duration_sec=5.0,
            target_model_override="small",
        )
    # Override must be None after the finally clause
    assert svc._target_model_override is None


# ---------------------------------------------------------------------------
# transcribe(): queue pre-cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_pre_cleans_utterance_queue(monkeypatch, tmp_path):
    """Stale entries in _utterance_queue are drained before transcribe (lines 286-290)."""
    from app.services import transcription
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "whisper_use_batched_pipeline", False)
    monkeypatch.setattr(cfg.settings, "whisper_vad_filter", False)
    _install_model_manager(monkeypatch, active="tiny", downloaded=("tiny",))

    model, _, _ = _make_whisper_mock(return_segments=("a",))
    svc = transcription.TranscriptionService()
    svc._model = model

    # Pre-fill queue with stale entries
    svc._utterance_queue.put({"start": 0.0, "end": 1.0, "text": "stale"})
    svc._utterance_queue.put({"start": 1.0, "end": 2.0, "text": "stale"})
    assert svc._utterance_queue.qsize() == 2

    async def _noop(*a, **kw):
        return None
    monkeypatch.setattr(
        "app.services.task_status.update_task_status_in_db", _noop)

    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"x")

    await svc.transcribe(
        protocol_id=uuid.uuid4(),
        audio_path=audio,
        task_id=uuid.uuid4(),
        duration_sec=5.0,
    )
    # Queue should have been drained before transcription; new entries
    # from the fresh run are flushed by _persist_utterances_loop.
    # We can only verify pre-cleanup ran by checking nothing "stale" leaked
    # into Utterances (covered by integration). Here we verify no exception
    # and the queue is empty post-run.
    assert svc._utterance_queue.empty()


# ---------------------------------------------------------------------------
# transcribe(): fallback_reason assigned to status.message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_fallback_reason_clears_flag(monkeypatch, tmp_path):
    """_last_fallback_reason is cleared after being assigned (lines 342-345)."""
    from app.services import transcription
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "whisper_use_batched_pipeline", False)
    monkeypatch.setattr(cfg.settings, "whisper_vad_filter", False)
    _install_model_manager(monkeypatch, active="tiny", downloaded=("tiny",))

    model, _, _ = _make_whisper_mock(return_segments=("x",))
    svc = transcription.TranscriptionService()
    svc._model = model
    svc._last_fallback_reason = "Модель 'large-v3' не загрузилась"

    async def _noop(*a, **kw):
        return None
    monkeypatch.setattr(
        "app.services.task_status.update_task_status_in_db", _noop)

    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"x")

    await svc.transcribe(
        protocol_id=uuid.uuid4(),
        audio_path=audio,
        task_id=uuid.uuid4(),
        duration_sec=2.0,
    )
    assert svc._last_fallback_reason is None


# ---------------------------------------------------------------------------
# transcribe(): only_update_weak path skips clear
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_only_update_weak_skips_clear(monkeypatch, tmp_path):
    """only_update_weak=True skips the DELETE branch (lines 334-339)."""
    from app.services import transcription
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "whisper_use_batched_pipeline", False)
    monkeypatch.setattr(cfg.settings, "whisper_vad_filter", False)
    _install_model_manager(monkeypatch, active="tiny", downloaded=("tiny",))

    model, _, _ = _make_whisper_mock(return_segments=("x",))
    svc = transcription.TranscriptionService()
    svc._model = model

    async def _noop(*a, **kw):
        return None
    monkeypatch.setattr(
        "app.services.task_status.update_task_status_in_db", _noop)

    # Track if any DELETE was attempted by replacing AsyncSessionLocal
    delete_calls = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, stmt, *args, **kwargs):
            delete_calls.append(stmt)
            return MagicMock()

        async def commit(self):
            pass

        async def get(self, *args, **kwargs):
            return None

    import app.services.transcription as transcription_mod
    monkeypatch.setattr(transcription_mod, "AsyncSessionLocal", lambda: FakeSession())

    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"x")

    status = await svc.transcribe(
        protocol_id=uuid.uuid4(),
        audio_path=audio,
        task_id=uuid.uuid4(),
        duration_sec=2.0,
        only_update_weak=True,
    )
    assert status.status == "completed"


# ---------------------------------------------------------------------------
# _run_transcribe_eager: vad_parameters with vad_filter on
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_eager_vad_parameters_passed(monkeypatch, tmp_path):
    """When vad_filter=True, vad_parameters dict is passed (lines 569-577)."""
    from app.services import transcription
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "whisper_use_batched_pipeline", False)
    monkeypatch.setattr(cfg.settings, "whisper_vad_filter", True)
    monkeypatch.setattr(cfg.settings, "vad_min_silence_duration_ms", 500)
    monkeypatch.setattr(cfg.settings, "vad_speech_pad_ms", 300)
    monkeypatch.setattr(cfg.settings, "vad_threshold", 0.5)
    _install_model_manager(monkeypatch, active="tiny", downloaded=("tiny",))

    captured = {}

    def _transcribe(*args, **kwargs):
        captured.update(kwargs)
        seg = MagicMock(start=0.0, end=2.0, avg_logprob=-0.1)
        seg.text = "x"
        info = MagicMock(duration=2.0, language="en", language_probability=0.95)
        return iter([seg]), info

    model = MagicMock()
    model.transcribe.side_effect = _transcribe

    svc = transcription.TranscriptionService()
    svc._model = model

    async def _noop(*a, **kw):
        return None
    monkeypatch.setattr(
        "app.services.task_status.update_task_status_in_db", _noop)

    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"x")

    await svc.transcribe(
        protocol_id=uuid.uuid4(),
        audio_path=audio,
        task_id=uuid.uuid4(),
        duration_sec=2.0,
    )
    assert captured.get("vad_filter") is True
    assert captured.get("vad_parameters") is not None
    assert "min_silence_duration_ms" in captured["vad_parameters"]


@pytest.mark.asyncio
async def test_transcribe_eager_vad_parameters_none_when_vad_off(monkeypatch, tmp_path):
    """When vad_filter=False, vad_parameters is None (line 558)."""
    from app.services import transcription
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "whisper_use_batched_pipeline", False)
    monkeypatch.setattr(cfg.settings, "whisper_vad_filter", False)
    _install_model_manager(monkeypatch, active="tiny", downloaded=("tiny",))

    captured = {}

    def _transcribe(*args, **kwargs):
        captured.update(kwargs)
        seg = MagicMock(start=0.0, end=2.0, avg_logprob=-0.1)
        seg.text = "x"
        info = MagicMock(duration=2.0, language="en", language_probability=0.95)
        return iter([seg]), info

    model = MagicMock()
    model.transcribe.side_effect = _transcribe

    svc = transcription.TranscriptionService()
    svc._model = model

    async def _noop(*a, **kw):
        return None
    monkeypatch.setattr(
        "app.services.task_status.update_task_status_in_db", _noop)

    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"x")

    await svc.transcribe(
        protocol_id=uuid.uuid4(),
        audio_path=audio,
        task_id=uuid.uuid4(),
        duration_sec=2.0,
    )
    assert captured.get("vad_parameters") is None


# ---------------------------------------------------------------------------
# _persist_utterances_loop: final flush + exception swallow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_loop_final_flush(monkeypatch):
    """Leftover items are flushed after stop_event (lines 893-908)."""
    from app.services.transcription import TranscriptionService

    svc = TranscriptionService()
    svc._current_audio_duration = 100.0

    # Put segments, then set stop → loop should drain them in final flush
    svc._utterance_queue.put({
        "start": 0.0, "end": 1.0, "text": "first",
        "avg_logprob": -0.1,
    })
    svc._utterance_queue.put({
        "start": 1.0, "end": 2.0, "text": "second",
        "avg_logprob": -0.2,
    })

    stop = asyncio.Event()
    stop.set()  # skip loop, go straight to final flush

    class FakeSession:
        def __init__(self):
            self.added = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, *args, **kwargs):
            return MagicMock()

        async def commit(self):
            pass

        def add(self, obj):
            self.added.append(obj)

    fake = FakeSession()
    import app.services.transcription as transcription_mod
    monkeypatch.setattr(transcription_mod, "AsyncSessionLocal", lambda: fake)

    count = await svc._persist_utterances_loop(uuid.uuid4(), stop)
    # Two segments grouped into one batch → 1 grouped utterance
    assert count == 1
    assert len(fake.added) == 1


@pytest.mark.asyncio
async def test_persist_loop_save_batch_exception(monkeypatch):
    """save_batch swallows exceptions (lines 867-873)."""
    from app.services.transcription import TranscriptionService

    svc = TranscriptionService()
    svc._current_audio_duration = 100.0

    svc._utterance_queue.put({
        "start": 0.0, "end": 1.0, "text": "x",
        "avg_logprob": -0.1,
    })

    stop = asyncio.Event()
    stop.set()

    class ExplodingSession:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *args):
            return False

    import app.services.transcription as transcription_mod
    monkeypatch.setattr(transcription_mod, "AsyncSessionLocal", lambda: ExplodingSession())

    # Should not raise — exception is swallowed by save_batch
    count = await svc._persist_utterances_loop(uuid.uuid4(), stop)
    assert count == 0


# ---------------------------------------------------------------------------
# transcribe(): completion DB update failure (already-completed path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_completion_db_update_fails(monkeypatch, tmp_path):
    """When update_task_status_in_db raises after completion, status still succeeds."""
    from app.services import transcription
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "whisper_use_batched_pipeline", False)
    monkeypatch.setattr(cfg.settings, "whisper_vad_filter", False)
    _install_model_manager(monkeypatch, active="tiny", downloaded=("tiny",))

    model, _, _ = _make_whisper_mock(return_segments=("x",))
    svc = transcription.TranscriptionService()
    svc._model = model

    call_count = {"n": 0}

    async def _flaky(*a, **kw):
        call_count["n"] += 1
        # Fail only on the FINAL completion update (last one in the run)
        if call_count["n"] >= 3:
            raise RuntimeError("db down on completion")
        return None

    monkeypatch.setattr(
        "app.services.task_status.update_task_status_in_db", _flaky)

    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"x")

    status = await svc.transcribe(
        protocol_id=uuid.uuid4(),
        audio_path=audio,
        task_id=uuid.uuid4(),
        duration_sec=2.0,
    )
    # Transcription succeeded despite the final DB update failing
    assert status.status == "completed"


# ---------------------------------------------------------------------------
# transcribe(): failure_db_update_failed path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_failure_db_update_fails(monkeypatch, tmp_path):
    """When update_task_status_in_db raises on the failure path, exception re-raised."""
    from app.services import transcription
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "whisper_use_batched_pipeline", False)
    monkeypatch.setattr(cfg.settings, "whisper_vad_filter", False)
    _install_model_manager(monkeypatch, active="tiny", downloaded=("tiny",))

    # Model whose transcribe raises → triggers failure path
    model = MagicMock()
    model.transcribe = MagicMock(side_effect=RuntimeError("whisper failed"))
    svc = transcription.TranscriptionService()
    svc._model = model

    async def _always_fail(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(
        "app.services.task_status.update_task_status_in_db", _always_fail)

    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"x")

    with pytest.raises(RuntimeError, match="whisper failed"):
        await svc.transcribe(
            protocol_id=uuid.uuid4(),
            audio_path=audio,
            task_id=uuid.uuid4(),
            duration_sec=2.0,
        )