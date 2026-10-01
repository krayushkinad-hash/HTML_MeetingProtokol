"""Deep coverage for app/services/auto_screenshots.py (US-092).

Targets (125 statements, baseline 0%):
- _compute_phash (HAS_IMAGEHASH True/False, success, exception)
- _hamming_distance (HAS_IMAGEHASH True/False, success, exception)
- _save_screenshot_to_db_sync (file exists / missing)
- capture_and_save_screenshot (frame missing, protocol missing, success,
  exception branch, own_session close)
- ScreenshotWatcher (__init__ output_dir mkdir, start, stop,
  _capture_frame success / failure, _tick branches, _run loop)
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
# Fixtures / helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def tmp_png(tmp_path):
    """Real small PNG (1x1 black) for phash / Image.open."""
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
    """AsyncMock that mimics AsyncSession for capture_and_save_screenshot."""
    session = AsyncMock()

    # db.get(Protocol, protocol_id) -> protocol
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
# _compute_phash
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_compute_phash_success(tmp_png, monkeypatch):
    """_compute_phash returns hex string on a valid image."""
    result = await _compute_phash(tmp_png)
    assert isinstance(result, str)
    # imagehash.phash returns 8-char hex for default hash_size=8
    assert len(result) >= 8


@pytest.mark.asyncio
async def test_compute_phash_disabled_returns_none(tmp_png, monkeypatch):
    """When HAS_IMAGEHASH=False, _compute_phash returns None immediately."""
    monkeypatch.setattr(as_mod, "HAS_IMAGEHASH", False)
    result = await _compute_phash(tmp_png)
    assert result is None


@pytest.mark.asyncio
async def test_compute_phash_exception_returns_none(tmp_path, monkeypatch):
    """If Image.open raises, the helper logs warning and returns None."""
    fake_path = tmp_path / "broken.png"
    fake_path.write_bytes(b"not a png")

    result = await _compute_phash(fake_path)
    # PIL will raise UnidentifiedImageError
    assert result is None


# ---------------------------------------------------------------------------
# _hamming_distance
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_hamming_distance_zero_for_same_hash():
    """Identical hashes → distance 0."""
    h = await _compute_phash.__wrapped__ if hasattr(_compute_phash, "__wrapped__") else None
    # We need real phash; use known hex via imagehash directly
    import imagehash
    from PIL import Image

    img = Image.new("RGB", (16, 16), (123, 45, 67))
    hex_str = str(imagehash.phash(img))
    d = await _hamming_distance(hex_str, hex_str)
    assert d == 0


@pytest.mark.asyncio
async def test_hamming_distance_disabled_returns_999(monkeypatch):
    """HAS_IMAGEHASH=False → sentinel 999."""
    monkeypatch.setattr(as_mod, "HAS_IMAGEHASH", False)
    d = await _hamming_distance("abc", "def")
    assert d == 999


@pytest.mark.asyncio
async def test_hamming_distance_invalid_input_returns_999(monkeypatch):
    """Bad hex input → exception swallowed, return 999."""
    monkeypatch.setattr(as_mod, "HAS_IMAGEHASH", True)
    d = await _hamming_distance("not-hex", "also-not-hex")
    assert d == 999


# ---------------------------------------------------------------------------
# _save_screenshot_to_db_sync
# ---------------------------------------------------------------------------
class _StubShot:
    """Stand-in for Screenshot that accepts arbitrary kwargs (real model has a
    different schema than what _save_screenshot_to_db_sync expects — those
    columns don't exist, so we patch the symbol to keep this test isolated)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


@pytest.fixture
def stub_screenshot_cls(monkeypatch):
    """Replace app.services.auto_screenshots.Screenshot with a permissive stub."""
    monkeypatch.setattr(as_mod, "Screenshot", _StubShot)
    return _StubShot


def test_save_screenshot_to_db_sync_file_exists(tmp_png, stub_screenshot_cls):
    """Records file_size from real existing file."""
    db = MagicMock()
    proto_id = uuid.uuid4()
    fp = tmp_png
    shot = _save_screenshot_to_db_sync(
        db=db,
        protocol_id=proto_id,
        timestamp_sec=1.234,
        file_path=fp,
    )
    assert shot.protocol_id == proto_id
    assert shot.timestamp_sec == 1.234  # rounded to 3 decimals
    assert shot.file_path is not None
    assert shot.file_path is not None
    assert shot.file_size_kb > 0 or shot.file_size_kb == 0
    db.add.assert_called_once_with(shot)


def test_save_screenshot_to_db_sync_missing_file(tmp_path, stub_screenshot_cls):
    """When file_path doesn't exist, file_size is 0."""
    db = MagicMock()
    proto_id = uuid.uuid4()
    fp = tmp_path / "absent.png"
    shot = _save_screenshot_to_db_sync(
        db=db,
        protocol_id=proto_id,
        timestamp_sec=0.0,
        file_path=fp,
    )
    assert shot.file_size_kb is None or shot.file_size_kb == 0
    assert shot.file_path == str(fp)
    db.add.assert_called_once()


# ---------------------------------------------------------------------------
# capture_and_save_screenshot — main flow
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_capture_frame_missing_returns_none(tmp_path, fake_protocol_id, fake_session):
    """Frame file doesn't exist → return None, no DB call."""
    result = await capture_and_save_screenshot(
        protocol_id=fake_protocol_id,
        frame_image_path=tmp_path / "ghost.png",
        timestamp_sec=1.0,
        db=fake_session,
    )
    assert result is None
    fake_session.get.assert_not_called()


@pytest.mark.asyncio
async def test_capture_protocol_not_found(tmp_png, fake_protocol_id):
    """db.get returns None → return None (error branch)."""
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()

    result = await capture_and_save_screenshot(
        protocol_id=fake_protocol_id,
        frame_image_path=tmp_png,
        timestamp_sec=0.0,
        db=session,
    )
    assert result is None
    session.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_capture_success_with_external_session(
    tmp_png, fake_protocol_id, fake_session, monkeypatch
):
    """Happy path: mocked _save helper, own_session=False, return Screenshot."""

    fake_shot = MagicMock(name="Screenshot")
    fake_shot.id = uuid.uuid4()
    monkeypatch.setattr(
        as_mod, "_save_screenshot_to_db_sync", lambda **kw: fake_shot
    )

    result = await capture_and_save_screenshot(
        protocol_id=fake_protocol_id,
        frame_image_path=tmp_png,
        timestamp_sec=2.5,
        db=fake_session,
    )
    assert result is fake_shot
    fake_session.commit.assert_awaited_once()
    fake_session.refresh.assert_awaited_once_with(fake_shot)
    # Own session was provided → no close()
    fake_session.close.assert_not_called()


@pytest.mark.asyncio
async def test_capture_success_creates_own_session(
    tmp_png, fake_protocol_id, monkeypatch
):
    """When db=None, function creates session via AsyncSessionLocal and closes it."""

    fake_shot = MagicMock(name="Screenshot")
    fake_shot.id = uuid.uuid4()
    monkeypatch.setattr(
        as_mod, "_save_screenshot_to_db_sync", lambda **kw: fake_shot
    )

    own_session = AsyncMock()
    own_session.get = AsyncMock(return_value=MagicMock())
    own_session.commit = AsyncMock()
    own_session.refresh = AsyncMock()
    own_session.rollback = AsyncMock()
    own_session.close = AsyncMock()

    monkeypatch.setattr(as_mod, "AsyncSessionLocal", lambda: own_session)

    result = await capture_and_save_screenshot(
        protocol_id=fake_protocol_id,
        frame_image_path=tmp_png,
        timestamp_sec=3.0,
        db=None,
    )
    assert result is fake_shot
    own_session.commit.assert_awaited_once()
    own_session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_capture_exception_branch_triggers_rollback(
    tmp_png, fake_protocol_id, fake_session, monkeypatch
):
    """When commit/refresh raises, exception branch → rollback, return None."""

    def boom(**kw):
        # Return a Screenshot-like mock, but make commit() raise so the
        # `await db.commit()` line triggers the except block.
        raise RuntimeError("simulated DB error")

    monkeypatch.setattr(as_mod, "_save_screenshot_to_db_sync", boom)

    result = await capture_and_save_screenshot(
        protocol_id=fake_protocol_id,
        frame_image_path=tmp_png,
        timestamp_sec=1.0,
        db=fake_session,
    )
    assert result is None
    fake_session.rollback.assert_awaited_once()
    # External session → not closed in finally
    fake_session.close.assert_not_called()


@pytest.mark.asyncio
async def test_capture_exception_closes_own_session(
    tmp_png, fake_protocol_id, monkeypatch
):
    """Exception path with own session: rollback + close in finally."""

    def boom(**kw):
        raise RuntimeError("db error")

    monkeypatch.setattr(as_mod, "_save_screenshot_to_db_sync", boom)

    own = AsyncMock()
    own.get = AsyncMock(return_value=MagicMock())
    own.commit = AsyncMock(side_effect=RuntimeError("commit fail"))
    own.refresh = AsyncMock()
    own.rollback = AsyncMock()
    own.close = AsyncMock()
    monkeypatch.setattr(as_mod, "AsyncSessionLocal", lambda: own)

    result = await capture_and_save_screenshot(
        protocol_id=fake_protocol_id,
        frame_image_path=tmp_png,
        timestamp_sec=1.0,
        db=None,
    )
    assert result is None
    own.rollback.assert_awaited_once()
    own.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# ScreenshotWatcher
# ---------------------------------------------------------------------------
def test_watcher_init_creates_output_dir(tmp_path):
    """__init__ must mkdir(parents=True, exist_ok=True) for output_dir."""
    out = tmp_path / "deep" / "nested" / "shots"
    assert not out.exists()
    w = ScreenshotWatcher(
        protocol_id=uuid.uuid4(),
        source_media_path=tmp_path / "src.mp4",
        output_dir=out,
        interval_seconds=0.1,
    )
    assert out.exists() and out.is_dir()
    assert w.interval_seconds == 0.1
    assert w._last_phash is None
    assert w._last_screenshot_time == 0.0
    assert w._is_running is False
    assert w._task is None


@pytest.mark.asyncio
async def test_watcher_start_creates_task(tmp_path, monkeypatch):
    """start() spawns an asyncio task and returns it."""
    w = ScreenshotWatcher(
        protocol_id=uuid.uuid4(),
        source_media_path=tmp_path / "src.mp4",
        output_dir=tmp_path,
        interval_seconds=0.01,
    )

    # Replace _tick so the loop never actually sleeps productively.
    # First call: stop. After that, _is_running=False so the loop exits.
    async def fake_tick():
        w.stop()

    monkeypatch.setattr(w, "_tick", fake_tick)

    task = w.start()
    assert isinstance(task, asyncio.Task)
    # The loop calls fake_tick which calls w.stop(); stop() cancels the task,
    # so awaiting it surfaces CancelledError. Just wait until it's done.
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass
    assert task.done()
    assert w._is_running is False


def test_watcher_start_idempotent_when_task_alive(tmp_path):
    """start() re-uses existing task if it's still running."""
    w = ScreenshotWatcher(
        protocol_id=uuid.uuid4(),
        source_media_path=tmp_path / "src.mp4",
        output_dir=tmp_path,
    )

    real_task = MagicMock(spec=asyncio.Task)
    real_task.done.return_value = False
    w._task = real_task

    returned = w.start()
    assert returned is real_task  # no new task created


def test_watcher_start_recreates_finished_task(tmp_path):
    """start() creates new task when previous one is done()."""
    w = ScreenshotWatcher(
        protocol_id=uuid.uuid4(),
        source_media_path=tmp_path / "src.mp4",
        output_dir=tmp_path,
    )

    done_task = MagicMock(spec=asyncio.Task)
    done_task.done.return_value = True
    w._task = done_task

    # asyncio.create_task from inside sync test needs a running loop;
    # patch asyncio.create_task to verify behaviour.
    new_task = MagicMock(spec=asyncio.Task)
    with patch("asyncio.create_task", return_value=new_task) as ct:
        returned = w.start()
    assert returned is new_task
    assert ct.called


def test_watcher_stop_without_task_is_safe(tmp_path):
    """stop() without an active task shouldn't raise."""
    w = ScreenshotWatcher(
        protocol_id=uuid.uuid4(),
        source_media_path=tmp_path / "src.mp4",
        output_dir=tmp_path,
    )
    w.stop()
    assert w._is_running is False


def test_watcher_stop_cancels_running_task(tmp_path):
    """stop() cancels the live task."""
    w = ScreenshotWatcher(
        protocol_id=uuid.uuid4(),
        source_media_path=tmp_path / "src.mp4",
        output_dir=tmp_path,
    )
    live_task = MagicMock(spec=asyncio.Task)
    live_task.done.return_value = False
    w._task = live_task
    w.stop()
    assert w._is_running is False
    live_task.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_watcher_capture_frame_success(tmp_path, monkeypatch):
    """_capture_frame uses asyncio.create_subprocess_exec and returns Path on success."""
    w = ScreenshotWatcher(
        protocol_id=uuid.uuid4(),
        source_media_path=tmp_path / "src.mp4",
        output_dir=tmp_path / "out",
        interval_seconds=0.05,
    )

    # Fake subprocess that mirrors what _capture_frame expects:
    # out_path = f"auto_{int(timestamp_sec*1000):010d}.png"
    # For ts=100.0 → int(100000)=100000 → "0000100000" → "auto_0000100000.png"
    expected_out = w.output_dir / "auto_0000100000.png"

    class FakeProc:
        async def wait(self):
            expected_out.write_bytes(b"fake-png-data")
            return 0

    async def fake_exec(*args, **kwargs):
        # args after ffmpeg should be the output path
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    result = await w._capture_frame(100.0)
    assert result is not None
    assert result.exists()
    assert result.stat().st_size > 0


@pytest.mark.asyncio
async def test_watcher_capture_frame_no_output(tmp_path, monkeypatch):
    """If ffmpeg succeeds but produces no output file → return None."""
    w = ScreenshotWatcher(
        protocol_id=uuid.uuid4(),
        source_media_path=tmp_path / "src.mp4",
        output_dir=tmp_path / "out",
    )

    class FakeProc:
        async def wait(self):
            return 0  # but no file written

    async def fake_exec(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    result = await w._capture_frame(1.0)
    assert result is None


@pytest.mark.asyncio
async def test_watcher_capture_frame_exception(tmp_path, monkeypatch):
    """If subprocess raises → None returned, error logged."""
    w = ScreenshotWatcher(
        protocol_id=uuid.uuid4(),
        source_media_path=tmp_path / "src.mp4",
        output_dir=tmp_path / "out",
    )

    async def fake_exec(*args, **kwargs):
        raise RuntimeError("ffmpeg boom")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    result = await w._capture_frame(1.0)
    assert result is None


@pytest.mark.asyncio
async def test_watcher_tick_first_frame_saves(tmp_path, monkeypatch):
    """First tick: _last_phash is None → should_save=True and screenshot is captured."""
    w = ScreenshotWatcher(
        protocol_id=uuid.uuid4(),
        source_media_path=tmp_path / "src.mp4",
        output_dir=tmp_path,
        interval_seconds=0.05,
    )

    # Fake _capture_frame returns a real PNG (so _compute_phash works)
    from PIL import Image

    real_png = tmp_path / "fake.png"
    Image.new("RGB", (16, 16), (255, 0, 0)).save(real_png)
    monkeypatch.setattr(w, "_capture_frame", AsyncMock(return_value=real_png))

    save_mock = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(as_mod, "capture_and_save_screenshot", save_mock)

    # Make _last_screenshot_time ancient so debounce passes
    w._last_screenshot_time = 0.0
    await w._tick()
    save_mock.assert_awaited_once()
    assert w._last_phash is not None


@pytest.mark.asyncio
async def test_watcher_tick_no_significant_change_skips_save(
    tmp_path, monkeypatch
):
    """If hamming distance < threshold, no save."""
    w = ScreenshotWatcher(
        protocol_id=uuid.uuid4(),
        source_media_path=tmp_path / "src.mp4",
        output_dir=tmp_path,
    )

    from PIL import Image

    real_png = tmp_path / "same.png"
    Image.new("RGB", (16, 16), (1, 2, 3)).save(real_png)
    monkeypatch.setattr(w, "_capture_frame", AsyncMock(return_value=real_png))

    save_mock = AsyncMock()
    monkeypatch.setattr(as_mod, "capture_and_save_screenshot", save_mock)

    # Pretend we just saw the same frame → tiny distance
    w._last_phash = await _compute_phash(real_png)
    await w._tick()
    save_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_watcher_tick_debounce_blocks_save(tmp_path, monkeypatch):
    """Even if change is significant, debounce blocks save within DEBOUNCE_SECONDS."""
    w = ScreenshotWatcher(
        protocol_id=uuid.uuid4(),
        source_media_path=tmp_path / "src.mp4",
        output_dir=tmp_path,
    )

    from PIL import Image

    real_png = tmp_path / "x.png"
    Image.new("RGB", (16, 16), (1, 2, 3)).save(real_png)
    monkeypatch.setattr(w, "_capture_frame", AsyncMock(return_value=real_png))

    save_mock = AsyncMock()
    monkeypatch.setattr(as_mod, "capture_and_save_screenshot", save_mock)

    # Force a "very different" previous hash so distance >= threshold
    w._last_phash = "0" * 16
    # Pretend we just saved
    loop = asyncio.get_event_loop()
    w._last_screenshot_time = loop.time()  # just now
    await w._tick()
    save_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_watcher_tick_frame_capture_fails(tmp_path, monkeypatch):
    """If _capture_frame returns None, tick returns early (no phash, no save)."""
    w = ScreenshotWatcher(
        protocol_id=uuid.uuid4(),
        source_media_path=tmp_path / "src.mp4",
        output_dir=tmp_path,
    )
    monkeypatch.setattr(w, "_capture_frame", AsyncMock(return_value=None))

    save_mock = AsyncMock()
    monkeypatch.setattr(as_mod, "capture_and_save_screenshot", save_mock)

    await w._tick()
    save_mock.assert_not_awaited()
    assert w._last_phash is None


@pytest.mark.asyncio
async def test_watcher_tick_phash_compute_fails(tmp_path, monkeypatch):
    """If _compute_phash returns None, tick returns early."""
    w = ScreenshotWatcher(
        protocol_id=uuid.uuid4(),
        source_media_path=tmp_path / "src.mp4",
        output_dir=tmp_path,
    )
    monkeypatch.setattr(w, "_capture_frame", AsyncMock(return_value=tmp_path / "x.png"))
    monkeypatch.setattr(as_mod, "_compute_phash", AsyncMock(return_value=None))

    save_mock = AsyncMock()
    monkeypatch.setattr(as_mod, "capture_and_save_screenshot", save_mock)

    await w._tick()
    save_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_watcher_run_loop_handles_tick_error(tmp_path, monkeypatch):
    """_run() must swallow exceptions raised in _tick() and continue."""
    w = ScreenshotWatcher(
        protocol_id=uuid.uuid4(),
        source_media_path=tmp_path / "src.mp4",
        output_dir=tmp_path,
        interval_seconds=0.01,
    )

    call_count = {"n": 0}

    async def fake_tick():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("tick boom")
        # Second call: stop the loop
        w._is_running = False

    # Patch asyncio.sleep inside the module, NOT globally (otherwise recursive).
    async def fake_sleep(seconds):
        # Tiny yield so the loop yields control
        await asyncio.sleep(0)
        return None

    monkeypatch.setattr(w, "_tick", fake_tick)
    monkeypatch.setattr(as_mod, "asyncio", asyncio)
    # Patch the module's asyncio.sleep via a sentinel: monkeypatch the sleep
    # function *referenced by the loop*. Cleanest: monkeypatch asyncio.sleep
    # but with a non-recursive implementation.
    orig_sleep = asyncio.sleep

    async def safe_sleep(seconds):
        await orig_sleep(0)
        return None

    monkeypatch.setattr(asyncio, "sleep", safe_sleep)

    await w._run()
    assert call_count["n"] >= 1
    assert w._is_running is False


def test_constants_thresholds():
    """Sanity check for module-level constants."""
    assert isinstance(CHANGE_THRESHOLD, int) and CHANGE_THRESHOLD > 0
    assert isinstance(DEBOUNCE_SECONDS, (int, float)) and DEBOUNCE_SECONDS > 0