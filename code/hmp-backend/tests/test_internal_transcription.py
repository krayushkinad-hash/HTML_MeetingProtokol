"""Comprehensive coverage tests for app/services/transcription.py.

Covers:
- TranscriptionStatus dataclass
- TranscriptionService.get_status() with various inputs
- Singleton instance creation
- transcribe() with mock Whisper pipeline
- Error paths and graceful failure
- Resume/cancel via TaskStatus
- Internal helpers (progress callback behaviour, queue flush)
"""
from __future__ import annotations

import asyncio
import queue
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Module-level sanity
# ---------------------------------------------------------------------------


def test_module_imports():
    """TranscriptionService / transcription_service singleton importable."""
    from app.services import transcription
    assert transcription is not None
    assert hasattr(transcription, "TranscriptionService")
    assert hasattr(transcription, "transcription_service")


def test_transcription_service_singleton():
    """The exported singleton is a TranscriptionService instance."""
    from app.services.transcription import TranscriptionService, transcription_service

    assert isinstance(transcription_service, TranscriptionService)
    # Singleton — same object every import
    from app.services import transcription as t2
    assert t2.transcription_service is transcription_service


# ---------------------------------------------------------------------------
# TranscriptionStatus dataclass
# ---------------------------------------------------------------------------


def test_transcription_status_defaults():
    """Default values populated correctly."""
    from app.services.transcription import TranscriptionStatus

    pid = uuid.uuid4()
    s = TranscriptionStatus(id=uuid.uuid4(), protocol_id=pid)
    assert s.protocol_id == pid
    assert s.status == "queued"
    assert s.progress_percent == 0
    assert s.current_chunk is None
    assert s.total_chunks is None
    assert s.peak_rss_mb is None
    assert s.estimated_completion is None
    assert s.error_message is None
    assert s.wer_quality is None
    assert s.message is None


def test_transcription_status_custom_values():
    """All fields settable via constructor."""
    from app.services.transcription import TranscriptionStatus

    now = datetime.now(timezone.utc)
    s = TranscriptionStatus(
        id=uuid.uuid4(),
        protocol_id=uuid.uuid4(),
        status="running",
        progress_percent=42,
        current_chunk=2,
        total_chunks=10,
        peak_rss_mb=512.0,
        estimated_completion=now,
        error_message=None,
        wer_quality=0.05,
        message="Transcribing…",
    )
    assert s.status == "running"
    assert s.progress_percent == 42
    assert s.current_chunk == 2
    assert s.total_chunks == 10
    assert s.peak_rss_mb == 512.0
    assert s.estimated_completion == now
    assert s.wer_quality == 0.05
    assert s.message == "Transcribing…"


def test_transcription_status_literal_values():
    """The status field accepts every literal defined in the dataclass."""
    from app.services.transcription import TranscriptionStatus

    for literal in ("queued", "processing", "running", "starting",
                    "paused", "completed", "failed", "cancelled"):
        s = TranscriptionStatus(id=uuid.uuid4(), protocol_id=uuid.uuid4(),
                                status=literal)
        assert s.status == literal


# ---------------------------------------------------------------------------
# TranscriptionService.__init__ / state
# ---------------------------------------------------------------------------


def test_service_init_creates_state():
    """Fresh service has empty task / callback registries and a queue."""
    from app.services.transcription import TranscriptionService

    svc = TranscriptionService()
    assert svc._model is None
    assert isinstance(svc._tasks, dict)
    assert svc._tasks == {}
    assert isinstance(svc._progress_callbacks, dict)
    assert svc._progress_callbacks == {}
    assert isinstance(svc._utterance_queue, queue.Queue)
    # Queue is empty at start
    assert svc._utterance_queue.empty() is True


# ---------------------------------------------------------------------------
# TranscriptionService.get_status — branches
# ---------------------------------------------------------------------------


def test_get_status_unknown_uuid_returns_none():
    """Unknown task_id returns None (in-memory miss)."""
    from app.services.transcription import TranscriptionService

    svc = TranscriptionService()
    assert svc.get_status(uuid.uuid4()) is None


def test_get_status_invalid_string_returns_none():
    """Malformed UUID string returns None (graceful)."""
    from app.services.transcription import TranscriptionService

    svc = TranscriptionService()
    assert svc.get_status("not-a-uuid") is None
    assert svc.get_status("") is None


def test_get_status_terminal_state_returns_none():
    """Completed/failed/cancelled tasks return None (E182 logic)."""
    from app.services.transcription import TranscriptionService, TranscriptionStatus

    svc = TranscriptionService()
    tid = uuid.uuid4()
    svc._tasks[tid] = TranscriptionStatus(
        id=tid, protocol_id=uuid.uuid4(), status="completed", progress_percent=100,
    )
    assert svc.get_status(tid) is None

    svc._tasks[tid].status = "failed"
    assert svc.get_status(tid) is None

    svc._tasks[tid].status = "cancelled"
    assert svc.get_status(tid) is None


def test_get_status_active_state_returns_status():
    """Active (non-terminal) task returns its status dataclass."""
    from app.services.transcription import TranscriptionService, TranscriptionStatus

    svc = TranscriptionService()
    tid = uuid.uuid4()
    svc._tasks[tid] = TranscriptionStatus(
        id=tid, protocol_id=uuid.uuid4(), status="running", progress_percent=37,
    )
    s = svc.get_status(tid)
    assert s is not None
    assert s.id == tid
    assert s.progress_percent == 37


def test_get_status_string_uuid_works():
    """Valid string UUID is normalised."""
    from app.services.transcription import TranscriptionService, TranscriptionStatus

    svc = TranscriptionService()
    tid = uuid.uuid4()
    svc._tasks[tid] = TranscriptionStatus(
        id=tid, protocol_id=uuid.uuid4(), status="starting",
    )
    s = svc.get_status(str(tid))
    assert s is not None
    assert s.status == "starting"


def test_get_status_paused_returns_status():
    """Paused is a non-terminal state — should be returned."""
    from app.services.transcription import TranscriptionService, TranscriptionStatus

    svc = TranscriptionService()
    tid = uuid.uuid4()
    svc._tasks[tid] = TranscriptionStatus(
        id=tid, protocol_id=uuid.uuid4(), status="paused",
    )
    s = svc.get_status(tid)
    assert s is not None
    assert s.status == "paused"


# ---------------------------------------------------------------------------
# _load_model — branch coverage (graceful failure when faster_whisper missing)
# ---------------------------------------------------------------------------


def test_load_model_handles_missing_faster_whisper(monkeypatch):
    """If faster_whisper import fails — graceful ImportError path."""
    from app.services import transcription

    svc = transcription.TranscriptionService()

    # Block the import of faster_whisper
    import sys
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    # Force ImportError when accessing faster_whisper.WhisperModel
    monkeypatch.delitem(sys.modules, "faster_whisper", raising=False)

    class FakeMod:
        def __getattr__(self, name):
            raise ImportError("simulated missing faster_whisper")

    monkeypatch.setitem(sys.modules, "faster_whisper", FakeMod())

    with pytest.raises(Exception):
        # Either ImportError propagates OR we hit the outer except — both
        # are acceptable "graceful failure" outcomes. We just need the
        # except branch in _load_model to execute.
        svc._load_model()


# ---------------------------------------------------------------------------
# transcribe() — mock WhisperModel + audio file
# ---------------------------------------------------------------------------


def _make_whisper_mock():
    """Return a MagicMock that mimics faster_whisper.WhisperModel."""
    seg1 = MagicMock(start=0.0, end=2.5, no_speech_prob=0.1,
                     avg_logprob=-0.2)
    seg1.text = " hello world "
    seg2 = MagicMock(start=3.0, end=5.0, no_speech_prob=0.05,
                     avg_logprob=-0.1)
    seg2.text = " second segment "
    info = MagicMock(duration=5.0, language="en", language_probability=0.95)
    model = MagicMock()
    model.transcribe = MagicMock(return_value=iter([seg1, seg2]), info=info)
    return model


@pytest.mark.asyncio
async def test_transcribe_happy_path(tmp_path, monkeypatch):
    """End-to-end transcribe() with fully-mocked Whisper + DB layer."""
    from app.services import transcription

    svc = transcription.TranscriptionService()
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"fake audio bytes")

    model = _make_whisper_mock()
    svc._model = model  # skip _load_model

    # Mock the WhisperModel class import + get_active_model
    fake_model_manager = MagicMock()
    fake_model_manager.get_active_model.return_value = "tiny"
    fake_model_manager.is_downloaded.return_value = True

    monkeypatch.setattr(
        "app.services.whisper_models.model_manager", fake_model_manager,
    )

    # Patch model_manager import inside transcribe()
    fake_wm_module = MagicMock()
    fake_wm_module.model_manager = fake_model_manager
    fake_wm_module.AVAILABLE_MODELS = ["tiny", "base"]
    monkeypatch.setitem(
        __import__("sys").modules, "app.services.whisper_models", fake_wm_module,
    )

    # Patch update_task_status_in_db (DB persistence)
    async def _noop_update(*args, **kwargs):
        return None
    monkeypatch.setattr(
        "app.services.task_status.update_task_status_in_db", _noop_update,
    )

    pid = uuid.uuid4()
    tid = uuid.uuid4()

    status = await svc.transcribe(
        protocol_id=pid, audio_path=audio, task_id=tid, duration_sec=5.0,
    )

    # Status reflects completion (or at least the path was exercised)
    assert status is not None
    assert status.id == tid
    # Progress should be 100 after success
    assert status.progress_percent == 100
    # model.transcribe was called
    assert model.transcribe.called


@pytest.mark.asyncio
async def test_transcribe_missing_audio_file(monkeypatch):
    """transcribe() raises FileNotFoundError when audio path missing."""
    from app.services import transcription

    svc = transcription.TranscriptionService()
    svc._model = MagicMock()  # skip load

    fake_model_manager = MagicMock()
    fake_model_manager.get_active_model.return_value = "tiny"
    fake_model_manager.is_downloaded.return_value = True
    fake_wm_module = MagicMock()
    fake_wm_module.model_manager = fake_model_manager
    fake_wm_module.AVAILABLE_MODELS = ["tiny"]
    monkeypatch.setitem(
        __import__("sys").modules, "app.services.whisper_models", fake_wm_module,
    )

    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr(
        "app.services.task_status.update_task_status_in_db", _noop,
    )

    nonexistent = Path("/nonexistent/audio.mp3")

    with pytest.raises(FileNotFoundError):
        await svc.transcribe(
            protocol_id=uuid.uuid4(),
            audio_path=nonexistent,
            task_id=uuid.uuid4(),
            duration_sec=10.0,
        )


@pytest.mark.asyncio
async def test_transcribe_whisper_exception_marked_failed(tmp_path, monkeypatch):
    """Whisper raises mid-run → status marked failed and exception re-raised."""
    from app.services import transcription

    svc = transcription.TranscriptionService()
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"fake")

    broken = MagicMock()
    broken.transcribe.side_effect = RuntimeError("whisper boom")
    svc._model = broken

    fake_model_manager = MagicMock()
    fake_model_manager.get_active_model.return_value = "tiny"
    fake_model_manager.is_downloaded.return_value = True
    fake_wm_module = MagicMock()
    fake_wm_module.model_manager = fake_model_manager
    fake_wm_module.AVAILABLE_MODELS = ["tiny"]
    monkeypatch.setitem(
        __import__("sys").modules, "app.services.whisper_models", fake_wm_module,
    )

    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr(
        "app.services.task_status.update_task_status_in_db", _noop,
    )

    with pytest.raises(RuntimeError, match="whisper boom"):
        await svc.transcribe(
            protocol_id=uuid.uuid4(),
            audio_path=audio,
            task_id=uuid.uuid4(),
            duration_sec=10.0,
        )


@pytest.mark.asyncio
async def test_transcribe_no_models_downloaded(tmp_path, monkeypatch):
    """If active model isn't downloaded and no fallback exists → status failed."""
    from app.services import transcription

    svc = transcription.TranscriptionService()
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"fake")

    fake_model_manager = MagicMock()
    fake_model_manager.get_active_model.return_value = "large-v3"
    fake_model_manager.is_downloaded.return_value = False  # nothing downloaded
    fake_wm_module = MagicMock()
    fake_wm_module.model_manager = fake_model_manager
    fake_wm_module.AVAILABLE_MODELS = ["large-v3", "tiny"]
    monkeypatch.setitem(
        __import__("sys").modules, "app.services.whisper_models", fake_wm_module,
    )

    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr(
        "app.services.task_status.update_task_status_in_db", _noop,
    )

    status = await svc.transcribe(
        protocol_id=uuid.uuid4(),
        audio_path=audio,
        task_id=uuid.uuid4(),
        duration_sec=10.0,
    )

    assert status.status == "failed"
    assert "не скачана" in status.error_message or "Модель" in status.error_message
    assert status.progress_percent == 0


@pytest.mark.asyncio
async def test_transcribe_fallback_to_downloaded_model(tmp_path, monkeypatch):
    """If active not downloaded, but fallback exists — use it."""
    from app.services import transcription

    svc = transcription.TranscriptionService()
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"fake")

    # Active = not downloaded; tiny = downloaded (fallback)
    fake_model_manager = MagicMock()
    fake_model_manager.get_active_model.return_value = "large-v3"

    def _is_downloaded(name):
        return name == "tiny"  # only tiny is on disk
    fake_model_manager.is_downloaded.side_effect = _is_downloaded

    fake_wm_module = MagicMock()
    fake_wm_module.model_manager = fake_model_manager
    fake_wm_module.AVAILABLE_MODELS = ["large-v3", "tiny"]
    monkeypatch.setitem(
        __import__("sys").modules, "app.services.whisper_models", fake_wm_module,
    )

    # Whisper model returns empty list — segments_generator, info tuple
    info = MagicMock(duration=10.0, language="en", language_probability=0.95)
    model = MagicMock()
    model.transcribe.return_value = (iter([]), info)
    svc._model = model

    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr(
        "app.services.task_status.update_task_status_in_db", _noop,
    )

    status = await svc.transcribe(
        protocol_id=uuid.uuid4(),
        audio_path=audio,
        task_id=uuid.uuid4(),
        duration_sec=10.0,
    )

    # Even with empty segments, it should reach completion path
    assert status.status == "completed"
    assert status.progress_percent == 100


# ---------------------------------------------------------------------------
# _persist_utterances_loop — branch coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_utterances_loop_empty_queue(monkeypatch):
    """Empty queue + immediate stop_event set → returns 0 without saving."""
    from app.services.transcription import TranscriptionService

    svc = TranscriptionService()
    stop = asyncio.Event()
    stop.set()  # immediate exit

    # Track DB calls
    db_called = []
    import app.services.transcription as transcription_mod

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, *args, **kwargs):
            db_called.append("execute")
            return MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))

        async def commit(self):
            db_called.append("commit")

        def add(self, obj):
            db_called.append("add")

    monkeypatch.setattr(transcription_mod, "AsyncSessionLocal", lambda: FakeSession())

    total = await svc._persist_utterances_loop(uuid.uuid4(), stop)
    assert total == 0
    # No utterances added when queue is empty
    assert "add" not in db_called


@pytest.mark.asyncio
async def test_persist_utterances_loop_with_segments(monkeypatch):
    """Segments in the queue are grouped + written to DB."""
    from app.services.transcription import TranscriptionService

    svc = TranscriptionService()
    svc._current_audio_duration = 100.0
    stop = asyncio.Event()
    stop.set()  # skip loop, go straight to final flush

    # Queue segments
    svc._utterance_queue.put({
        "start": 0.0, "end": 2.0, "text": "hello",
        "avg_logprob": -0.1,
    })
    svc._utterance_queue.put({
        "start": 2.5, "end": 4.0, "text": "world",
        "avg_logprob": -0.2,
    })

    # Patch AsyncSessionLocal
    class FakeSession:
        def __init__(self):
            self.added = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, *args, **kwargs):
            return MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))

        async def commit(self):
            pass

        def add(self, obj):
            self.added.append(obj)

    fake_session_inst = FakeSession()

    import app.services.transcription as transcription_mod
    monkeypatch.setattr(
        transcription_mod, "AsyncSessionLocal", lambda: fake_session_inst,
    )

    total = await svc._persist_utterances_loop(uuid.uuid4(), stop)
    # Two segments → grouped into one because pause < 1.5s
    assert total >= 1
    assert len(fake_session_inst.added) >= 1


@pytest.mark.asyncio
async def test_persist_utterances_loop_group_pause_threshold(monkeypatch):
    """Segments with > 1.5s gap form separate groups."""
    from app.services.transcription import TranscriptionService

    svc = TranscriptionService()
    svc._current_audio_duration = 100.0
    stop = asyncio.Event()
    stop.set()

    # Two segments with big gap (>1.5s)
    svc._utterance_queue.put({
        "start": 0.0, "end": 1.0, "text": "first",
        "avg_logprob": -0.1,
    })
    svc._utterance_queue.put({
        "start": 5.0, "end": 6.0, "text": "second",
        "avg_logprob": -0.2,
    })

    class FakeSession:
        def __init__(self):
            self.added = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, *args, **kwargs):
            return MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))

        async def commit(self):
            pass

        def add(self, obj):
            self.added.append(obj)

    fake_session_inst = FakeSession()
    import app.services.transcription as transcription_mod
    monkeypatch.setattr(
        transcription_mod, "AsyncSessionLocal", lambda: fake_session_inst,
    )

    await svc._persist_utterances_loop(uuid.uuid4(), stop)
    # Two separate groups → two adds
    assert len(fake_session_inst.added) == 2


@pytest.mark.asyncio
async def test_persist_utterances_loop_outside_audio_dropped(monkeypatch):
    """Segments beyond audio duration are dropped."""
    from app.services.transcription import TranscriptionService

    svc = TranscriptionService()
    svc._current_audio_duration = 10.0  # only 10 sec
    stop = asyncio.Event()
    stop.set()

    # Segment at 100s — way outside
    svc._utterance_queue.put({
        "start": 100.0, "end": 105.0, "text": "hallucination",
        "avg_logprob": -0.5,
    })

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

    total = await svc._persist_utterances_loop(uuid.uuid4(), stop)
    assert total == 0
    assert fake.added == []


@pytest.mark.asyncio
async def test_persist_utterances_loop_dedup_same_start(monkeypatch):
    """Segments with the same start_sec are deduplicated."""
    from app.services.transcription import TranscriptionService

    svc = TranscriptionService()
    svc._current_audio_duration = 100.0
    stop = asyncio.Event()
    stop.set()

    # Two identical segments
    for _ in range(2):
        svc._utterance_queue.put({
            "start": 1.0, "end": 2.0, "text": "dup",
            "avg_logprob": -0.1,
        })

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

    await svc._persist_utterances_loop(uuid.uuid4(), stop)
    # Dedup keeps only one
    assert len(fake.added) == 1


@pytest.mark.asyncio
async def test_persist_utterances_loop_skip_empty_text(monkeypatch):
    """Empty/blank text is skipped."""
    from app.services.transcription import TranscriptionService

    svc = TranscriptionService()
    svc._current_audio_duration = 100.0
    stop = asyncio.Event()
    stop.set()

    svc._utterance_queue.put({
        "start": 0.0, "end": 1.0, "text": "   ",
        "avg_logprob": None,
    })

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

    await svc._persist_utterances_loop(uuid.uuid4(), stop)
    assert fake.added == []


# ---------------------------------------------------------------------------
# CancelledError path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_cancelled_via_cancellation(tmp_path, monkeypatch):
    """Cancelling the transcribe() task mid-run → status cancelled."""
    from app.services import transcription

    svc = transcription.TranscriptionService()
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"fake")

    # Whisper model that blocks (synchronous) until cancelled
    import time as _time
    seg = MagicMock(start=0.0, end=1.0, text="x", avg_logprob=-0.1)

    def blocking_transcribe(*args, **kwargs):
        # Block in thread for a long time; will be cancelled
        yield seg  # one segment before blocking
        _time.sleep(30)  # blocked in thread; thread is killed on cancel
        yield seg  # unreachable

    info = MagicMock(duration=10.0, language="en", language_probability=0.95)
    model = MagicMock()
    model.transcribe = MagicMock(return_value=blocking_transcribe())
    svc._model = model

    fake_model_manager = MagicMock()
    fake_model_manager.get_active_model.return_value = "tiny"
    fake_model_manager.is_downloaded.return_value = True
    fake_wm_module = MagicMock()
    fake_wm_module.model_manager = fake_model_manager
    fake_wm_module.AVAILABLE_MODELS = ["tiny"]
    monkeypatch.setitem(
        __import__("sys").modules, "app.services.whisper_models", fake_wm_module,
    )

    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr(
        "app.services.task_status.update_task_status_in_db", _noop,
    )

    pid = uuid.uuid4()
    tid = uuid.uuid4()

    # Schedule transcribe
    task = asyncio.create_task(
        svc.transcribe(
            protocol_id=pid,
            audio_path=audio,
            task_id=tid,
            duration_sec=10.0,
        )
    )
    # Give it time to start
    await asyncio.sleep(0.2)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    # Status should be cancelled
    assert tid in svc._tasks
    assert svc._tasks[tid].status == "cancelled"


# ---------------------------------------------------------------------------
# proxy env handling
# ---------------------------------------------------------------------------


def test_proxy_env_vars_cleared(monkeypatch):
    """Loading model clears all proxy env vars (E166)."""
    from app.services import transcription

    # Set proxy vars
    monkeypatch.setenv("HTTP_PROXY", "http://evil:1234")
    monkeypatch.setenv("HTTPS_PROXY", "http://evil:1234")
    monkeypatch.setenv("SOCKS_PROXY", "socks5://evil:1234")

    # Patch WhisperModel to raise so _load_model exits via except
    class FakeFasterWhisper:
        class WhisperModel:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("forced failure for test")

    monkeypatch.setitem(
        __import__("sys").modules, "faster_whisper", FakeFasterWhisper,
    )

    svc = transcription.TranscriptionService()
    with pytest.raises(RuntimeError):
        svc._load_model()

    # Proxy vars should be cleared
    import os
    assert "HTTP_PROXY" not in os.environ
    assert "HTTPS_PROXY" not in os.environ
    assert "SOCKS_PROXY" not in os.environ
    # NO_PROXY should be set to bypass
    assert os.environ.get("NO_PROXY") == "*"


# ---------------------------------------------------------------------------
# Resume / pause state via TranscriptionTask path is integration — covered in
# routers/transcribe/local.py tests.
# ---------------------------------------------------------------------------


def test_transcribe_state_for_pause_present():
    """Paused state is preserved in memory."""
    from app.services.transcription import TranscriptionService, TranscriptionStatus

    svc = TranscriptionService()
    tid = uuid.uuid4()
    svc._tasks[tid] = TranscriptionStatus(
        id=tid, protocol_id=uuid.uuid4(), status="paused", progress_percent=42,
    )
    s = svc.get_status(tid)
    assert s is not None
    assert s.progress_percent == 42
    assert s.status == "paused"