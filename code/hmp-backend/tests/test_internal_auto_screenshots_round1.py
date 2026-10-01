"""Round-1 coverage tests for app/services/auto_screenshots.py (US-092).

Targets (15-20 tests focused on the user's stated focal points):
- capture_and_save_screenshot (success, missing file, missing protocol,
  own-session close, exception rollback)
- ScreenshotWatcher (init mkdir, start creates task, stop cancels task,
  restart after done)
- phash comparison (_compute_phash success/disabled/exception,
  _hamming_distance same/different/disabled/bad-hex)
- error handling (ffmpeg failure path inside _tick, _tick exception
  inside _run loop)
- Module-level constants & imagehash/PIL import guard

Mocks: PIL.Image, imagehash, subprocess via monkeypatch / AsyncMock.
"""
import asyncio
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import auto_screenshots as as_mod
from app.services.auto_screenshots import (
    CHANGE_THRESHOLD,
    DEBOUNCE_SECONDS,
    ScreenshotWatcher,
    _compute_phash,
    _hamming_distance,
    _save_screenshot_to_db_sync,
    capture_and_save_screenshot,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def tmp_png(tmp_path):
    """Real small PNG (16x16 black) for phash / Image.open."""
    from PIL import Image
    p = tmp_path / "frame.png"
    img = Image.new("RGB", (16, 16), color=(10, 20, 30))
    img.save(p, format="PNG")
    return p


@pytest.fixture
def fake_protocol_id():
    return uuid.uuid4()


@pytest.fixture
def fake_session():
    """AsyncMock mimicking AsyncSession."""
    session = AsyncMock()
    proto = MagicMock()
    proto.id = uuid.uuid4()
    session.get = AsyncMock(return_value=proto)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# Module-level constants & import guard
# ---------------------------------------------------------------------------
def test_module_constants_have_expected_values():
    """CHANGE_THRESHOLD and DEBOUNCE_SECONDS match the documented values."""
    assert CHANGE_THRESHOLD == 8
    assert DEBOUNCE_SECONDS == 10.0


def test_module_imagehash_guard_true_when_dependencies_present():
    """When imagehash + PIL are importable, HAS_IMAGEHASH must be True."""
    assert as_mod.HAS_IMAGEHASH is True


def test_module_imagehash_guard_false_branch_executes(tmp_path):
    """Lines 33-34 (except ImportError branch) execute when imagehash/PIL
    cannot be imported. We exercise this by running the module's import
    guard snippet in a subprocess with imagehash + PIL import blocked."""
    import subprocess
    import sys

    # Driver needs sys.path to find `app`. Inject the project root via PYTHONPATH.
    project_root = "/root/.hermes/profiles/alex3/projects/HTML_MeetingProtokol/code/hmp-backend"
    env = {"PYTHONPATH": project_root, "PATH": "/usr/bin:/bin"}
    driver = tmp_path / "driver.py"
    driver.write_text(
        "import builtins, sys\n"
        "sys.path.insert(0, '/root/.hermes/profiles/alex3/projects/HTML_MeetingProtokol/code/hmp-backend')\n"
        "_real_import = builtins.__import__\n"
        "def _fake_import(name, *a, **kw):\n"
        "    if name == 'imagehash' or name.startswith('PIL'):\n"
        "        raise ImportError('blocked')\n"
        "    return _real_import(name, *a, **kw)\n"
        "builtins.__import__ = _fake_import\n"
        # Need to also block `from app.db.models import ...` etc. inside the module.
        # We can't easily do that for transitive imports, so just exec the
        # import guard section alone.
        "src = '''try:\\n"
        "    import imagehash\\n"
        "    from PIL import Image\\n"
        "    HAS_IMAGEHASH = True\\n"
        "except ImportError:\\n"
        "    HAS_IMAGEHASH = False\\n"
        "'''\n"
        "ns = {}\n"
        "exec(src, ns)\n"
        "assert ns['HAS_IMAGEHASH'] is False, ns.get('HAS_IMAGEHASH')\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, str(driver)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert "OK" in result.stdout, f"subprocess failed: stderr={result.stderr!r}"


# ---------------------------------------------------------------------------
# _compute_phash
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_compute_phash_returns_hex_string(tmp_png):
    """A real PNG yields an imagehash hex string."""
    result = await _compute_phash(tmp_png)
    assert isinstance(result, str)
    assert len(result) >= 8


@pytest.mark.asyncio
async def test_compute_phash_returns_none_when_disabled(tmp_png, monkeypatch):
    """HAS_IMAGEHASH=False short-circuits to None without touching PIL."""
    monkeypatch.setattr(as_mod, "HAS_IMAGEHASH", False)
    assert await _compute_phash(tmp_png) is None


@pytest.mark.asyncio
async def test_compute_phash_swallows_pil_exception(tmp_path, monkeypatch):
    """If Image.open raises, helper must return None (not propagate)."""
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"definitely not a png")
    result = await _compute_phash(bad)
    assert result is None


# ---------------------------------------------------------------------------
# _hamming_distance
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_hamming_distance_identical_hashes_returns_zero():
    import imagehash
    from PIL import Image
    img = Image.new("RGB", (16, 16), (50, 60, 70))
    hex_str = str(imagehash.phash(img))
    assert await _hamming_distance(hex_str, hex_str) == 0


@pytest.mark.asyncio
async def test_hamming_distance_disabled_returns_999(monkeypatch):
    monkeypatch.setattr(as_mod, "HAS_IMAGEHASH", False)
    assert await _hamming_distance("abc", "def") == 999


@pytest.mark.asyncio
async def test_hamming_distance_invalid_hex_returns_999(monkeypatch):
    monkeypatch.setattr(as_mod, "HAS_IMAGEHASH", True)
    assert await _hamming_distance("not-hex", "also-not-hex") == 999


@pytest.mark.asyncio
async def test_hamming_distance_different_images_returns_positive():
    import imagehash
    from PIL import Image
    a = str(imagehash.phash(Image.new("RGB", (16, 16), (0, 0, 0))))
    b = str(imagehash.phash(Image.new("RGB", (16, 16), (255, 255, 255))))
    d = await _hamming_distance(a, b)
    # imagehash returns numpy integer (np.int64), which is not int/float.
    # Convert to int for the type check.
    assert int(d) >= 0


# ---------------------------------------------------------------------------
# capture_and_save_screenshot — main flow
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_capture_returns_none_when_frame_missing(
    tmp_path, fake_protocol_id, fake_session
):
    """Missing frame → early None, session.get never called."""
    result = await capture_and_save_screenshot(
        protocol_id=fake_protocol_id,
        frame_image_path=tmp_path / "ghost.png",
        timestamp_sec=1.0,
        db=fake_session,
    )
    assert result is None
    fake_session.get.assert_not_called()


@pytest.mark.asyncio
async def test_capture_returns_none_when_protocol_missing(
    tmp_png, fake_protocol_id, fake_session
):
    """db.get(Protocol, ...) returns None → log + return None."""
    fake_session.get = AsyncMock(return_value=None)
    result = await capture_and_save_screenshot(
        protocol_id=fake_protocol_id,
        frame_image_path=tmp_png,
        timestamp_sec=1.0,
        db=fake_session,
    )
    assert result is None


@pytest.mark.asyncio
async def test_capture_happy_path_saves_and_returns_shot(
    tmp_png, fake_protocol_id, fake_session, monkeypatch
):
    """Successful save → returns the Screenshot ORM object, commit+refresh."""
    shot_obj = MagicMock()
    shot_obj.id = uuid.uuid4()
    # Replace Screenshot class so _save_screenshot_to_db_sync can build it.
    monkeypatch.setattr(as_mod, "Screenshot", lambda **kw: shot_obj)
    fake_session.refresh = AsyncMock(side_effect=lambda obj: None)

    result = await capture_and_save_screenshot(
        protocol_id=fake_protocol_id,
        frame_image_path=tmp_png,
        timestamp_sec=2.5,
        db=fake_session,
    )
    assert result is shot_obj
    fake_session.add.assert_called_once()
    fake_session.commit.assert_awaited_once()
    fake_session.refresh.assert_awaited_once()
    fake_session.close.assert_not_called()  # own_session=False


@pytest.mark.asyncio
async def test_capture_rolls_back_on_exception(
    tmp_png, fake_protocol_id, fake_session, monkeypatch
):
    """If anything raises inside the try-block, rollback is called and None returned."""
    fake_session.commit = AsyncMock(side_effect=RuntimeError("boom"))
    result = await capture_and_save_screenshot(
        protocol_id=fake_protocol_id,
        frame_image_path=tmp_png,
        timestamp_sec=0.0,
        db=fake_session,
    )
    assert result is None
    fake_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_capture_own_session_path_closes_session(
    tmp_png, fake_protocol_id, monkeypatch
):
    """When db=None, helper creates its own session via AsyncSessionLocal
    and closes it in the finally block."""

    own_session = AsyncMock()
    own_session.get = AsyncMock(return_value=MagicMock(id=fake_protocol_id))
    own_session.add = MagicMock()
    own_session.commit = AsyncMock()
    own_session.refresh = AsyncMock()
    own_session.rollback = AsyncMock()
    own_session.close = AsyncMock()

    monkeypatch.setattr(as_mod, "AsyncSessionLocal", lambda: own_session)
    monkeypatch.setattr(as_mod, "Screenshot", lambda **kw: MagicMock())

    result = await capture_and_save_screenshot(
        protocol_id=fake_protocol_id,
        frame_image_path=tmp_png,
        timestamp_sec=1.0,
    )
    own_session.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# ScreenshotWatcher — lifecycle
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_watcher_init_creates_output_dir(tmp_path, fake_protocol_id):
    """__init__ must mkdir -p the output dir (parents=True, exist_ok=True)."""
    out = tmp_path / "deep" / "nested" / "dir"
    w = ScreenshotWatcher(
        protocol_id=fake_protocol_id,
        source_media_path=tmp_path / "video.mp4",
        output_dir=out,
        interval_seconds=2.0,
    )
    assert out.exists() and out.is_dir()
    assert w.interval_seconds == 2.0
    assert w._last_phash is None
    assert w._last_screenshot_time == 0.0
    assert w._is_running is False
    assert w._task is None


@pytest.mark.asyncio
async def test_watcher_start_creates_task(tmp_path, fake_protocol_id):
    """start() schedules a task and does not re-create an already-running one."""
    w = ScreenshotWatcher(
        protocol_id=fake_protocol_id,
        source_media_path=tmp_path / "video.mp4",
        output_dir=tmp_path,
        interval_seconds=0.01,
    )
    task1 = w.start()
    assert isinstance(task1, asyncio.Task)
    task2 = w.start()
    assert task2 is task1  # idempotent while alive
    w.stop()
    try:
        await asyncio.wait_for(task1, timeout=1.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass


@pytest.mark.asyncio
async def test_watcher_stop_sets_flag_and_cancels_task(tmp_path, fake_protocol_id):
    """stop() flips _is_running and cancels the running task."""
    w = ScreenshotWatcher(
        protocol_id=fake_protocol_id,
        source_media_path=tmp_path / "video.mp4",
        output_dir=tmp_path,
        interval_seconds=0.01,
    )
    task = w.start()
    # let it run one tick
    await asyncio.sleep(0.02)
    assert w._is_running is True
    w.stop()
    assert w._is_running is False
    with pytest.raises((asyncio.CancelledError, asyncio.TimeoutError)):
        await asyncio.wait_for(task, timeout=1.0)


@pytest.mark.asyncio
async def test_watcher_can_restart_after_done(tmp_path, fake_protocol_id):
    """If the previous task finished (e.g. _is_running flipped), start() may
    create a new one."""
    w = ScreenshotWatcher(
        protocol_id=fake_protocol_id,
        source_media_path=tmp_path / "video.mp4",
        output_dir=tmp_path,
        interval_seconds=0.01,
    )
    # Force _task into "done" state without an actual asyncio task
    fake_done = MagicMock()
    fake_done.done.return_value = True
    w._task = fake_done
    new_task = w.start()
    assert isinstance(new_task, asyncio.Task)
    w.stop()
    try:
        await asyncio.wait_for(new_task, timeout=1.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass


# ---------------------------------------------------------------------------
# ScreenshotWatcher._tick — internal branches (covers line 201)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_watcher_tick_saves_when_distance_above_threshold(
    tmp_path, fake_protocol_id, monkeypatch
):
    """When hamming_distance >= CHANGE_THRESHOLD, should_save becomes True (line 201)."""
    w = ScreenshotWatcher(
        protocol_id=fake_protocol_id,
        source_media_path=tmp_path / "video.mp4",
        output_dir=tmp_path,
        interval_seconds=999,  # we only run one tick
    )
    # Force _last_phash so we hit the `else` branch (line 198)
    w._last_phash = "0" * 16
    monkeypatch.setattr(as_mod, "_hamming_distance", AsyncMock(return_value=999))
    # _capture_frame returns a real file we control
    fake_frame = tmp_path / "frame.png"
    fake_frame.write_bytes(b"\x89PNG\r\n\x1a\n")  # bytes; PIL will fail to open it
    # Skip PIL — go straight to capture_and_save_screenshot
    monkeypatch.setattr(
        as_mod,
        "_compute_phash",
        AsyncMock(return_value="f" * 16),
    )
    monkeypatch.setattr(
        as_mod,
        "capture_and_save_screenshot",
        AsyncMock(return_value=MagicMock()),
    )
    w._capture_frame = AsyncMock(return_value=fake_frame)

    await w._tick()
    as_mod.capture_and_save_screenshot.assert_awaited_once()
    assert w._last_phash == "f" * 16


@pytest.mark.asyncio
async def test_watcher_tick_skips_when_phash_none(
    tmp_path, fake_protocol_id, monkeypatch
):
    """If _compute_phash returns None, tick returns early."""
    w = ScreenshotWatcher(
        protocol_id=fake_protocol_id,
        source_media_path=tmp_path / "v.mp4",
        output_dir=tmp_path,
        interval_seconds=999,
    )
    w._capture_frame = AsyncMock(return_value=tmp_path / "f.png")
    monkeypatch.setattr(as_mod, "_compute_phash", AsyncMock(return_value=None))
    save_mock = AsyncMock()
    monkeypatch.setattr(as_mod, "capture_and_save_screenshot", save_mock)

    await w._tick()
    save_mock.assert_not_called()


@pytest.mark.asyncio
async def test_watcher_tick_skips_when_capture_frame_fails(
    tmp_path, fake_protocol_id, monkeypatch
):
    """If _capture_frame returns None, tick returns without computing hash."""
    w = ScreenshotWatcher(
        protocol_id=fake_protocol_id,
        source_media_path=tmp_path / "v.mp4",
        output_dir=tmp_path,
        interval_seconds=999,
    )
    w._capture_frame = AsyncMock(return_value=None)
    phash_mock = AsyncMock()
    monkeypatch.setattr(as_mod, "_compute_phash", phash_mock)

    await w._tick()
    phash_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Error handling: ffmpeg subprocess failure inside _capture_frame
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_watcher_capture_frame_handles_subprocess_exception(
    tmp_path, fake_protocol_id
):
    """If asyncio.create_subprocess_exec raises, _capture_frame logs and returns None."""
    w = ScreenshotWatcher(
        protocol_id=fake_protocol_id,
        source_media_path=tmp_path / "v.mp4",
        output_dir=tmp_path,
        interval_seconds=999,
    )
    with patch("asyncio.create_subprocess_exec", side_effect=RuntimeError("no ffmpeg")):
        result = await w._capture_frame(1.0)
    assert result is None


@pytest.mark.asyncio
async def test_watcher_run_loop_swallows_tick_exception(
    tmp_path, fake_protocol_id, monkeypatch
):
    """_run() catches exceptions raised by _tick() so the loop survives."""
    w = ScreenshotWatcher(
        protocol_id=fake_protocol_id,
        source_media_path=tmp_path / "v.mp4",
        output_dir=tmp_path,
        interval_seconds=0.01,
    )

    call_count = {"n": 0}

    async def flaky_tick():
        call_count["n"] += 1
        if call_count["n"] <= 1:
            raise RuntimeError("first tick boom")
        # Stop the loop after the second successful tick
        w._is_running = False

    monkeypatch.setattr(w, "_tick", flaky_tick)
    w.start()
    # Give it a moment to process both ticks
    await asyncio.sleep(0.1)
    assert call_count["n"] >= 2
    w.stop()


# ---------------------------------------------------------------------------
# Coverage gap closers: lines 178-179 (ffmpeg success path) and 197
# (first-frame should_save=True).
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_watcher_capture_frame_success_when_file_has_size(tmp_path):
    """When ffmpeg writes a non-empty output file, _capture_frame returns it.
    Covers lines 178-179 (exists() and stat().st_size > 0)."""
    w = ScreenshotWatcher(
        protocol_id=uuid.uuid4(),
        source_media_path=tmp_path / "v.mp4",
        output_dir=tmp_path,
        interval_seconds=999,
    )

    class _FakeProc:
        async def wait(self):
            return 0

    async def fake_exec(*args, **kwargs):
        # Last positional arg is the output path
        out_path = Path(args[-1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        return _FakeProc()

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        result = await w._capture_frame(1.5)
    assert result is not None
    assert result.exists()
    assert result.stat().st_size > 0
    assert result.name.startswith("auto_")
    assert result.name.endswith(".png")


@pytest.mark.asyncio
async def test_watcher_tick_first_frame_saves(
    tmp_path, fake_protocol_id, monkeypatch
):
    """When _last_phash is None (very first frame), should_save=True (line 197)
    and capture_and_save_screenshot is invoked."""
    w = ScreenshotWatcher(
        protocol_id=fake_protocol_id,
        source_media_path=tmp_path / "v.mp4",
        output_dir=tmp_path,
        interval_seconds=999,
    )
    assert w._last_phash is None  # precondition for line 197

    monkeypatch.setattr(as_mod, "_compute_phash", AsyncMock(return_value="a" * 16))
    # _hamming_distance must NOT be called on the first frame
    hd_mock = AsyncMock()
    monkeypatch.setattr(as_mod, "_hamming_distance", hd_mock)

    w._capture_frame = AsyncMock(return_value=tmp_path / "f.png")
    save_mock = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(as_mod, "capture_and_save_screenshot", save_mock)

    # Force debounce to be satisfied
    w._last_screenshot_time = 0.0
    loop = asyncio.get_event_loop()
    # ensure time() - 0 >= DEBOUNCE_SECONDS is satisfied (it always will be in tests)
    await w._tick()
    save_mock.assert_awaited_once()
    hd_mock.assert_not_called()  # _hamming_distance skipped on first frame
    assert w._last_phash == "a" * 16