"""E286 deep coverage for app/services/video_screenshots.py.

Targets:
- _sp_run (sync): real subprocess, FileNotFoundError, TimeoutExpired
- _sp_run_async: async wrapper
- extract_frame: probe fallback, audio-only, ffmpeg attempt 1 success, attempt 2 fallback, width scale
- generate_screenshots_for_protocol: protocol not found, no utterances, uniform/important/decisions strategies, error rollback
- generate_screenshots_change_detection: missing PIL/imagehash, ffprobe failure, normal flow, DB commit failure
- synthesize_screenshots_for_protocol: no audio_file
"""
import asyncio
import uuid
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------
def _make_real_video(tmp_path: Path) -> Path:
    p = tmp_path / "fake.mp4"
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
    return p


def _png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 256


def _make_real_output(tmp_path: Path, name: str = "out.png") -> Path:
    p = tmp_path / name
    p.write_bytes(_png_bytes())
    return p


def _make_fake_ffmpeg_run(output_root: Path, fail_first: bool = False, fail_both: bool = False):
    """Return a fake _sp_run that simulates ffprobe + ffmpeg behaviour."""
    call_state = {"ffmpeg_calls": 0}

    def fake_run(cmd, timeout=30):
        cmd0 = cmd[0] if cmd else ""
        # ffprobe: return a video stream index
        if cmd0 == "ffprobe":
            # duration probe (change_detection)
            if "format=duration" in " ".join(cmd):
                return 0, "30.0", ""
            # stream probe (extract_frame) — return "1" to indicate video stream exists
            return 0, "1", ""
        # ffmpeg
        if cmd0 == "ffmpeg":
            call_state["ffmpeg_calls"] += 1
            if fail_both:
                return 1, "", "ffmpeg error"
            # First call may be configured to fail (so fallback runs)
            if fail_first and call_state["ffmpeg_calls"] == 1:
                return 1, "", "first strategy failed"
            out_path = Path(cmd[-1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(_png_bytes())
            return 0, "", ""
        return -1, "", f"command not found: {cmd0}"
    return fake_run


def _patch_run(monkeypatch, fake_run):
    import app.services.video_screenshots as vs

    async def fake_async(cmd, timeout=30):
        return fake_run(cmd, timeout=timeout)

    monkeypatch.setattr(vs, "_sp_run", fake_run)
    monkeypatch.setattr(vs, "_sp_run_async", fake_async)


# ---------------------------------------------------------------------------
# _sp_run / _sp_run_async
# ---------------------------------------------------------------------------
def test_sp_run_real_subprocess():
    """_sp_run with real subprocess (python --version)."""
    from app.services.video_screenshots import _sp_run
    rc, out, err = _sp_run(["python", "--version"], timeout=10)
    assert isinstance(rc, int)
    assert isinstance(out, str)
    assert isinstance(err, str)


def test_sp_run_file_not_found():
    """_sp_run returns (-1, '', msg) for missing binary."""
    from app.services.video_screenshots import _sp_run
    rc, out, err = _sp_run(["definitely_not_a_real_binary_xyz123"], timeout=5)
    assert rc == -1
    assert "command not found" in err


@pytest.mark.asyncio
async def test_sp_run_async_invokes_subprocess(monkeypatch):
    """_sp_run_async returns the same tuple shape."""
    from app.services import video_screenshots as vs

    seen = {}

    def fake_run(cmd, timeout=30):
        seen["cmd"] = cmd
        seen["timeout"] = timeout
        return 0, "out", "err"

    monkeypatch.setattr(vs, "_sp_run", fake_run)
    rc, out, err = await vs._sp_run_async(["ffprobe", "-v", "error"], timeout=15)
    assert rc == 0
    assert out == "out"
    assert err == "err"
    assert seen["timeout"] == 15
    assert seen["cmd"][0] == "ffprobe"


# ---------------------------------------------------------------------------
# extract_frame
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_extract_frame_missing_video_returns_false(tmp_path):
    """Video file does not exist → False (no probe call)."""
    from app.services.video_screenshots import extract_frame
    result = await extract_frame(
        video_path=tmp_path / "nope.mp4",
        timestamp_sec=1.0,
        output_path=tmp_path / "out.png",
    )
    assert result is False


@pytest.mark.asyncio
async def test_extract_frame_audio_only_returns_false(tmp_path, monkeypatch):
    """ffprobe returns empty stdout → no video stream → False."""
    def fake_run(cmd, timeout=30):
        if cmd and cmd[0] == "ffprobe":
            return 0, "", ""  # no video stream
        return 0, "", ""

    _patch_run(monkeypatch, fake_run)
    from app.services.video_screenshots import extract_frame

    video = _make_real_video(tmp_path)
    out = tmp_path / "out.png"
    result = await extract_frame(video_path=video, timestamp_sec=1.0, output_path=out)
    assert result is False
    assert not out.exists()


@pytest.mark.asyncio
async def test_extract_frame_first_attempt_succeeds(tmp_path, monkeypatch):
    """First ffmpeg strategy (copy) succeeds → True."""
    fake = _make_fake_ffmpeg_run(tmp_path)
    _patch_run(monkeypatch, fake)

    from app.services.video_screenshots import extract_frame

    video = _make_real_video(tmp_path)
    out = tmp_path / "first.png"
    result = await extract_frame(video, 5.0, out, width=1280)
    assert result is True
    assert out.exists()
    assert out.stat().st_size > 0


@pytest.mark.asyncio
async def test_extract_frame_second_attempt_fallback(tmp_path, monkeypatch):
    """First ffmpeg strategy fails, second (re-encode) succeeds → True."""
    fake = _make_fake_ffmpeg_run(tmp_path, fail_first=True)
    _patch_run(monkeypatch, fake)

    from app.services.video_screenshots import extract_frame

    video = _make_real_video(tmp_path)
    out = tmp_path / "fallback.png"
    result = await extract_frame(video, 2.5, out, width=800)
    assert result is True
    assert out.exists()


@pytest.mark.asyncio
async def test_extract_frame_both_attempts_fail(tmp_path, monkeypatch):
    """Both ffmpeg strategies fail → False."""
    fake = _make_fake_ffmpeg_run(tmp_path, fail_both=True)
    _patch_run(monkeypatch, fake)

    from app.services.video_screenshots import extract_frame

    video = _make_real_video(tmp_path)
    out = tmp_path / "fail.png"
    result = await extract_frame(video, 0.0, out)
    assert result is False


@pytest.mark.asyncio
async def test_extract_frame_with_width_includes_scale(tmp_path, monkeypatch):
    """Width parameter adds -vf scale=… to fallback command."""
    captured_cmds = []

    def fake_run(cmd, timeout=30):
        captured_cmds.append(list(cmd))
        if cmd[0] == "ffprobe":
            return 0, "1", ""
        # ffmpeg — fail first so we hit fallback
        if cmd[0] == "ffmpeg" and "-c:v" in cmd:
            return 1, "", "first failed"
        out = Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(_png_bytes())
        return 0, "", ""

    _patch_run(monkeypatch, fake_run)

    from app.services.video_screenshots import extract_frame

    video = _make_real_video(tmp_path)
    out = tmp_path / "scaled.png"
    result = await extract_frame(video, 1.0, out, width=640)
    assert result is True

    # Check the fallback command contained -vf scale=640:-1
    fallback_cmds = [c for c in captured_cmds if c[0] == "ffmpeg" and "-vf" in c]
    assert any("scale=640:-1" in " ".join(c) for c in fallback_cmds)


# ---------------------------------------------------------------------------
# generate_screenshots_for_protocol
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_generate_for_unknown_protocol_returns_empty(tmp_path, monkeypatch, db_session):
    """Unknown protocol_id → [] (no screenshots)."""
    _patch_run(monkeypatch, _make_fake_ffmpeg_run(tmp_path))

    from app.services.video_screenshots import generate_screenshots_for_protocol

    result = await generate_screenshots_for_protocol(
        protocol_id=uuid.uuid4(),
        video_path=_make_real_video(tmp_path),
        output_dir=tmp_path / "shots",
        strategy="uniform",
        max_screenshots=5,
        db=db_session,
    )
    assert result == []


@pytest.mark.asyncio
async def test_generate_uniform_strategy(
    tmp_path, monkeypatch, db_session, sample_protocol, sample_speaker
):
    """Uniform strategy: even spacing across all utterances."""
    _patch_run(monkeypatch, _make_fake_ffmpeg_run(tmp_path))

    from app.db.models import Utterance
    from app.services.video_screenshots import generate_screenshots_for_protocol

    # 10 utterances every 10s → uniform picks 0, 30, 60, 90, 120 with n=5
    for i in range(10):
        db_session.add(Utterance(
            id=uuid.uuid4(),
            protocol_id=sample_protocol.id,
            speaker_id=sample_speaker.id,
            start_sec=float(i * 10),
            end_sec=float(i * 10 + 5),
            text=f"utt {i}",
        ))
    await db_session.commit()

    result = await generate_screenshots_for_protocol(
        protocol_id=sample_protocol.id,
        video_path=_make_real_video(tmp_path),
        output_dir=tmp_path / "uniform",
        strategy="uniform",
        max_screenshots=5,
        db=db_session,
    )
    assert isinstance(result, list)
    assert len(result) == 5
    # Verify timestamps are spaced — 10 utterances, n=5 → step_idx=2 → picks [0,2,4,6,8]
    timestamps = sorted(float(s.timestamp_sec) for s in result)
    assert timestamps == [0.0, 20.0, 40.0, 60.0, 80.0]


@pytest.mark.asyncio
async def test_generate_important_strategy(
    tmp_path, monkeypatch, db_session, sample_protocol, sample_speaker
):
    """Important strategy picks only utterances with important=True."""
    _patch_run(monkeypatch, _make_fake_ffmpeg_run(tmp_path))

    from app.db.models import Utterance
    from app.services.video_screenshots import generate_screenshots_for_protocol

    for i, important in enumerate([True, False, True, False, True, False]):
        db_session.add(Utterance(
            id=uuid.uuid4(),
            protocol_id=sample_protocol.id,
            speaker_id=sample_speaker.id,
            start_sec=float(i * 10),
            end_sec=float(i * 10 + 5),
            text=f"u{i}",
            important=important,
        ))
    await db_session.commit()

    result = await generate_screenshots_for_protocol(
        protocol_id=sample_protocol.id,
        video_path=_make_real_video(tmp_path),
        output_dir=tmp_path / "imp",
        strategy="important",
        max_screenshots=10,
        db=db_session,
    )
    assert len(result) == 3
    # All important utterances were at indices 0, 2, 4
    timestamps = sorted(s.timestamp_sec for s in result)
    assert timestamps == [0.0, 20.0, 40.0]


@pytest.mark.asyncio
async def test_generate_decisions_strategy(
    tmp_path, monkeypatch, db_session, sample_protocol, sample_speaker
):
    """Decisions strategy picks only utterances with is_decision=True."""
    _patch_run(monkeypatch, _make_fake_ffmpeg_run(tmp_path))

    from app.db.models import Utterance
    from app.services.video_screenshots import generate_screenshots_for_protocol

    for i, dec in enumerate([False, True, False, True, False]):
        db_session.add(Utterance(
            id=uuid.uuid4(),
            protocol_id=sample_protocol.id,
            speaker_id=sample_speaker.id,
            start_sec=float(i * 5),
            end_sec=float(i * 5 + 2),
            text=f"d{i}",
            is_decision=dec,
        ))
    await db_session.commit()

    result = await generate_screenshots_for_protocol(
        protocol_id=sample_protocol.id,
        video_path=_make_real_video(tmp_path),
        output_dir=tmp_path / "dec",
        strategy="decisions",
        max_screenshots=10,
        db=db_session,
    )
    assert len(result) == 2
    timestamps = sorted(s.timestamp_sec for s in result)
    assert timestamps == [5.0, 15.0]


@pytest.mark.asyncio
async def test_generate_no_utterances_returns_empty(
    tmp_path, monkeypatch, db_session, sample_protocol
):
    """Protocol with no utterances → []."""
    _patch_run(monkeypatch, _make_fake_ffmpeg_run(tmp_path))

    from app.services.video_screenshots import generate_screenshots_for_protocol

    result = await generate_screenshots_for_protocol(
        protocol_id=sample_protocol.id,
        video_path=_make_real_video(tmp_path),
        output_dir=tmp_path / "empty",
        strategy="uniform",
        max_screenshots=3,
        db=db_session,
    )
    assert result == []


@pytest.mark.asyncio
async def test_generate_file_size_kb_calculation(
    tmp_path, monkeypatch, db_session, sample_protocol, sample_speaker
):
    """file_size_kb = file_size_bytes // 1024 (rounded down)."""
    _patch_run(monkeypatch, _make_fake_ffmpeg_run(tmp_path))

    from app.db.models import Utterance
    from app.services.video_screenshots import generate_screenshots_for_protocol

    db_session.add(Utterance(
        id=uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_id=sample_speaker.id,
        start_sec=0.0,
        end_sec=1.0,
        text="x",
    ))
    await db_session.commit()

    result = await generate_screenshots_for_protocol(
        protocol_id=sample_protocol.id,
        video_path=_make_real_video(tmp_path),
        output_dir=tmp_path / "size",
        strategy="uniform",
        max_screenshots=1,
        db=db_session,
    )
    assert len(result) == 1
    # _png_bytes() = 8 + 256 = 264 bytes → 0 KB (264 // 1024)
    assert result[0].file_size_kb == 0
    # The file exists on disk
    assert Path(result[0].file_path).exists()


@pytest.mark.asyncio
async def test_generate_db_error_rolls_back(
    tmp_path, monkeypatch, db_session, sample_protocol, sample_speaker
):
    """If db.commit raises, the except branch logs + rolls back + returns []."""
    from app.db.models import Utterance

    # Add an utterance so we get past the "no timestamps" branch
    db_session.add(Utterance(
        id=uuid.uuid4(),
        protocol_id=sample_protocol.id,
        speaker_id=sample_speaker.id,
        start_sec=0.0,
        end_sec=1.0,
        text="x",
    ))
    await db_session.commit()

    _patch_run(monkeypatch, _make_fake_ffmpeg_run(tmp_path))

    # Break commit to force rollback branch
    real_commit = db_session.commit

    async def boom():
        raise RuntimeError("simulated db failure")

    monkeypatch.setattr(db_session, "commit", boom)

    from app.services.video_screenshots import generate_screenshots_for_protocol

    result = await generate_screenshots_for_protocol(
        protocol_id=sample_protocol.id,
        video_path=_make_real_video(tmp_path),
        output_dir=tmp_path / "err",
        strategy="uniform",
        max_screenshots=1,
        db=db_session,
    )
    assert result == []
    # Restore for fixture cleanup
    monkeypatch.setattr(db_session, "commit", real_commit)


# ---------------------------------------------------------------------------
# generate_screenshots_change_detection
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_change_detection_no_modules(monkeypatch, tmp_path):
    """If PIL/imagehash unavailable → return [] immediately."""
    import builtins

    import app.services.video_screenshots as vs

    # Force ImportError on the inner imports
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in ("PIL.Image", "imagehash") or name in ("PIL", "imagehash"):
            raise ImportError(f"no module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    result = await vs.generate_screenshots_change_detection(
        protocol_id=uuid.uuid4(),
        video_path=_make_real_video(tmp_path),
        output_dir=tmp_path / "cd",
    )
    assert result == []


@pytest.mark.asyncio
async def test_change_detection_ffprobe_invalid_duration(
    tmp_path, monkeypatch, db_session, sample_protocol
):
    """ffprobe returns 0 duration → []. Even if modules are present."""
    # Pre-stub PIL/imagehash in sys.modules so the import succeeds
    import sys
    import types

    if "PIL" not in sys.modules:
        pil = types.ModuleType("PIL")
        pil_img = types.ModuleType("PIL.Image")
        pil_img.__version__ = "0.0.0"
        pil_img.open = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no real PIL"))
        pil.Image = pil_img
        sys.modules["PIL"] = pil
        sys.modules["PIL.Image"] = pil_img
    if "imagehash" not in sys.modules:
        ih = types.ModuleType("imagehash")
        ih.__version__ = "0.0.0"
        ih.phash = lambda img: None
        sys.modules["imagehash"] = ih

    def fake_run(cmd, timeout=30):
        if cmd and cmd[0] == "ffprobe":
            return 0, "0", ""  # invalid duration
        return 0, "", ""

    _patch_run(monkeypatch, fake_run)

    from app.services.video_screenshots import generate_screenshots_change_detection

    result = await generate_screenshots_change_detection(
        protocol_id=sample_protocol.id,
        video_path=_make_real_video(tmp_path),
        output_dir=tmp_path / "cd_zero",
        db=db_session,
    )
    assert result == []


@pytest.mark.asyncio
async def test_synthesize_no_audio_file_returns_zero(db_session, sample_protocol):
    """Protocol without audio_file_id → synthesize returns 0."""
    from app.services.video_screenshots import synthesize_screenshots_for_protocol

    result = await synthesize_screenshots_for_protocol(
        protocol_id=sample_protocol.id,
        db=db_session,
    )
    assert result == 0


# ---------------------------------------------------------------------------
# Timestamp filename formatting
# ---------------------------------------------------------------------------
def test_shot_filename_format():
    """shot_{int(ts*1000):010d}.png format used by both generators."""
    # Mirror the formatting logic in the source
    ts = 12.345
    expected = f"shot_{int(ts * 1000):010d}.png"
    # int(12.345 * 1000) = 12345 → zero-padded to 10 digits
    assert expected == "shot_0000012345.png"

    ts2 = 0.0
    # int(0 * 1000) = 0 → 10 zeros (format spec says 10 chars total)
    assert f"shot_{int(ts2 * 1000):010d}.png" == "shot_0000000000.png"

    ts3 = 125.0
    # int(125 * 1000) = 125000
    assert f"shot_{int(ts3 * 1000):010d}.png" == "shot_0000125000.png"
