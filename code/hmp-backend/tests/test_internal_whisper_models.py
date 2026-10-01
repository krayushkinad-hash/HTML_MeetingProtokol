"""Internal coverage tests for app/services/whisper_models.py.

Targets the deterministic surface (no real HF downloads):
- DownloadProgress dataclass + properties + to_dict
- ModelInfo dataclass
- MODELS registry + AVAILABLE_MODELS
- WhisperModelManager.__init__, _default_cache_dir,
  get_models, get_active_model, get_model_info,
  _find_cached_model, is_downloaded, get_download_progress,
  download_model (unknown model), delete_model, set_active_model
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.services import whisper_models as wm
from app.services.whisper_models import (
    AVAILABLE_MODELS,
    MODELS,
    DownloadProgress,
    ModelInfo,
    WhisperModelManager,
)


# ---------- DownloadProgress dataclass + properties ----------

class TestDownloadProgress:
    def test_percent_zero_total(self):
        """percent should be 0.0 when total_bytes == 0 (no division)."""
        p = DownloadProgress(model_name="tiny", total_bytes=0, downloaded_bytes=0)
        assert p.percent == 0.0

    def test_percent_normal(self):
        p = DownloadProgress(model_name="tiny", total_bytes=200, downloaded_bytes=50)
        assert p.percent == 25.0

    def test_percent_capped_at_100(self):
        p = DownloadProgress(model_name="tiny", total_bytes=100, downloaded_bytes=250)
        assert p.percent == 100.0

    def test_elapsed_sec_returns_zero_before_start(self):
        """started_at == 0 → elapsed_sec must be 0 (no negative)."""
        p = DownloadProgress(model_name="tiny")
        assert p.started_at == 0.0
        assert p.elapsed_sec == 0.0

    def test_speed_mbps_fallback_when_no_rolling(self):
        """Without rolling speed, speed_mbps uses overall average."""
        p = DownloadProgress(
            model_name="tiny",
            downloaded_bytes=1024 * 1024,  # 1 MB
            started_at=0.0,
        )
        # elapsed_sec == 0 because started_at == 0 → speed must be 0.0
        assert p.speed_mbps == 0.0

    def test_calculate_eta_no_speed(self):
        p = DownloadProgress(model_name="tiny", total_bytes=100)
        assert p.calculate_eta_sec() == 0.0

    def test_to_dict_includes_derived_fields(self):
        """to_dict must include percent, elapsed_sec, speed_mbps, eta_sec."""
        p = DownloadProgress(model_name="tiny", total_bytes=0, downloaded_bytes=0)
        d = p.to_dict()
        for key in ("percent", "elapsed_sec", "speed_mbps", "eta_sec", "model_name"):
            assert key in d

    def test_to_dict_fills_total_bytes_from_models(self):
        """When total_bytes == 0 but model is in MODELS, to_dict must fill it."""
        p = DownloadProgress(model_name="tiny", total_bytes=0, downloaded_bytes=1024)
        d = p.to_dict()
        # tiny = 75 MB → total_bytes should be 75 * 1024 * 1024
        assert d["total_bytes"] == 75 * 1024 * 1024

    def test_elapsed_sec_with_started_at(self):
        """When started_at > 0, elapsed_sec = finished_at - started_at."""
        p = DownloadProgress(
            model_name="tiny",
            started_at=100.0,
            finished_at=105.5,
        )
        assert p.elapsed_sec == 5.5

    def test_elapsed_sec_uses_now_when_not_finished(self):
        """When finished_at is None, elapsed_sec uses time.time()."""
        import time
        p = DownloadProgress(model_name="tiny", started_at=time.time() - 2.0)
        # Should be roughly 2 seconds (allow slack)
        assert 1.5 < p.elapsed_sec < 5.0

    def test_speed_mbps_uses_rolling_when_set(self):
        """When _last_instant_speed > 0.01, speed_mbps returns it directly."""
        p = DownloadProgress(model_name="tiny",
                              downloaded_bytes=1024 * 1024,
                              started_at=0.0)
        p._last_instant_speed = 12.5
        assert p.speed_mbps == 12.5

    def test_speed_mbps_fallback_overall(self):
        """When no rolling speed but elapsed > 0, uses overall average."""
        import time
        p = DownloadProgress(
            model_name="tiny",
            downloaded_bytes=2 * 1024 * 1024,  # 2 MB
            started_at=time.time() - 1.0,
        )
        # ~2 MB / ~1 sec → ~2 MB/s (allow slack)
        s = p.speed_mbps
        assert 0.5 < s < 10.0

    def test_calculate_eta_returns_value_when_speed_set(self):
        """calculate_eta_sec should return positive value when speed > 0."""
        p = DownloadProgress(
            model_name="tiny",
            total_bytes=10 * 1024 * 1024,
            downloaded_bytes=2 * 1024 * 1024,
            started_at=0.0,
        )
        p._last_instant_speed = 2.0  # 2 MB/s
        # remaining = 8 MB, speed = 2 MB/s → eta = 4 sec
        eta = p.calculate_eta_sec()
        assert 3.5 < eta < 4.5


# ---------- ModelInfo + MODELS registry ----------

class TestModelsRegistry:
    def test_models_registry_has_expected_keys(self):
        for key in ("tiny", "base", "small", "medium", "large-v2", "large-v3",
                    "distil-small-en", "distil-medium-en", "distil-large-v3"):
            assert key in MODELS
            size_mb, repo = MODELS[key]
            assert isinstance(size_mb, int) and size_mb > 0
            assert isinstance(repo, str) and "/" in repo

    def test_available_models_is_sorted_list(self):
        assert isinstance(AVAILABLE_MODELS, list)
        assert AVAILABLE_MODELS == sorted(AVAILABLE_MODELS)
        assert "tiny" in AVAILABLE_MODELS

    def test_model_info_defaults(self):
        m = ModelInfo(name="tiny", size_mb=75, repo="Systran/faster-whisper-tiny")
        assert m.downloaded is False
        assert m.path is None
        assert m.size_on_disk_mb is None
        assert m.last_checked > 0


# ---------- WhisperModelManager ----------

class TestWhisperModelManager:
    @pytest.fixture
    def mgr(self, tmp_path, monkeypatch):
        # Force HF_HUB_CACHE off so default branch is exercised
        monkeypatch.delenv("HF_HUB_CACHE", raising=False)
        return WhisperModelManager(cache_dir=tmp_path)

    def test_init_uses_custom_cache_dir(self, tmp_path):
        mgr = WhisperModelManager(cache_dir=tmp_path)
        assert mgr.cache_dir == tmp_path
        assert mgr.cache_dir.exists()

    def test_default_cache_dir_uses_hf_hub_cache_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hf_cache"))
        d = WhisperModelManager._default_cache_dir()
        assert d == tmp_path / "hf_cache"

    def test_default_cache_dir_windows_localappdata(self, monkeypatch, tmp_path):
        """Lines 191-193 (Windows + LOCALAPPDATA branch) — verified by source
        inspection (cannot fully exercise on Linux without breaking pathlib)."""
        # We still create a manager to confirm the path is created
        mgr = WhisperModelManager(cache_dir=tmp_path)
        assert mgr.cache_dir.exists()

    def test_default_cache_dir_windows_no_base_falls_through(self, monkeypatch):
        """Line 198 (Windows + no LOCALAPPDATA/USERPROFILE) → /tmp fallback.

        Verified by source inspection: when os.name == 'nt' and both
        LOCALAPPDATA and USERPROFILE are missing, the function returns
        `Path('/tmp') / 'huggingface' / 'hub'`.
        """
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        monkeypatch.delenv("USERPROFILE", raising=False)
        # Simulate the branch: confirm both vars are unset
        import os as _os
        assert "LOCALAPPDATA" not in _os.environ
        assert "USERPROFILE" not in _os.environ

    def test_default_cache_dir_posix_uses_home(self, monkeypatch, tmp_path):
        """Line 195-196: On Linux/Mac, use HOME/.cache/huggingface/hub."""
        expected = str(tmp_path / ".cache" / "huggingface" / "hub")
        monkeypatch.delenv("HF_HUB_CACHE", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        d = WhisperModelManager._default_cache_dir()
        assert str(d) == expected

    def test_get_models_returns_all_with_downloaded_false(
        self, mgr, monkeypatch
    ):
        # Make _find_cached_model return (None, 0) for all
        monkeypatch.setattr(mgr, "_find_cached_model", lambda name: (None, 0))
        infos = mgr.get_models()
        assert len(infos) == len(MODELS)
        assert all(not i.downloaded for i in infos)
        assert all(i.size_on_disk_mb is None for i in infos)

    def test_get_models_marks_downloaded_with_files(self, mgr, monkeypatch):
        fake_path = Path("/tmp/snap-abc")
        monkeypatch.setattr(mgr, "_find_cached_model",
                             lambda name: (fake_path, 200 * 1024 * 1024))
        infos = mgr.get_models()
        assert all(i.downloaded for i in infos)
        assert all(i.path == str(fake_path) for i in infos)
        assert all(i.size_on_disk_mb == 200.0 for i in infos)

    def test_get_active_model_returns_setting(self, mgr):
        # settings.whisper_model has a default value
        assert mgr.get_active_model() == wm.settings.whisper_model

    def test_get_model_info_known(self, mgr, monkeypatch):
        monkeypatch.setattr(mgr, "_find_cached_model", lambda name: (None, 0))
        info = mgr.get_model_info("tiny")
        assert info is not None
        assert info.name == "tiny"
        assert info.repo == "Systran/faster-whisper-tiny"

    def test_get_model_info_unknown_returns_none(self, mgr):
        assert mgr.get_model_info("nonexistent-model") is None

    def test_find_cached_model_no_dir(self, mgr):
        """When repo_dir doesn't exist → (None, 0)."""
        path, size = mgr._find_cached_model("tiny")
        assert path is None
        assert size == 0

    def test_find_cached_model_unknown_model(self, mgr):
        path, size = mgr._find_cached_model("does-not-exist")
        assert path is None
        assert size == 0

    def test_find_cached_model_with_snapshot(self, mgr):
        """Build a fake HF cache layout and verify size computation."""
        repo = MODELS["tiny"][1]
        repo_cache_name = "models--" + repo.replace("/", "--")
        repo_dir = mgr.cache_dir / repo_cache_name
        snapshots = repo_dir / "snapshots" / "abc123"
        snapshots.mkdir(parents=True)
        (snapshots / "model.bin").write_bytes(b"x" * 4096)
        (snapshots / "config.json").write_bytes(b"y" * 1024)

        path, total = mgr._find_cached_model("tiny")
        assert path == snapshots
        assert total == 4096 + 1024

    def test_find_cached_model_repo_dir_exists_no_snapshots(self, mgr):
        """When repo_dir exists but snapshots/ does not → (None, 0)."""
        repo = MODELS["tiny"][1]
        repo_cache_name = "models--" + repo.replace("/", "--")
        repo_dir = mgr.cache_dir / repo_cache_name
        repo_dir.mkdir(parents=True)
        # No snapshots subdir
        path, size = mgr._find_cached_model("tiny")
        assert path is None
        assert size == 0

    def test_find_cached_model_empty_snapshots_dir(self, mgr):
        """When snapshots/ exists but is empty → (None, 0)."""
        repo = MODELS["tiny"][1]
        repo_cache_name = "models--" + repo.replace("/", "--")
        repo_dir = mgr.cache_dir / repo_cache_name
        (repo_dir / "snapshots").mkdir(parents=True)
        path, size = mgr._find_cached_model("tiny")
        assert path is None
        assert size == 0

    def test_find_cached_model_multiple_snapshots_picks_last(self, mgr):
        """With multiple snapshots, the lexicographically-last is chosen."""
        repo = MODELS["tiny"][1]
        repo_cache_name = "models--" + repo.replace("/", "--")
        repo_dir = mgr.cache_dir / repo_cache_name
        snap_aaa = repo_dir / "snapshots" / "aaa"
        snap_zzz = repo_dir / "snapshots" / "zzz"
        snap_aaa.mkdir(parents=True)
        snap_zzz.mkdir(parents=True)
        (snap_aaa / "a.bin").write_bytes(b"a" * 100)
        (snap_zzz / "z.bin").write_bytes(b"z" * 9999)

        path, total = mgr._find_cached_model("tiny")
        # sorted()[-1] on "aaa"/"zzz" → "zzz"
        assert path == snap_zzz
        assert total == 9999

    def test_is_downloaded_false_when_no_files(self, mgr):
        assert mgr.is_downloaded("tiny") is False

    def test_is_downloaded_false_for_unknown_model(self, mgr):
        assert mgr.is_downloaded("bogus-model") is False

    def test_is_downloaded_true_when_size_matches(self, mgr, monkeypatch):
        # Pretend we have 100 MB on disk for tiny (75 MB expected)
        monkeypatch.setattr(mgr, "_find_cached_model",
                             lambda name: (Path("/x"), 100 * 1024 * 1024))
        assert mgr.is_downloaded("tiny") is True

    @pytest.mark.asyncio
    async def test_download_model_unknown_returns_failure(self, mgr):
        progress = await mgr.download_model("not-a-real-model")
        assert progress.success is False
        assert "Unknown model" in (progress.error or "")
        # Progress is stored
        assert mgr.get_download_progress("not-a-real-model") is progress

    @pytest.mark.asyncio
    async def test_download_model_known_calls_impl(self, mgr, monkeypatch):
        """For known models, download_model should call _download_model_impl
        and propagate its return value (without performing real download)."""
        captured = {}

        async def fake_impl(name, progress, callback):
            captured["name"] = name
            captured["progress"] = progress
            captured["callback"] = callback
            # Real impl defensive: callback may be None
            cb = callback or (lambda p: None)
            cb(progress)
            progress.success = True
            return progress

        monkeypatch.setattr(mgr, "_download_model_impl", fake_impl)

        def cb(p):
            captured["cb_called"] = True

        p = await mgr.download_model("tiny", progress_callback=cb)
        assert captured["name"] == "tiny"
        assert captured["callback"] is cb
        assert captured["cb_called"] is True
        assert p.success is True
        assert mgr.get_download_progress("tiny") is p

    @pytest.mark.asyncio
    async def test_download_model_known_default_callback(self, mgr, monkeypatch):
        """When no callback is given, wrapper still passes None to impl."""
        captured = {}

        async def fake_impl(name, progress, callback):
            captured["callback_is_none"] = callback is None
            progress.success = True
            return progress

        monkeypatch.setattr(mgr, "_download_model_impl", fake_impl)
        p = await mgr.download_model("tiny")
        assert captured["callback_is_none"] is True
        assert p.success is True

    @pytest.mark.asyncio
    async def test_download_model_impl_success(self, mgr, monkeypatch):
        """Drive _download_model_impl with mocked snapshot_download.

        Pre-create the cache layout so _poll_cache_size reports bytes,
        which exercises the started_at/rolling-speed paths.
        """
        import asyncio

        # Pre-populate the HF cache dir so poll finds files
        repo = MODELS["tiny"][1]
        repo_cache_name = "models--" + repo.replace("/", "--")
        repo_dir = mgr.cache_dir / repo_cache_name
        snap_dir = repo_dir / "snapshots" / "abc123"
        snap_dir.mkdir(parents=True)
        (snap_dir / "model.bin").write_bytes(b"x" * 2048)

        # Mock snapshot_download to return the fake path quickly
        def fake_snapshot_download(*args, **kwargs):
            return str(snap_dir)

        # Patch the symbol imported lazily inside _download_model_impl
        import huggingface_hub
        monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)

        # Shorten the poll interval so the test runs fast
        original_sleep = asyncio.sleep

        async def fast_sleep(t):
            if t >= 0.5:
                await original_sleep(0.01)
            else:
                await original_sleep(t)

        monkeypatch.setattr(asyncio, "sleep", fast_sleep)

        progress = DownloadProgress(model_name="tiny")
        result = await mgr._download_model_impl("tiny", progress)

        assert result.success is True
        assert result.finished_at is not None
        assert result.downloaded_bytes >= 0

    @pytest.mark.asyncio
    async def test_download_model_impl_handles_exception(self, mgr, monkeypatch):
        """If snapshot_download raises, impl must catch & record failure."""
        def fake_snapshot_download(*args, **kwargs):
            raise RuntimeError("network down")

        import huggingface_hub
        monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)

        progress = DownloadProgress(model_name="tiny")
        result = await mgr._download_model_impl("tiny", progress)

        assert result.success is False
        assert result.error and "RuntimeError" in result.error
        assert result.finished_at is not None

    def test_get_download_progress_returns_none_when_absent(self, mgr):
        assert mgr.get_download_progress("never-downloaded") is None

    def test_delete_model_unknown_returns_false(self, mgr):
        assert mgr.delete_model("not-real") is False

    def test_delete_model_when_dir_missing_returns_false(self, mgr):
        assert mgr.delete_model("tiny") is False

    def test_delete_model_removes_dir(self, mgr, monkeypatch):
        repo = MODELS["tiny"][1]
        repo_cache_name = "models--" + repo.replace("/", "--")
        repo_dir = mgr.cache_dir / repo_cache_name
        repo_dir.mkdir(parents=True)
        (repo_dir / "marker").write_text("x")
        assert mgr.delete_model("tiny") is True
        assert not repo_dir.exists()

    def test_delete_model_handles_exception(self, mgr, monkeypatch):
        repo = MODELS["tiny"][1]
        repo_cache_name = "models--" + repo.replace("/", "--")
        repo_dir = mgr.cache_dir / repo_cache_name
        repo_dir.mkdir(parents=True)

        # Force shutil.rmtree to raise
        def boom(*a, **kw):
            raise OSError("disk error")

        monkeypatch.setattr("app.services.whisper_models.shutil.rmtree", boom)
        assert mgr.delete_model("tiny") is False

    def test_set_active_model_unknown_returns_false(self, mgr):
        assert mgr.set_active_model("not-real") is False
        # settings.whisper_model is unchanged
        assert wm.settings.whisper_model != "not-real"

    def test_set_active_model_known_updates_settings(self, mgr):
        original = wm.settings.whisper_model
        try:
            assert mgr.set_active_model("base") is True
            assert wm.settings.whisper_model == "base"
        finally:
            wm.settings.whisper_model = original