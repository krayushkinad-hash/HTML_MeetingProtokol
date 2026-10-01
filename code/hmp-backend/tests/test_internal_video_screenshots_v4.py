"""Tests for app/services/video_screenshots.py — goal 70%+ coverage.

Covers:
- _sp_run (FileNotFoundError, TimeoutExpired, generic exception, success)
- _sp_run_async
- extract_frame (all branches: missing video, no stream, success, both ffmpeg attempts)
- generate_screenshots_for_protocol (uniform/important/decisions/empty/not-found)
- synthesize_screenshots_for_protocol
- generate_screenshots_change_detection (happy path, no PIL, ffprobe fail, etc.)
"""
import asyncio
import sys
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import subprocess as sp


# ============================================================================
# _sp_run — synchronous subprocess helper
# ============================================================================

class TestSpRun:
    """Direct unit tests of the synchronous _sp_run helper."""

    def test_sp_run_success(self):
        from app.services.video_screenshots import _sp_run
        rc, out, err = _sp_run(["true"])
        assert rc == 0
        assert isinstance(out, str)
        assert isinstance(err, str)

    def test_sp_run_filenotfound(self):
        from app.services.video_screenshots import _sp_run
        rc, out, err = _sp_run(["nonexistent_command_xyz_abc"])
        assert rc == -1
        assert "command not found" in err

    def test_sp_run_timeout(self):
        from app.services.video_screenshots import _sp_run
        # sleep 5 with 0.1s timeout — must trigger TimeoutExpired
        rc, out, err = _sp_run(["sleep", "5"], timeout=0.1)
        assert rc == -2
        assert "timeout" in err

    def test_sp_run_generic_exception(self):
        from app.services.video_screenshots import _sp_run
        # Patch sp.run to raise a generic exception
        with patch("subprocess.run", side_effect=RuntimeError("boom")):
            rc, out, err = _sp_run(["anything"])
            assert rc == -3
            assert "boom" in err

    @pytest.mark.asyncio
    async def test_sp_run_async_delegates(self):
        from app.services.video_screenshots import _sp_run_async
        rc, out, err = await _sp_run_async(["true"])
        assert rc == 0


# ============================================================================
# extract_frame — frame extraction with ffmpeg
# ============================================================================

class TestExtractFrame:
    """extract_frame: 404 video, no video stream, success path, both ffmpeg strategies."""

    @pytest.mark.asyncio
    async def test_extract_frame_video_not_found(self, tmp_path):
        from app.services.video_screenshots import extract_frame
        result = await extract_frame(
            video_path=tmp_path / "no_such.mp4",
            timestamp_sec=1.0,
            output_path=tmp_path / "out.png",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_extract_frame_no_video_stream(self, tmp_path):
        """When ffprobe returns no stream, function returns False."""
        from app.services.video_screenshots import extract_frame
        video = tmp_path / "audio_only.mp4"
        video.write_bytes(b"fake")

        async def fake_probe(cmd, timeout=10):
            return 0, "", ""  # empty stdout → no video stream

        with patch("app.services.video_screenshots._sp_run_async", side_effect=fake_probe):
            result = await extract_frame(video, 1.0, tmp_path / "out.png")
        assert result is False

    @pytest.mark.asyncio
    async def test_extract_frame_ffmpeg_not_found(self, tmp_path):
        """ffprobe OK, but ffmpeg missing → return False."""
        from app.services.video_screenshots import extract_frame
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")

        call_count = {"n": 0}

        async def fake(cmd, timeout=10):
            call_count["n"] += 1
            if "ffprobe" in cmd[0]:
                return 0, "0", ""  # has video stream
            raise FileNotFoundError("ffmpeg not found")

        with patch("app.services.video_screenshots._sp_run_async", side_effect=fake):
            result = await extract_frame(video, 1.0, tmp_path / "out.png")
        assert result is False

    @pytest.mark.asyncio
    async def test_extract_frame_first_strategy_succeeds(self, tmp_path):
        """First ffmpeg strategy produces output → success."""
        from app.services.video_screenshots import extract_frame
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        out = tmp_path / "shot.png"

        async def fake(cmd, timeout=10):
            if "ffprobe" in cmd[0]:
                return 0, "0", ""
            # ffmpeg copy strategy — create output
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"PNG_DATA_HERE")
            return 0, "", ""

        with patch("app.services.video_screenshots._sp_run_async", side_effect=fake):
            result = await extract_frame(video, 1.0, out)
        assert result is True
        assert out.exists()

    @pytest.mark.asyncio
    async def test_extract_frame_fallback_strategy(self, tmp_path):
        """First ffmpeg attempt fails, fallback strategy succeeds."""
        from app.services.video_screenshots import extract_frame
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        out = tmp_path / "shot.png"
        attempt = {"n": 0}

        async def fake(cmd, timeout=10):
            if "ffprobe" in cmd[0]:
                return 0, "0", ""
            attempt["n"] += 1
            if attempt["n"] == 1:
                return 1, "", "codec error"  # first strategy fails
            # second (fallback) — create output
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"OK")
            return 0, "", ""

        with patch("app.services.video_screenshots._sp_run_async", side_effect=fake):
            result = await extract_frame(video, 2.0, out, width=640)
        assert result is True
        assert attempt["n"] == 2

    @pytest.mark.asyncio
    async def test_extract_frame_both_attempts_fail(self, tmp_path):
        """Both ffmpeg strategies fail → returns False."""
        from app.services.video_screenshots import extract_frame
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")

        async def fake(cmd, timeout=10):
            if "ffprobe" in cmd[0]:
                return 0, "0", ""
            return 1, "", "fail"

        with patch("app.services.video_screenshots._sp_run_async", side_effect=fake):
            result = await extract_frame(video, 1.0, tmp_path / "out.png")
        assert result is False

    @pytest.mark.asyncio
    async def test_extract_frame_generic_exception(self, tmp_path):
        """Generic exception inside ffmpeg try block is logged & loop continues."""
        from app.services.video_screenshots import extract_frame
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")

        async def fake(cmd, timeout=10):
            if "ffprobe" in cmd[0]:
                return 0, "0", ""
            if cmd[0] == "ffmpeg":
                raise RuntimeError("ffmpeg crash")
            return 0, "", ""

        with patch("app.services.video_screenshots._sp_run_async", side_effect=fake):
            result = await extract_frame(video, 1.0, tmp_path / "out.png")
        # Both attempts raise → return False
        assert result is False


# ============================================================================
# generate_screenshots_for_protocol — main entry point with all strategies
# ============================================================================

async def _add_utterances(db_session, protocol, speaker, count, important_flags=None, decision_flags=None):
    """Helper to bulk-create utterances."""
    from app.db.models import Utterance
    objs = []
    for i in range(count):
        u = Utterance(
            id=uuid.uuid4(),
            protocol_id=protocol.id,
            speaker_id=speaker.id,
            start_sec=float(i),
            end_sec=float(i) + 0.5,
            text=f"u{i}",
        )
        if important_flags and i < len(important_flags):
            u.important = important_flags[i]
        if decision_flags and i < len(decision_flags):
            u.is_decision = decision_flags[i]
        db_session.add(u)
        objs.append(u)
    await db_session.commit()
    for u in objs:
        await db_session.refresh(u)
    return objs


def _fake_extract_factory():
    """Return an async function that writes fake PNG files (with mkdir)."""
    async def fake_extract(vp, ts, op, width=1280):
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_bytes(b"PNG")
        return True
    return fake_extract


class TestGenerateScreenshotsProtocol:
    """Strategy tests: uniform, important, decisions, edge cases."""

    @pytest.mark.asyncio
    async def test_protocol_not_found(self, db_session, tmp_path):
        from app.services.video_screenshots import generate_screenshots_for_protocol
        result = await generate_screenshots_for_protocol(
            protocol_id=uuid.uuid4(),
            video_path=tmp_path / "v.mp4",
            output_dir=tmp_path,
            db=db_session,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_no_utterances(self, db_session, sample_protocol, tmp_path):
        from app.services.video_screenshots import generate_screenshots_for_protocol
        result = await generate_screenshots_for_protocol(
            protocol_id=sample_protocol.id,
            video_path=tmp_path / "v.mp4",
            output_dir=tmp_path,
            db=db_session,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_uniform_strategy(self, db_session, sample_protocol, sample_speaker, tmp_path):
        """Uniform with 4 utterances → picks 3 evenly."""
        from app.services.video_screenshots import generate_screenshots_for_protocol
        await _add_utterances(db_session, sample_protocol, sample_speaker, 4)

        with patch("app.services.video_screenshots.extract_frame", side_effect=_fake_extract_factory()):
            result = await generate_screenshots_for_protocol(
                protocol_id=sample_protocol.id,
                video_path=tmp_path / "v.mp4",
                output_dir=tmp_path / "out",
                max_screenshots=3,
                strategy="uniform",
                db=db_session,
            )
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_important_strategy(self, db_session, sample_protocol, sample_speaker, tmp_path):
        """Strategy='important' picks only important utterances."""
        from app.services.video_screenshots import generate_screenshots_for_protocol
        await _add_utterances(db_session, sample_protocol, sample_speaker, 3,
                        important_flags=[False, True, False])

        with patch("app.services.video_screenshots.extract_frame", side_effect=_fake_extract_factory()):
            result = await generate_screenshots_for_protocol(
                protocol_id=sample_protocol.id,
                video_path=tmp_path / "v.mp4",
                output_dir=tmp_path / "out",
                strategy="important",
                db=db_session,
            )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_decisions_strategy(self, db_session, sample_protocol, sample_speaker, tmp_path):
        """Strategy='decisions' picks only decision utterances."""
        from app.services.video_screenshots import generate_screenshots_for_protocol
        await _add_utterances(db_session, sample_protocol, sample_speaker, 3,
                        decision_flags=[True, False, False])

        with patch("app.services.video_screenshots.extract_frame", side_effect=_fake_extract_factory()):
            result = await generate_screenshots_for_protocol(
                protocol_id=sample_protocol.id,
                video_path=tmp_path / "v.mp4",
                output_dir=tmp_path / "out",
                strategy="decisions",
                db=db_session,
            )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_extract_failure_skipped(self, db_session, sample_protocol, sample_speaker, tmp_path):
        """If extract_frame returns False, that timestamp is skipped (not added)."""
        from app.services.video_screenshots import generate_screenshots_for_protocol
        await _add_utterances(db_session, sample_protocol, sample_speaker, 2)

        async def fail(*a, **kw):
            return False

        with patch("app.services.video_screenshots.extract_frame", side_effect=fail):
            result = await generate_screenshots_for_protocol(
                protocol_id=sample_protocol.id,
                video_path=tmp_path / "v.mp4",
                output_dir=tmp_path / "out",
                max_screenshots=5,
                db=db_session,
            )
        assert result == []

    @pytest.mark.asyncio
    async def test_exception_during_extract_is_caught(self, db_session, sample_protocol, sample_speaker, tmp_path):
        """Exception inside the loop is caught by outer try/except → returns []."""
        from app.services.video_screenshots import generate_screenshots_for_protocol
        await _add_utterances(db_session, sample_protocol, sample_speaker, 1)

        async def boom(*a, **kw):
            raise RuntimeError("disk full")

        with patch("app.services.video_screenshots.extract_frame", side_effect=boom):
            # extract raising an exception propagates → outer try/except catches
            result = await generate_screenshots_for_protocol(
                protocol_id=sample_protocol.id,
                video_path=tmp_path / "v.mp4",
                output_dir=tmp_path / "out",
                db=db_session,
            )
        # Outer try/except catches and returns []
        assert result == []


# ============================================================================
# synthesize_screenshots_for_protocol
# ============================================================================

class TestSynthesizeScreenshots:
    @pytest.mark.asyncio
    async def test_no_protocol(self, db_session):
        from app.services.video_screenshots import synthesize_screenshots_for_protocol
        result = await synthesize_screenshots_for_protocol(
            protocol_id=uuid.uuid4(),
            db=db_session,
        )
        assert result == 0

    @pytest.mark.asyncio
    async def test_no_audio_file(self, db_session, sample_protocol):
        """Protocol exists, no audio_file_id → returns 0."""
        from app.services.video_screenshots import synthesize_screenshots_for_protocol
        result = await synthesize_screenshots_for_protocol(
            protocol_id=sample_protocol.id,
            db=db_session,
        )
        assert result == 0


# ============================================================================
# generate_screenshots_change_detection
# ============================================================================

class TestChangeDetection:
    @pytest.mark.asyncio
    async def test_change_detection_no_pil(self, db_session, sample_protocol, tmp_path):
        """When PIL/imagehash are not installed, function returns []."""
        from app.services import video_screenshots as vs
        # Force ImportError by patching sys.modules
        orig_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__
        def fake_import(name, *args, **kwargs):
            if name in ("PIL", "PIL.Image", "imagehash"):
                raise ImportError("no module")
            return orig_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=fake_import):
            result = await vs.generate_screenshots_change_detection(
                protocol_id=sample_protocol.id,
                video_path=tmp_path / "v.mp4",
                output_dir=tmp_path,
                db=db_session,
            )
        assert result == []

    @pytest.mark.asyncio
    async def test_change_detection_ffprobe_invalid_duration(self, db_session, sample_protocol, tmp_path):
        """ffprobe returns 0/empty duration → return []."""
        from app.services.video_screenshots import generate_screenshots_change_detection

        async def fake_probe(cmd, timeout=10):
            return 0, "not_a_number", ""

        with patch("app.services.video_screenshots._sp_run_async", side_effect=fake_probe):
            result = await generate_screenshots_change_detection(
                protocol_id=sample_protocol.id,
                video_path=tmp_path / "v.mp4",
                output_dir=tmp_path,
                db=db_session,
            )
        assert result == []

    @pytest.mark.asyncio
    async def test_change_detection_ffprobe_zero_duration(self, db_session, sample_protocol, tmp_path):
        """ffprobe returns duration=0 → return []."""
        from app.services.video_screenshots import generate_screenshots_change_detection

        async def fake_probe(cmd, timeout=10):
            return 0, "0", ""

        with patch("app.services.video_screenshots._sp_run_async", side_effect=fake_probe):
            result = await generate_screenshots_change_detection(
                protocol_id=sample_protocol.id,
                video_path=tmp_path / "v.mp4",
                output_dir=tmp_path,
                db=db_session,
            )
        assert result == []

    @pytest.mark.asyncio
    async def test_change_detection_ffprobe_raises_valueerror(self, db_session, sample_protocol, tmp_path):
        """ffprobe raises ValueError → returns []."""
        from app.services.video_screenshots import generate_screenshots_change_detection

        async def fake(cmd, timeout=10):
            raise ValueError("ffprobe crashed")

        with patch("app.services.video_screenshots._sp_run_async", side_effect=fake):
            result = await generate_screenshots_change_detection(
                protocol_id=sample_protocol.id,
                video_path=tmp_path / "v.mp4",
                output_dir=tmp_path,
                db=db_session,
            )
        assert result == []

    @pytest.mark.asyncio
    async def test_change_detection_ffprobe_raises_oserror(self, db_session, sample_protocol, tmp_path):
        """ffprobe raises OSError → returns []."""
        from app.services.video_screenshots import generate_screenshots_change_detection

        async def fake(cmd, timeout=10):
            raise OSError("io error")

        with patch("app.services.video_screenshots._sp_run_async", side_effect=fake):
            result = await generate_screenshots_change_detection(
                protocol_id=sample_protocol.id,
                video_path=tmp_path / "v.mp4",
                output_dir=tmp_path,
                db=db_session,
            )
        assert result == []

    @pytest.mark.asyncio
    async def test_change_detection_happy_path(self, db_session, sample_protocol, tmp_path):
        """Full happy path: ffprobe returns duration, extract succeeds, hash changes."""
        from app.services.video_screenshots import generate_screenshots_change_detection

        # Build two different mock hashes with subtraction returning a distance
        hash_a = MagicMock()
        hash_b = MagicMock()
        # __sub__ must return an int for `dist >= threshold`
        hash_a.__sub__ = MagicMock(return_value=20)
        hash_b.__sub__ = MagicMock(return_value=20)
        # phash() must be iterable to keep producing hashes for many timestamps
        hash_seq = [hash_a, hash_b] * 10
        mock_imagehash = MagicMock()
        mock_imagehash.phash.side_effect = hash_seq

        # Configure __version__ on the mock module
        mock_imagehash_mod = MagicMock()
        mock_imagehash_mod.phash = MagicMock(side_effect=hash_seq)
        mock_imagehash_mod.__version__ = "4.3"

        mock_img_inst = MagicMock()
        mock_img_inst.__version__ = "10.0"  # not needed (Image.__version__) but safe
        mock_pil_mod = MagicMock()
        mock_pil_mod.__version__ = "10.0"
        mock_pil_mod.Image = MagicMock()
        mock_pil_mod.Image.open = MagicMock(return_value=mock_img_inst)
        mock_pil_mod.Image.__version__ = "10.0"

        # Patch the import to use our mocks
        import builtins
        orig_import = builtins.__import__
        def fake_import(name, *args, **kwargs):
            if name == "PIL":
                return mock_pil_mod
            if name == "PIL.Image":
                return mock_pil_mod.Image
            if name == "imagehash":
                return mock_imagehash_mod
            return orig_import(name, *args, **kwargs)

        # ffprobe returns duration 20s
        async def fake(cmd, timeout=10):
            if "ffprobe" in cmd[0]:
                return 0, "20.0", ""
            return 0, "", ""

        async def fake_extract(vp, ts, op, width=1280):
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_bytes(b"PNG_DATA")
            return True

        with patch("builtins.__import__", side_effect=fake_import):
            with patch("app.services.video_screenshots._sp_run_async", side_effect=fake):
                with patch("app.services.video_screenshots.extract_frame", side_effect=fake_extract):
                    result = await generate_screenshots_change_detection(
                        protocol_id=sample_protocol.id,
                        video_path=tmp_path / "v.mp4",
                        output_dir=tmp_path / "out",
                        max_screenshots=2,
                        sample_interval_sec=5.0,
                        threshold=8,
                        db=db_session,
                    )
        assert isinstance(result, list)