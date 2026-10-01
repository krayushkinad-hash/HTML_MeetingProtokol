"""Internal coverage v3 for app/services/whisper_models.py + router.

Targets branches NOT yet covered by v1/v2 test files:

HTTP router (/whisper/*):
- GET  /models
- GET  /models/{name}        → 404 unknown, 200 known
- GET  /status/{name}        → 404 unknown, 200 known
- GET  /progress/{name}      → 404 unknown, "not started" branch, "already done" branch
- GET  /active
- POST /active/{name}        → 404 unknown, 200 known
- POST /download/{name}      → 404 unknown, "already_downloaded" branch
- DELETE /models/{name}      → 404 unknown, 200 known

Service (whisper_models.py):
- WhisperModelManager.download_model wrapper → unknown-model error branch (line 289-297)
- _find_cached_model edge: snapshots_dir missing, empty snapshots
- is_downloaded → unknown model returns False
- delete_model → unknown model returns False, missing repo returns False
- get_download_progress → missing key returns None
- get_active_model → returns settings.whisper_model
- set_active_model → unknown model returns False
- Singleton model_manager exists

All HF / network calls are mocked — no real downloads.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import whisper_models as wm
from app.services.whisper_models import (
    AVAILABLE_MODELS,
    MODELS,
    DownloadProgress,
    WhisperModelManager,
)


# ============================================================================
# Service-level: WhisperModelManager
# ============================================================================

class TestManagerServiceEdges:
    """Cover service-level branches not hit by v2."""

    def test_download_model_unknown_returns_error_progress(self):
        """download_model with unknown name returns error progress without impl call."""
        mgr = WhisperModelManager(cache_dir=Path("/tmp"))
        # Impl not called for unknown model — wrapper short-circuits
        with patch.object(mgr, "_download_model_impl") as mock_impl:
            progress = awaitable_sync(mgr.download_model, "nonexistent-model")

        assert progress.success is False
        assert "Unknown model" in progress.error
        assert "nonexistent-model" in progress.error
        assert progress.finished_at is not None
        mock_impl.assert_not_called()
        # Cached for inspection
        assert mgr.get_download_progress("nonexistent-model") is progress

    def test_download_model_known_calls_impl(self, tmp_path):
        """download_model for known model delegates to _download_model_impl."""
        mgr = WhisperModelManager(cache_dir=tmp_path)

        async def fake_impl(name, progress, cb=None):
            progress.success = True
            return progress

        with patch.object(mgr, "_download_model_impl", side_effect=fake_impl):
            progress = awaitable_sync(mgr.download_model, "tiny")

        assert progress.success is True
        assert progress.model_name == "tiny"

    def test_get_download_progress_returns_none_for_unknown(self, tmp_path):
        """get_download_progress returns None when no download started."""
        mgr = WhisperModelManager(cache_dir=tmp_path)
        assert mgr.get_download_progress("tiny") is None

    def test_get_active_model_returns_settings_value(self, tmp_path):
        """get_active_model delegates to settings.whisper_model."""
        mgr = WhisperModelManager(cache_dir=tmp_path)
        # Default from settings
        result = mgr.get_active_model()
        assert result == wm.settings.whisper_model
        assert isinstance(result, str)
        assert result in MODELS

    def test_set_active_model_unknown_returns_false(self, tmp_path):
        """set_active_model with unknown model returns False."""
        mgr = WhisperModelManager(cache_dir=tmp_path)
        assert mgr.set_active_model("totally-fake") is False
        # settings.whisper_model should NOT have been changed
        assert wm.settings.whisper_model != "totally-fake"

    def test_set_active_model_known_returns_true(self, tmp_path):
        """set_active_model with valid model returns True and updates settings."""
        mgr = WhisperModelManager(cache_dir=tmp_path)
        original = wm.settings.whisper_model
        try:
            # Pick a model different from current
            target = "small" if original != "small" else "base"
            assert mgr.set_active_model(target) is True
            assert wm.settings.whisper_model == target
        finally:
            wm.settings.whisper_model = original

    def test_delete_model_unknown_returns_false(self, tmp_path):
        """delete_model with unknown model returns False without touching FS."""
        mgr = WhisperModelManager(cache_dir=tmp_path)
        assert mgr.delete_model("nope") is False

    def test_delete_model_missing_dir_returns_false(self, tmp_path):
        """delete_model with known model but no cached dir returns False."""
        mgr = WhisperModelManager(cache_dir=tmp_path)
        # 'tiny' is valid but nothing in cache yet
        assert mgr.delete_model("tiny") is False

    def test_delete_model_present_returns_true(self, tmp_path):
        """delete_model removes cached repo dir and returns True."""
        mgr = WhisperModelManager(cache_dir=tmp_path)
        repo = MODELS["tiny"][1]
        repo_dir = mgr.cache_dir / ("models--" + repo.replace("/", "--"))
        snap_dir = repo_dir / "snapshots" / "abc"
        snap_dir.mkdir(parents=True)
        (snap_dir / "model.bin").write_bytes(b"x" * 1024)

        assert mgr.delete_model("tiny") is True
        assert not repo_dir.exists()

    def test_delete_model_restore_failure_returns_false(self, tmp_path):
        """If shutil.rmtree raises, delete_model returns False."""
        mgr = WhisperModelManager(cache_dir=tmp_path)
        repo = MODELS["tiny"][1]
        repo_dir = mgr.cache_dir / ("models--" + repo.replace("/", "--"))
        snap_dir = repo_dir / "snapshots" / "abc"
        snap_dir.mkdir(parents=True)

        with patch("app.services.whisper_models.shutil.rmtree",
                    side_effect=OSError("boom")):
            assert mgr.delete_model("tiny") is False

    def test_is_downloaded_unknown_returns_false(self, tmp_path):
        """is_downloaded returns False for unknown model names."""
        mgr = WhisperModelManager(cache_dir=tmp_path)
        assert mgr.is_downloaded("not-a-model") is False


class TestFindCachedModelEdgeBranches:
    """Hit edge branches in _find_cached_model (lines 246-267)."""

    def test_unknown_model_returns_none_zero(self, tmp_path):
        """_find_cached_model for unknown name → (None, 0)."""
        mgr = WhisperModelManager(cache_dir=tmp_path)
        path, size = mgr._find_cached_model("nonexistent")
        assert path is None
        assert size == 0

    def test_repo_dir_exists_but_no_snapshots_subdir(self, tmp_path):
        """repo_dir exists but no 'snapshots' subdir → (None, 0)."""
        mgr = WhisperModelManager(cache_dir=tmp_path)
        repo = MODELS["tiny"][1]
        repo_dir = mgr.cache_dir / ("models--" + repo.replace("/", "--"))
        repo_dir.mkdir(parents=True)
        # No snapshots/ subdir
        path, size = mgr._find_cached_model("tiny")
        assert path is None
        assert size == 0

    def test_snapshots_dir_empty(self, tmp_path):
        """snapshots/ exists but is empty → (None, 0)."""
        mgr = WhisperModelManager(cache_dir=tmp_path)
        repo = MODELS["tiny"][1]
        repo_dir = mgr.cache_dir / ("models--" + repo.replace("/", "--"))
        (repo_dir / "snapshots").mkdir(parents=True)
        path, size = mgr._find_cached_model("tiny")
        assert path is None
        assert size == 0

    def test_snapshots_picks_latest_alphabetically(self, tmp_path):
        """When multiple snapshots exist, picks last in sorted order."""
        mgr = WhisperModelManager(cache_dir=tmp_path)
        repo = MODELS["tiny"][1]
        repo_dir = mgr.cache_dir / ("models--" + repo.replace("/", "--"))
        snap_aaa = repo_dir / "snapshots" / "aaa"
        snap_zzz = repo_dir / "snapshots" / "zzz"
        snap_aaa.mkdir(parents=True)
        snap_zzz.mkdir(parents=True)
        (snap_aaa / "m.bin").write_bytes(b"x" * 100)
        (snap_zzz / "m.bin").write_bytes(b"x" * 200)

        path, size = mgr._find_cached_model("tiny")
        assert path == snap_zzz
        assert size == 200


class TestSingleton:
    """Verify module-level singleton and AVAILABLE_MODELS."""

    def test_module_singleton_exists(self):
        assert wm.model_manager is not None
        assert isinstance(wm.model_manager, WhisperModelManager)

    def test_available_models_matches_sorted_mod_keys(self):
        assert AVAILABLE_MODELS == sorted(MODELS.keys())
        assert "tiny" in AVAILABLE_MODELS
        assert "large-v3" in AVAILABLE_MODELS


# ============================================================================
# HTTP router: /whisper/* endpoints
# ============================================================================

@pytest.fixture
def mock_mgr(tmp_path):
    """WhisperModelManager pointed at tmp_path; expose to monkeypatch."""
    return WhisperModelManager(cache_dir=tmp_path)


class TestWhisperHttpEndpoints:
    """Drive HTTP router — cover 404/200/422/500 paths."""

    @pytest.mark.asyncio
    async def test_list_models_returns_all(self, client, mock_mgr):
        with patch("app.routers.whisper_models.model_manager", mock_mgr):
            r = await client.get("/api/v1/hmp/whisper/models")
        assert r.status_code == 200
        body = r.json()
        assert "models" in body
        assert len(body["models"]) == len(MODELS)
        assert body["active"] == mock_mgr.get_active_model()
        assert set(body["available"]) == set(MODELS.keys())

    @pytest.mark.asyncio
    async def test_get_model_info_unknown_returns_400(self, client, mock_mgr):
        with patch("app.routers.whisper_models.model_manager", mock_mgr):
            r = await client.get("/api/v1/hmp/whisper/models/totally-fake")
        # _validate_model_name raises HTTPException(400) for unknown names
        assert r.status_code == 400
        assert "Unknown model" in r.text

    @pytest.mark.asyncio
    async def test_get_model_info_known_returns_200(self, client, mock_mgr):
        with patch("app.routers.whisper_models.model_manager", mock_mgr):
            r = await client.get("/api/v1/hmp/whisper/models/tiny")
        assert r.status_code == 200
        body = r.json()
        assert body["info"]["name"] == "tiny"
        assert body["info"]["size_mb"] == MODELS["tiny"][0]

    @pytest.mark.asyncio
    async def test_get_status_unknown_returns_400(self, client, mock_mgr):
        with patch("app.routers.whisper_models.model_manager", mock_mgr):
            r = await client.get("/api/v1/hmp/whisper/status/nope")
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_get_status_known_returns_200(self, client, mock_mgr):
        with patch("app.routers.whisper_models.model_manager", mock_mgr):
            r = await client.get("/api/v1/hmp/whisper/status/tiny")
        assert r.status_code == 200
        body = r.json()
        assert body["model"] == "tiny"
        assert body["downloaded"] is False
        assert body["expected_size_mb"] == MODELS["tiny"][0]

    @pytest.mark.asyncio
    async def test_get_progress_unknown_returns_400(self, client, mock_mgr):
        with patch("app.routers.whisper_models.model_manager", mock_mgr):
            r = await client.get("/api/v1/hmp/whisper/progress/nope")
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_get_progress_known_not_started(self, client, mock_mgr):
        """No download started → returns 'not_started' progress dict."""
        with patch("app.routers.whisper_models.model_manager", mock_mgr):
            r = await client.get("/api/v1/hmp/whisper/progress/tiny")
        assert r.status_code == 200
        body = r.json()
        assert body["model_name"] == "tiny"
        assert body["downloaded_bytes"] == 0
        assert body["success"] is None

    @pytest.mark.asyncio
    async def test_get_progress_known_already_downloaded(self, client, mock_mgr):
        """Model already on disk, no in-flight download → returns done progress."""
        # Create a fake cached snapshot with real file size
        repo = MODELS["tiny"][1]
        repo_dir = mock_mgr.cache_dir / ("models--" + repo.replace("/", "--"))
        snap = repo_dir / "snapshots" / "x"
        snap.mkdir(parents=True)
        (snap / "m.bin").write_bytes(b"x" * (MODELS["tiny"][0] * 1024 * 1024))

        with patch("app.routers.whisper_models.model_manager", mock_mgr):
            r = await client.get("/api/v1/hmp/whisper/progress/tiny")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["downloaded_bytes"] > 0

    @pytest.mark.asyncio
    async def test_get_progress_in_flight(self, client, mock_mgr):
        """When a download IS in progress, returns current progress dict."""
        p = DownloadProgress(
            model_name="tiny",
            total_bytes=1000,
            downloaded_bytes=500,
            started_at=1.0,
        )
        p._last_instant_speed = 1.0
        mock_mgr._downloads["tiny"] = p

        with patch("app.routers.whisper_models.model_manager", mock_mgr):
            r = await client.get("/api/v1/hmp/whisper/progress/tiny")
        assert r.status_code == 200
        body = r.json()
        assert body["downloaded_bytes"] == 500
        assert body["total_bytes"] == 1000
        assert 49.0 < body["percent"] < 51.0
        assert body["speed_mbps"] > 0

    @pytest.mark.asyncio
    async def test_get_active_returns_current(self, client, mock_mgr):
        with patch("app.routers.whisper_models.model_manager", mock_mgr):
            r = await client.get("/api/v1/hmp/whisper/active")
        assert r.status_code == 200
        body = r.json()
        assert body["active"] == mock_mgr.get_active_model()

    @pytest.mark.asyncio
    async def test_set_active_unknown_returns_400(self, client, mock_mgr):
        with patch("app.routers.whisper_models.model_manager", mock_mgr):
            r = await client.post("/api/v1/hmp/whisper/active/fake-model")
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_set_active_known_returns_200(self, client, mock_mgr):
        with patch("app.routers.whisper_models.model_manager", mock_mgr):
            r = await client.post("/api/v1/hmp/whisper/active/small")
        assert r.status_code == 200
        body = r.json()
        assert body["active"] == "small"

    @pytest.mark.asyncio
    async def test_download_unknown_returns_400(self, client, mock_mgr):
        with patch("app.routers.whisper_models.model_manager", mock_mgr):
            r = await client.post("/api/v1/hmp/whisper/download/fake")
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_download_already_downloaded(self, client, mock_mgr):
        """When model is already cached, returns 202 with status='already_downloaded'."""
        # Pre-populate cache
        repo = MODELS["tiny"][1]
        repo_dir = mock_mgr.cache_dir / ("models--" + repo.replace("/", "--"))
        snap = repo_dir / "snapshots" / "x"
        snap.mkdir(parents=True)
        # Need size > 90% of expected
        (snap / "m.bin").write_bytes(b"x" * (MODELS["tiny"][0] * 1024 * 1024))

        with patch("app.routers.whisper_models.model_manager", mock_mgr):
            r = await client.post("/api/v1/hmp/whisper/download/tiny")
        assert r.status_code == 202
        body = r.json()
        assert body["status"] == "already_downloaded"
        assert body["model"] == "tiny"

    @pytest.mark.asyncio
    async def test_download_starts_returns_downloading(self, client, mock_mgr):
        """When model NOT cached, returns 202 with status='downloading'."""
        # Mock download_model to be a no-op async
        async def fake_dl(name):
            return DownloadProgress(model_name=name, success=True)

        with patch.object(mock_mgr, "download_model", side_effect=fake_dl), \
             patch("app.routers.whisper_models.model_manager", mock_mgr):
            r = await client.post("/api/v1/hmp/whisper/download/base")
        assert r.status_code == 202
        body = r.json()
        assert body["status"] == "downloading"
        assert body["model"] == "base"

    @pytest.mark.asyncio
    async def test_delete_unknown_returns_400(self, client, mock_mgr):
        with patch("app.routers.whisper_models.model_manager", mock_mgr):
            r = await client.delete("/api/v1/hmp/whisper/models/fake")
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_known_not_cached_returns_200_deleted_false(
        self, client, mock_mgr
    ):
        """Known model but not in cache → 200, deleted=False."""
        with patch("app.routers.whisper_models.model_manager", mock_mgr):
            r = await client.delete("/api/v1/hmp/whisper/models/tiny")
        assert r.status_code == 200
        assert r.json()["deleted"] is False

    @pytest.mark.asyncio
    async def test_delete_known_cached_returns_200_deleted_true(
        self, client, mock_mgr
    ):
        repo = MODELS["tiny"][1]
        repo_dir = mock_mgr.cache_dir / ("models--" + repo.replace("/", "--"))
        (repo_dir / "snapshots" / "x").mkdir(parents=True)

        with patch("app.routers.whisper_models.model_manager", mock_mgr):
            r = await client.delete("/api/v1/hmp/whisper/models/tiny")
        assert r.status_code == 200
        assert r.json()["deleted"] is True
        assert not repo_dir.exists()


# ============================================================================
# Helpers
# ============================================================================

def awaitable_sync(coro_fn, *args, **kwargs):
    """Run a coroutine synchronously from sync test code.

    whisper_models.download_model is async — for sync tests we use
    asyncio.run. Wrapped here so test bodies stay readable.
    """
    import asyncio
    return asyncio.run(coro_fn(*args, **kwargs))