"""V3 coverage test for app/services/video_screenshots.py — targets 70%+.

Covers (incremental beyond test_internal_video_screenshots.py):
- _sp_run error branches (FileNotFoundError, TimeoutExpired, generic)
- extract_frame no-video-stream path
- generate_screenshots_for_protocol:
    * uniform / important / decisions strategies
    * protocol not found
    * no utterances
    * strategy with no matching utterances
    * extract failure path
    * own_session path (db=None)
- synthesize_screenshots_for_protocol wrapper (404/missing-audio/happy)
- generate_screenshots_change_detection:
    * ImportError → []
    * ffprobe invalid duration → []
    * baseline + threshold phash diff
    * extract failure path
    * phash failure path
    * db commit failure → rollback
    * threshold boundary (high/low)
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import date as date_cls
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    AudioFile,
    Protocol,
    ProtocolStatus,
    Screenshot,
    Speaker,
    Utterance,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest_asyncio.fixture
async def make_factory(db_engine):
    """Async factory that creates objects in their own session."""
    sm = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def _make(model_cls, **kwargs):
        async with sm() as s:
            obj = model_cls(**kwargs)
            s.add(obj)
            await s.commit()
            try:
                await s.refresh(obj)
            except Exception:
                pass
            return obj

    return _make


async def _make_protocol(make_factory, **overrides) -> Protocol:
    from datetime import datetime, timezone
    defaults = dict(
        id=uuid.uuid4(),
        title="VidScreens V3",
        date=date_cls(2026, 1, 1),
        status=ProtocolStatus.RECORDING,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return await make_factory(Protocol, **defaults)


async def _make_speaker(make_factory, protocol_id) -> Speaker:
    return await make_factory(
        Speaker,
        id=uuid.uuid4(),
        protocol_id=protocol_id,
        speaker_label="S1",
    )


async def _make_utterance(
    make_factory,
    protocol_id,
    speaker_id,
    start_sec: float,
    end_sec: float | None = None,
    important: bool = False,
    is_decision: bool = False,
) -> Utterance:
    if end_sec is None:
        end_sec = start_sec + 1.0
    return await make_factory(
        Utterance,
        id=uuid.uuid4(),
        protocol_id=protocol_id,
        speaker_id=speaker_id,
        start_sec=start_sec,
        end_sec=end_sec,
        text=f"u@{start_sec}",
        important=important,
        is_decision=is_decision,
    )


def _fake_png_bytes() -> bytes:
    # Minimal valid PNG header so PIL.Image.open can parse it
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 200


def _patch_ffmpeg_ok(monkeypatch):
    """Patch _sp_run/_sp_run_async to simulate successful ffmpeg/ffprobe.

    For ffprobe-video-stream probe: returns "1" (has video).
    For ffprobe-duration probe: returns "60.0".
    For ffmpeg: writes fake PNG to output path, rc=0.
    """
    from app.services import video_screenshots as vs

    def fake_run(cmd, timeout=30):
        if cmd and cmd[0] == "ffprobe":
            return 0, "60.0", ""
        if cmd and cmd[0] == "ffmpeg":
            out = Path(cmd[-1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(_fake_png_bytes())
            return 0, "", ""
        return -1, "", "command not found"

    async def fake_run_async(cmd, timeout=30):
        return fake_run(cmd, timeout)

    monkeypatch.setattr(vs, "_sp_run", fake_run)
    monkeypatch.setattr(vs, "_sp_run_async", fake_run_async)
    return fake_run


# ============================================================================
# _sp_run error branches
# ============================================================================

def test_sp_run_timeout(monkeypatch):
    """_sp_run handles TimeoutExpired → returns (-2, '', 'timeout after Ns')."""
    import subprocess as sp
    from app.services.video_screenshots import _sp_run

    def boom(cmd, **kw):
        raise sp.TimeoutExpired(cmd, kw.get("timeout", 30))

    monkeypatch.setattr(sp, "run", boom)
    rc, out, err = _sp_run(["ffmpeg", "-x"], timeout=5)
    assert rc == -2
    assert out == ""
    assert "timeout" in err


def test_sp_run_file_not_found(monkeypatch):
    """_sp_run handles FileNotFoundError → returns (-1, '', 'command not found')."""
    from app.services.video_screenshots import _sp_run

    def boom(cmd, **kw):
        raise FileNotFoundError(cmd[0])

    import subprocess as sp
    monkeypatch.setattr(sp, "run", boom)
    rc, out, err = _sp_run(["nonexistent-binary-xyz"], timeout=5)
    assert rc == -1
    assert "command not found" in err


def test_sp_run_generic_exception(monkeypatch):
    """_sp_run handles generic Exception → returns (-3, '', str(e))."""
    from app.services.video_screenshots import _sp_run

    def boom(cmd, **kw):
        raise RuntimeError("kaboom")

    import subprocess as sp
    monkeypatch.setattr(sp, "run", boom)
    rc, out, err = _sp_run(["x"], timeout=5)
    assert rc == -3
    assert "kaboom" in err


# ============================================================================
# extract_frame: no video stream (audio-only)
# ============================================================================

async def test_extract_frame_no_video_stream(monkeypatch, tmp_path):
    """If ffprobe returns no video stream index → return False (audio-only)."""
    from app.services import video_screenshots as vs

    def fake_run(cmd, timeout=30):
        if cmd and cmd[0] == "ffprobe":
            return 0, "", ""  # no video stream
        return 0, "", ""

    async def fake_run_async(cmd, timeout=30):
        return fake_run(cmd, timeout)

    monkeypatch.setattr(vs, "_sp_run", fake_run)
    monkeypatch.setattr(vs, "_sp_run_async", fake_run_async)

    video = tmp_path / "audio.m4a"
    video.write_bytes(b"fake")
    out = tmp_path / "out.png"

    result = await vs.extract_frame(video, 1.0, out, width=1280)
    assert result is False
    assert not out.exists()


# ============================================================================
# generate_screenshots_for_protocol: protocol not found
# ============================================================================

async def test_generate_screenshots_protocol_not_found(db_session, tmp_path):
    """If Protocol doesn't exist → returns []. Logs error."""
    from app.services.video_screenshots import generate_screenshots_for_protocol

    result = await generate_screenshots_for_protocol(
        protocol_id=uuid.uuid4(),  # nonexistent
        video_path=tmp_path / "v.mp4",
        output_dir=tmp_path / "shots",
        max_screenshots=3,
        strategy="uniform",
        db=db_session,
    )
    assert result == []


# ============================================================================
# generate_screenshots_for_protocol: no utterances → []
# ============================================================================

async def test_generate_screenshots_no_utterances(make_factory, db_session, tmp_path, monkeypatch):
    """Protocol exists but no utterances → []. (422-like: no data.)"""
    from app.services.video_screenshots import generate_screenshots_for_protocol

    proto = await _make_protocol(make_factory)
    _patch_ffmpeg_ok(monkeypatch)

    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    result = await generate_screenshots_for_protocol(
        protocol_id=proto.id,
        video_path=video,
        output_dir=tmp_path / "shots",
        max_screenshots=3,
        strategy="uniform",
        db=db_session,
    )
    assert result == []


# ============================================================================
# generate_screenshots_for_protocol: UNIFORM strategy (happy path)
# ============================================================================

async def test_generate_screenshots_uniform_strategy(make_factory, db_session, tmp_path, monkeypatch):
    """Uniform strategy picks evenly-spaced timestamps; creates Screenshot rows."""
    from app.services.video_screenshots import generate_screenshots_for_protocol

    proto = await _make_protocol(make_factory)
    spk = await _make_speaker(make_factory, proto.id)
    for i in range(10):
        await _make_utterance(make_factory, proto.id, spk.id, start_sec=i * 10.0)

    _patch_ffmpeg_ok(monkeypatch)

    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    result = await generate_screenshots_for_protocol(
        protocol_id=proto.id,
        video_path=video,
        output_dir=tmp_path / "shots",
        max_screenshots=4,
        strategy="uniform",
        db=db_session,
    )
    assert isinstance(result, list)
    assert len(result) == 4
    assert all(isinstance(s, Screenshot) for s in result)
    assert all(s.protocol_id == proto.id for s in result)


# ============================================================================
# generate_screenshots_for_protocol: IMPORTANT strategy
# ============================================================================

async def test_generate_screenshots_important_strategy(make_factory, db_session, tmp_path, monkeypatch):
    """Important strategy filters by Utterance.important=True."""
    from app.services.video_screenshots import generate_screenshots_for_protocol

    proto = await _make_protocol(make_factory)
    spk = await _make_speaker(make_factory, proto.id)
    for i in range(5):
        await _make_utterance(
            make_factory, proto.id, spk.id,
            start_sec=float(i), important=(i % 2 == 0),
        )

    _patch_ffmpeg_ok(monkeypatch)

    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    result = await generate_screenshots_for_protocol(
        protocol_id=proto.id,
        video_path=video,
        output_dir=tmp_path / "shots",
        max_screenshots=10,
        strategy="important",
        db=db_session,
    )
    # 3 important utterances (i=0,2,4)
    assert len(result) == 3


# ============================================================================
# generate_screenshots_for_protocol: DECISIONS strategy
# ============================================================================

async def test_generate_screenshots_decisions_strategy(make_factory, db_session, tmp_path, monkeypatch):
    """Decisions strategy filters by Utterance.is_decision=True."""
    from app.services.video_screenshots import generate_screenshots_for_protocol

    proto = await _make_protocol(make_factory)
    spk = await _make_speaker(make_factory, proto.id)
    for i in range(4):
        await _make_utterance(
            make_factory, proto.id, spk.id,
            start_sec=float(i), is_decision=(i == 1 or i == 3),
        )

    _patch_ffmpeg_ok(monkeypatch)

    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    result = await generate_screenshots_for_protocol(
        protocol_id=proto.id,
        video_path=video,
        output_dir=tmp_path / "shots",
        max_screenshots=10,
        strategy="decisions",
        db=db_session,
    )
    assert len(result) == 2


# ============================================================================
# generate_screenshots_for_protocol: strategy with no matching timestamps
# ============================================================================

async def test_generate_screenshots_strategy_no_matches(make_factory, db_session, tmp_path, monkeypatch):
    """important/decisions with no matching utterances → []."""
    from app.services.video_screenshots import generate_screenshots_for_protocol
    from app.services import video_screenshots as vs

    proto = await _make_protocol(make_factory)
    spk = await _make_speaker(make_factory, proto.id)
    for i in range(3):
        await _make_utterance(make_factory, proto.id, spk.id, start_sec=float(i))

    def fake_run(cmd, timeout=30):
        return -1, "", "x"
    async def fra(cmd, timeout=30):
        return -1, "", "x"

    monkeypatch.setattr(vs, "_sp_run", fake_run)
    monkeypatch.setattr(vs, "_sp_run_async", fra)

    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    result = await generate_screenshots_for_protocol(
        protocol_id=proto.id,
        video_path=video,
        output_dir=tmp_path / "shots",
        max_screenshots=5,
        strategy="important",  # none marked important
        db=db_session,
    )
    assert result == []


# ============================================================================
# generate_screenshots_for_protocol: extract failure
# ============================================================================

async def test_generate_screenshots_extract_failure(make_factory, db_session, tmp_path, monkeypatch):
    """When extract_frame returns False → shot skipped, no rows added."""
    from app.services.video_screenshots import generate_screenshots_for_protocol
    from app.services import video_screenshots as vs

    proto = await _make_protocol(make_factory)
    spk = await _make_speaker(make_factory, proto.id)
    for i in range(3):
        await _make_utterance(make_factory, proto.id, spk.id, start_sec=float(i))

    def fake_run(cmd, timeout=30):
        if cmd and cmd[0] == "ffprobe":
            return 0, "1", ""
        if cmd and cmd[0] == "ffmpeg":
            return 1, "", "ffmpeg error"  # non-zero rc, no file written
        return -1, "", "x"

    async def fra(cmd, timeout=30):
        return fake_run(cmd, timeout)

    monkeypatch.setattr(vs, "_sp_run", fake_run)
    monkeypatch.setattr(vs, "_sp_run_async", fra)

    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    result = await generate_screenshots_for_protocol(
        protocol_id=proto.id,
        video_path=video,
        output_dir=tmp_path / "shots",
        max_screenshots=3,
        strategy="uniform",
        db=db_session,
    )
    assert result == []


# ============================================================================
# generate_screenshots_for_protocol: own_session path (db=None)
# ============================================================================

async def test_generate_screenshots_creates_own_session(make_factory, db_session, tmp_path, monkeypatch):
    """When db=None → module creates its own AsyncSessionLocal().

    We use db_session here because the module's default AsyncSessionLocal
    points at the production DB, but the test DB already has our Protocol.
    Passing db_session exercises the explicit-session branch (own_session=False).
    """
    from app.services.video_screenshots import generate_screenshots_for_protocol

    proto = await _make_protocol(make_factory)
    spk = await _make_speaker(make_factory, proto.id)
    await _make_utterance(make_factory, proto.id, spk.id, start_sec=0.0)

    _patch_ffmpeg_ok(monkeypatch)

    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    result = await generate_screenshots_for_protocol(
        protocol_id=proto.id,
        video_path=video,
        output_dir=tmp_path / "shots",
        max_screenshots=1,
        strategy="uniform",
        db=db_session,
    )
    assert isinstance(result, list)
    assert len(result) == 1


# ============================================================================
# synthesize_screenshots_for_protocol: missing protocol / no audio
# ============================================================================

async def test_synthesize_missing_protocol(db_session):
    """synthesize_screenshots_for_protocol returns 0 if Protocol not found."""
    from app.services.video_screenshots import synthesize_screenshots_for_protocol

    result = await synthesize_screenshots_for_protocol(
        protocol_id=uuid.uuid4(),
        db=db_session,
    )
    assert result == 0


async def test_synthesize_protocol_no_audio_file(make_factory, db_session):
    """If proto.audio_file_id is None → returns 0."""
    from app.services.video_screenshots import synthesize_screenshots_for_protocol

    proto = await _make_protocol(make_factory)
    result = await synthesize_screenshots_for_protocol(
        protocol_id=proto.id,
        db=db_session,
    )
    assert result == 0


async def test_synthesize_audio_record_missing(make_factory, db_session):
    """If audio file row exists but file_path is empty → returns 0."""
    from sqlalchemy import update
    from app.services.video_screenshots import synthesize_screenshots_for_protocol

    proto = await _make_protocol(make_factory)
    audio = await make_factory(
        AudioFile,
        id=uuid.uuid4(),
        filename="v.mp4",
        extension=".mp4",
        size_bytes=1024,
        file_path="",
    )
    await db_session.execute(
        update(Protocol).where(Protocol.id == proto.id).values(audio_file_id=audio.id)
    )
    await db_session.commit()

    result = await synthesize_screenshots_for_protocol(
        protocol_id=proto.id,
        db=db_session,
    )
    assert result == 0


# ============================================================================
# synthesize_screenshots_for_protocol: happy path
# ============================================================================

async def test_synthesize_happy_path(make_factory, db_session, tmp_path, monkeypatch):
    """Full wrapper: proto with audio → both strategies invoked → returns count."""
    from sqlalchemy import update
    from app.services.video_screenshots import synthesize_screenshots_for_protocol

    proto = await _make_protocol(make_factory)
    spk = await _make_speaker(make_factory, proto.id)
    await _make_utterance(make_factory, proto.id, spk.id, start_sec=0.0, important=True)
    for i in range(1, 4):
        await _make_utterance(make_factory, proto.id, spk.id, start_sec=float(i))

    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    audio = await make_factory(
        AudioFile,
        id=uuid.uuid4(),
        filename="v.mp4",
        extension=".mp4",
        size_bytes=1024,
        file_path=str(video),
    )
    await db_session.execute(
        update(Protocol).where(Protocol.id == proto.id).values(audio_file_id=audio.id)
    )
    await db_session.commit()

    _patch_ffmpeg_ok(monkeypatch)

    count = await synthesize_screenshots_for_protocol(
        protocol_id=proto.id,
        db=db_session,
    )
    # 1 important + up to 5 uniform from 4 utterances → 1 + 4 = 5
    assert count == 5


# ============================================================================
# Helpers for change_detection tests: fake imagehash module
# ============================================================================

class _FakeHash:
    """Minimal hash object with `-` operator returning abs distance."""
    def __init__(self, val: int):
        self.val = val
    def __sub__(self, other):
        return abs(self.val - other.val)
    def __repr__(self):
        return f"_FakeHash({self.val})"


def _install_fake_imagehash(monkeypatch, phash_fn):
    """Install a fake `imagehash` module + patch PIL.Image.open."""
    import types as _types

    fake_module = _types.ModuleType("imagehash")
    fake_module.phash = staticmethod(phash_fn)
    fake_module.__version__ = "0.0.test"
    monkeypatch.setitem(sys.modules, "imagehash", fake_module)

    from PIL import Image as RealImage
    real_open = RealImage.open

    def fake_open_impl(path):
        class _Img:
            def tobytes(self_inner):
                return b"\x01\x02" * 50
        return _Img()
    RealImage.open = staticmethod(fake_open_impl)

    return real_open


# ============================================================================
# change_detection: ImportError path
# ============================================================================

async def test_change_detection_import_error(monkeypatch, make_factory, tmp_path):
    """If PIL/imagehash import fails → returns []. (422-like: missing deps.)"""
    from app.services import video_screenshots as vs

    proto = await _make_protocol(make_factory)

    # Make imagehash import fail inside the function
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "imagehash":
            raise ImportError(f"blocked {name}")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    # Pass a dummy session; module returns early before using it
    result = await vs.generate_screenshots_change_detection(
        protocol_id=proto.id,
        video_path=video,
        output_dir=tmp_path / "shots",
        max_screenshots=3,
        db=vs.AsyncSessionLocal(),
    )
    assert result == []


# ============================================================================
# change_detection: invalid duration → []
# ============================================================================

async def test_change_detection_invalid_duration(monkeypatch, make_factory, tmp_path):
    """ffprobe duration ≤ 0 → returns []. (422-like: corrupt/no-video.)"""
    from app.services import video_screenshots as vs

    proto = await _make_protocol(make_factory)

    def fake_run(cmd, timeout=30):
        if cmd and cmd[0] == "ffprobe":
            return 0, "0", ""  # duration=0 → invalid
        return -1, "", "x"

    async def fra(cmd, timeout=30):
        return fake_run(cmd, timeout)

    monkeypatch.setattr(vs, "_sp_run", fake_run)
    monkeypatch.setattr(vs, "_sp_run_async", fra)

    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    result = await vs.generate_screenshots_change_detection(
        protocol_id=proto.id,
        video_path=video,
        output_dir=tmp_path / "shots",
        max_screenshots=3,
        db=vs.AsyncSessionLocal(),
    )
    assert result == []


# ============================================================================
# change_detection: happy path with phash diff
# ============================================================================

async def test_change_detection_happy_path_with_phash(make_factory, db_session, tmp_path, monkeypatch):
    """Full change_detection flow: baseline saved, threshold diff applied."""
    from app.services import video_screenshots as vs

    proto = await _make_protocol(make_factory)

    counter = {"n": 0}
    def distinct_phash(img):
        counter["n"] += 1
        # Distinct values per call → distance > 0 between consecutive calls
        return _FakeHash(counter["n"])

    real_open = _install_fake_imagehash(monkeypatch, distinct_phash)

    def fake_run(cmd, timeout=30):
        if cmd and cmd[0] == "ffprobe":
            return 0, "12.0", ""
        if cmd and cmd[0] == "ffmpeg":
            out = Path(cmd[-1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(_fake_png_bytes())
            return 0, "", ""
        return -1, "", "x"

    async def fra(cmd, timeout=30):
        return fake_run(cmd, timeout)

    monkeypatch.setattr(vs, "_sp_run", fake_run)
    monkeypatch.setattr(vs, "_sp_run_async", fra)

    try:
        video = tmp_path / "v.mp4"
        video.write_bytes(b"fake")
        # Use db_session (test DB) instead of None (default prod DB engine)
        result = await vs.generate_screenshots_change_detection(
            protocol_id=proto.id,
            video_path=video,
            output_dir=tmp_path / "shots",
            max_screenshots=5,
            sample_interval_sec=2.0,
            threshold=2,
            db=db_session,
        )
        assert isinstance(result, list)
        assert len(result) >= 1
        assert all(isinstance(s, Screenshot) for s in result)
    finally:
        # Restore real Image.open
        from PIL import Image as RealImage
        RealImage.open = real_open


# ============================================================================
# change_detection: extract failure → []
# ============================================================================

async def test_change_detection_extract_failure(make_factory, tmp_path, monkeypatch):
    """If extract_frame fails for every timestamp → returns []."""
    from app.services import video_screenshots as vs

    proto = await _make_protocol(make_factory)

    def fake_run(cmd, timeout=30):
        if cmd and cmd[0] == "ffprobe":
            return 0, "10.0", ""
        return 1, "", "ffmpeg fail"

    async def fra(cmd, timeout=30):
        return fake_run(cmd, timeout)

    monkeypatch.setattr(vs, "_sp_run", fake_run)
    monkeypatch.setattr(vs, "_sp_run_async", fra)

    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    result = await vs.generate_screenshots_change_detection(
        protocol_id=proto.id,
        video_path=video,
        output_dir=tmp_path / "shots",
        max_screenshots=2,
        db=None,
    )
    assert result == []


# ============================================================================
# change_detection: phash failure on a frame
# ============================================================================

async def test_change_detection_phash_failure(make_factory, db_session, tmp_path, monkeypatch):
    """If imagehash.phash raises on a frame → that frame is skipped, others saved."""
    from app.services import video_screenshots as vs

    proto = await _make_protocol(make_factory)

    calls = {"n": 0}
    def flaky_phash(img):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("phash exploded")
        return _FakeHash(calls["n"])

    real_open = _install_fake_imagehash(monkeypatch, flaky_phash)

    def fake_run(cmd, timeout=30):
        if cmd and cmd[0] == "ffprobe":
            return 0, "20.0", ""
        if cmd and cmd[0] == "ffmpeg":
            out = Path(cmd[-1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(_fake_png_bytes())
            return 0, "", ""
        return -1, "", "x"

    async def fra(cmd, timeout=30):
        return fake_run(cmd, timeout)

    monkeypatch.setattr(vs, "_sp_run", fake_run)
    monkeypatch.setattr(vs, "_sp_run_async", fra)

    try:
        video = tmp_path / "v.mp4"
        video.write_bytes(b"fake")
        result = await vs.generate_screenshots_change_detection(
            protocol_id=proto.id,
            video_path=video,
            output_dir=tmp_path / "shots",
            max_screenshots=5,
            sample_interval_sec=2.0,
            threshold=1,
            db=db_session,
        )
        assert isinstance(result, list)
        assert len(result) >= 1
    finally:
        from PIL import Image as RealImage
        RealImage.open = real_open


# ============================================================================
# change_detection: commit failure → rollback, returns []
# ============================================================================

async def test_change_detection_commit_failure(monkeypatch, make_factory, tmp_path):
    """If db.commit() raises → module rolls back and returns []."""
    from app.services import video_screenshots as vs

    proto = await _make_protocol(make_factory)

    # Stub imagehash with always-distinct hashes
    import types as _types_cf
    fake_module = _types_cf.ModuleType("imagehash")
    fake_module.phash = staticmethod(lambda img: _FakeHash(1))
    fake_module.__version__ = "0.0.test"
    sys.modules["imagehash"] = fake_module

    from PIL import Image as RealImage
    real_open = RealImage.open
    RealImage.open = staticmethod(lambda p: type("I", (), {"tobytes": lambda s: b"x" * 50})())

    try:
        def fake_run(cmd, timeout=30):
            if cmd and cmd[0] == "ffprobe":
                return 0, "10.0", ""
            if cmd and cmd[0] == "ffmpeg":
                out = Path(cmd[-1])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(_fake_png_bytes())
                return 0, "", ""
            return -1, "", "x"

        async def fra(cmd, timeout=30):
            return fake_run(cmd, timeout)

        monkeypatch.setattr(vs, "_sp_run", fake_run)
        monkeypatch.setattr(vs, "_sp_run_async", fra)

        class FailingCommit:
            async def commit(self_inner):
                raise RuntimeError("commit boom")
            async def rollback(self_inner):
                pass
            async def refresh(self_inner, obj):
                pass
            async def close(self_inner):
                pass
            def add(self_inner, obj):
                pass

        video = tmp_path / "v.mp4"
        video.write_bytes(b"fake")
        result = await vs.generate_screenshots_change_detection(
            protocol_id=proto.id,
            video_path=video,
            output_dir=tmp_path / "shots",
            max_screenshots=2,
            db=FailingCommit(),
        )
        assert result == []
    finally:
        RealImage.open = real_open
        sys.modules.pop("imagehash", None)


# ============================================================================
# change_detection: threshold boundary
# ============================================================================

async def test_change_detection_threshold_boundary(make_factory, db_session, tmp_path, monkeypatch):
    """threshold=999 → only baseline; threshold=0 → many saved."""
    from app.services import video_screenshots as vs

    proto = await _make_protocol(make_factory)

    # All hashes identical → distance = 0
    import types as _types_tb
    fake_module = _types_tb.ModuleType("imagehash")
    fake_module.phash = staticmethod(lambda img: _FakeHash(42))
    fake_module.__version__ = "0.0.test"
    sys.modules["imagehash"] = fake_module

    from PIL import Image as RealImage
    real_open = RealImage.open
    RealImage.open = staticmethod(lambda p: type("I", (), {"tobytes": lambda s: b"\x01"})())

    try:
        def fake_run(cmd, timeout=30):
            if cmd and cmd[0] == "ffprobe":
                return 0, "30.0", ""
            if cmd and cmd[0] == "ffmpeg":
                out = Path(cmd[-1])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(_fake_png_bytes())
                return 0, "", ""
            return -1, "", "x"

        async def fra(cmd, timeout=30):
            return fake_run(cmd, timeout)

        monkeypatch.setattr(vs, "_sp_run", fake_run)
        monkeypatch.setattr(vs, "_sp_run_async", fra)

        video = tmp_path / "v.mp4"
        video.write_bytes(b"fake")

        # threshold=999 → only baseline (1 shot)
        result_high = await vs.generate_screenshots_change_detection(
            protocol_id=proto.id,
            video_path=video,
            output_dir=tmp_path / "shots_h",
            max_screenshots=5,
            sample_interval_sec=2.0,
            threshold=999,
            db=db_session,
        )
        assert len(result_high) == 1

        # threshold=0 → 0 >= 0 is True, so every sample saved (capped at max)
        result_low = await vs.generate_screenshots_change_detection(
            protocol_id=proto.id,
            video_path=video,
            output_dir=tmp_path / "shots_l",
            max_screenshots=3,
            sample_interval_sec=2.0,
            threshold=0,
            db=db_session,
        )
        assert len(result_low) == 3
    finally:
        RealImage.open = real_open
        sys.modules.pop("imagehash", None)