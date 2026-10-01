"""Internal coverage tests for app/routers/whisper_models.py (US-058).

Goal: 60%+ statements + branch coverage on the router. Tests are unit-level
(no DB, no real HF downloads): we build a minimal FastAPI app that mounts
only the whisper router, and monkeypatch the `model_manager` symbol on the
router module so we control every manager method.

Endpoints covered:
- GET    /whisper/models                   → list_models
- GET    /whisper/models/{name}            → get_model_info   (200 / 400 / 404)
- DELETE /whisper/models/{name}            → delete_model     (200 / 400)
- GET    /whisper/active                   → get_active
- POST   /whisper/active/{name}            → set_active       (200 / 400 / 500)
- POST   /whisper/download/{name}          → download_model   (200 downloading / 200 already)
- GET    /whisper/progress/{name}          → get_progress     (200 in-progress / not-started / done / 400)
- GET    /whisper/status/{name}            → get_status       (200 / 400)
- GET    /whisper/debug/proxy              → debug_proxy
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.routers import whisper_models as wm_router
from app.services.whisper_models import AVAILABLE_MODELS, DownloadProgress, ModelInfo


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

API_PREFIX = "/whisper"


class _FakeManager:
    """Stand-in for `model_manager` covering every method the router calls.

    Each test sets only the methods it cares about. Anything not set returns
    a MagicMock (which is fine because we won't exercise those branches).
    """

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or Path("/tmp/fake_hf_cache")
        # Defaults — overridable per-test
        self._models: list[ModelInfo] = []
        self._active: str = "tiny"
        self._info_map: dict[str, ModelInfo | None] = {}
        self._downloaded: dict[str, bool] = {}
        self._download_progress: dict[str, DownloadProgress] = {}
        self._delete_ok: dict[str, bool] = {}
        self._set_active_ok: dict[str, bool] = {}

    # --- sync methods used by GET handlers ---

    def get_models(self):
        return self._models

    def get_active_model(self):
        return self._active

    def get_model_info(self, name):
        return self._info_map.get(name)

    def is_downloaded(self, name):
        return self._downloaded.get(name, False)

    def get_download_progress(self, name):
        return self._download_progress.get(name)

    def delete_model(self, name):
        return self._delete_ok.get(name, True)

    def set_active_model(self, name):
        return self._set_active_ok.get(name, True)

    # --- async method used by download handler ---

    async def download_model(self, name, progress_callback=None):
        # Real impl returns a DownloadProgress; tests that care pin their own.
        return DownloadProgress(model_name=name, success=True)


@pytest.fixture
def fake_manager():
    return _FakeManager()


@pytest_asyncio.fixture
async def client(fake_manager, monkeypatch):
    """Mount the router on a bare FastAPI app and monkeypatch model_manager."""
    # Patch the symbol where the router looks it up
    monkeypatch.setattr(wm_router, "model_manager", fake_manager)

    app = FastAPI()
    # The router already declares prefix="/whisper"; don't double-prefix.
    app.include_router(wm_router.router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _mk_info(name: str, *, downloaded: bool = False, size_mb: int | None = 75,
             size_on_disk_mb: float | None = None) -> ModelInfo:
    return ModelInfo(
        name=name,
        size_mb=size_mb if size_mb is not None else 75,
        repo=f"Systran/faster-whisper-{name}",
        downloaded=downloaded,
        path="/fake/model.bin" if downloaded else None,
        size_on_disk_mb=size_on_disk_mb if size_on_disk_mb is not None else (
            70.0 if downloaded else None
        ),
        last_checked=datetime.now(timezone.utc).timestamp(),
    )


# ---------------------------------------------------------------------------
# GET /whisper/models — list_models
# ---------------------------------------------------------------------------

class TestListModels:
    @pytest.mark.asyncio
    async def test_list_returns_models_and_active_and_available(
        self, client, fake_manager
    ):
        fake_manager._models = [
            _mk_info("tiny", downloaded=False),
            _mk_info("base", downloaded=True, size_mb=140, size_on_disk_mb=130.5),
        ]
        fake_manager._active = "base"

        r = await client.get(f"{API_PREFIX}/models")
        assert r.status_code == 200
        body = r.json()
        assert len(body["models"]) == 2
        assert body["active"] == "base"
        assert set(body["available"]) == set(AVAILABLE_MODELS)
        assert body["cache_dir"] == str(fake_manager.cache_dir)


# ---------------------------------------------------------------------------
# GET /whisper/models/{name} — get_model_info (200, 400, 404)
# ---------------------------------------------------------------------------

class TestGetModelInfo:
    @pytest.mark.asyncio
    async def test_get_info_happy(self, client, fake_manager):
        info = _mk_info("tiny", downloaded=True, size_mb=75, size_on_disk_mb=70.0)
        fake_manager._info_map["tiny"] = info

        r = await client.get(f"{API_PREFIX}/models/tiny")
        assert r.status_code == 200
        assert r.json()["info"]["name"] == "tiny"
        assert r.json()["info"]["downloaded"] is True

    @pytest.mark.asyncio
    async def test_get_info_unknown_model_returns_400(self, client):
        # _validate_model_name triggers BEFORE get_model_info — 400, not 404
        r = await client.get(f"{API_PREFIX}/models/does-not-exist")
        assert r.status_code == 400
        assert "Unknown model" in r.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_info_known_name_but_info_is_none_returns_404(
        self, client, fake_manager
    ):
        # Validates name OK but get_model_info returns None → 404
        fake_manager._info_map["tiny"] = None
        r = await client.get(f"{API_PREFIX}/models/tiny")
        assert r.status_code == 404
        assert "Model not found" in r.json()["detail"]


# ---------------------------------------------------------------------------
# GET /whisper/active — get_active
# ---------------------------------------------------------------------------

class TestActiveGet:
    @pytest.mark.asyncio
    async def test_get_active(self, client, fake_manager):
        fake_manager._active = "small"
        r = await client.get(f"{API_PREFIX}/active")
        assert r.status_code == 200
        assert r.json() == {"active": "small"}


# ---------------------------------------------------------------------------
# POST /whisper/active/{name} — set_active (200, 400, 500)
# ---------------------------------------------------------------------------

class TestActiveSet:
    @pytest.mark.asyncio
    async def test_set_active_ok(self, client, fake_manager):
        fake_manager._set_active_ok["base"] = True
        r = await client.post(f"{API_PREFIX}/active/base")
        assert r.status_code == 200
        assert r.json() == {"active": "base"}

    @pytest.mark.asyncio
    async def test_set_active_unknown_returns_400(self, client):
        r = await client.post(f"{API_PREFIX}/active/nope")
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_set_active_returns_false_raises_500(self, client, fake_manager):
        # Manager returns False → router raises 500
        fake_manager._set_active_ok["tiny"] = False
        r = await client.post(f"{API_PREFIX}/active/tiny")
        assert r.status_code == 500
        assert "Failed to set" in r.json()["detail"]


# ---------------------------------------------------------------------------
# POST /whisper/download/{name} — download_model (downloading / already / 400)
# ---------------------------------------------------------------------------

class TestDownload:
    @pytest.mark.asyncio
    async def test_download_starts_background(self, client, fake_manager):
        fake_manager._downloaded["tiny"] = False
        fake_manager._info_map["tiny"] = _mk_info("tiny", downloaded=False)

        r = await client.post(f"{API_PREFIX}/download/tiny")
        assert r.status_code == 202
        body = r.json()
        assert body["status"] == "downloading"
        assert body["model"] == "tiny"
        assert "Poll" in body["message"]
        assert body["info"] is not None

    @pytest.mark.asyncio
    async def test_download_already_cached(self, client, fake_manager):
        fake_manager._downloaded["tiny"] = True
        fake_manager._info_map["tiny"] = _mk_info("tiny", downloaded=True)

        r = await client.post(f"{API_PREFIX}/download/tiny")
        assert r.status_code == 202
        body = r.json()
        assert body["status"] == "already_downloaded"
        assert body["info"]["downloaded"] is True

    @pytest.mark.asyncio
    async def test_download_unknown_returns_400(self, client):
        r = await client.post(f"{API_PREFIX}/download/not-a-model")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# GET /whisper/progress/{name} — get_progress (in-progress / not-started / done / 400)
# ---------------------------------------------------------------------------

class TestProgress:
    @pytest.mark.asyncio
    async def test_progress_in_flight(self, client, fake_manager):
        # Progress IS active — return False
        # In-flight download → returns progress.to_dict()
        prog = DownloadProgress(
            model_name="tiny",
            total_bytes=100,
            downloaded_bytes=42,
            started_at=1.0,
        )
        fake_manager._download_progress["tiny"] = prog

        r = await client.get(f"{API_PREFIX}/progress/tiny")
        assert r.status_code == 200
        body = r.json()
        assert body["model_name"] == "tiny"
        assert body["total_bytes"] == 100
        assert body["downloaded_bytes"] == 42

    @pytest.mark.asyncio
    async def test_progress_not_started_returns_zero(self, client, fake_manager):
        # No active progress, info is None → not_started branch
        fake_manager._info_map["tiny"] = None

        r = await client.get(f"{API_PREFIX}/progress/tiny")
        assert r.status_code == 200
        body = r.json()
        assert body["model_name"] == "tiny"
        assert body["success"] is None
        assert body["downloaded_bytes"] == 0
        # total_bytes filled from MODELS registry by DownloadProgress.to_dict()
        # (tiny = 75 MB). Verify the not-started shape (success None, dl=0)
        # rather than the exact byte count, which is owned by the service.
        assert body["total_bytes"] == 75 * 1024 * 1024

    @pytest.mark.asyncio
    async def test_progress_already_downloaded_branch(self, client, fake_manager):
        # No active progress but info says downloaded=True → "done" branch
        info = _mk_info("tiny", downloaded=True, size_mb=75, size_on_disk_mb=70.0)
        fake_manager._info_map["tiny"] = info

        r = await client.get(f"{API_PREFIX}/progress/tiny")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        # total_bytes derived from size_on_disk_mb
        assert body["total_bytes"] == int(70.0 * 1024 * 1024)
        assert body["downloaded_bytes"] == body["total_bytes"]

    @pytest.mark.asyncio
    async def test_progress_unknown_returns_400(self, client):
        r = await client.get(f"{API_PREFIX}/progress/not-a-model")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# GET /whisper/status/{name} — get_status (200 / 400)
# ---------------------------------------------------------------------------

class TestStatus:
    @pytest.mark.asyncio
    async def test_status_downloaded(self, client, fake_manager):
        info = _mk_info("tiny", downloaded=True, size_mb=75, size_on_disk_mb=70.5)
        fake_manager._info_map["tiny"] = info
        fake_manager._downloaded["tiny"] = True

        r = await client.get(f"{API_PREFIX}/status/tiny")
        assert r.status_code == 200
        body = r.json()
        assert body["downloaded"] is True
        assert body["expected_size_mb"] == 75
        assert body["size_mb"] == 70.5
        assert body["path"] == "/fake/model.bin"

    @pytest.mark.asyncio
    async def test_status_not_downloaded(self, client, fake_manager):
        # Info exists, downloaded=False, size_on_disk_mb=None → 0.0
        info = _mk_info("tiny", downloaded=False, size_mb=75, size_on_disk_mb=None)
        fake_manager._info_map["tiny"] = info
        fake_manager._downloaded["tiny"] = False

        r = await client.get(f"{API_PREFIX}/status/tiny")
        assert r.status_code == 200
        body = r.json()
        assert body["downloaded"] is False
        assert body["size_mb"] == 0.0  # None branch → 0.0
        assert body["path"] is None

    @pytest.mark.asyncio
    async def test_status_unknown_returns_400(self, client):
        r = await client.get(f"{API_PREFIX}/status/not-a-model")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /whisper/models/{name} — delete_model (200 ok / 200 fail / 400)
# ---------------------------------------------------------------------------

class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_ok(self, client, fake_manager):
        fake_manager._delete_ok["tiny"] = True
        r = await client.delete(f"{API_PREFIX}/models/tiny")
        assert r.status_code == 200
        assert r.json() == {"deleted": True, "model": "tiny"}

    @pytest.mark.asyncio
    async def test_delete_returns_false_still_200(self, client, fake_manager):
        # Router wraps ok in DeleteResponse(deleted=ok, model=name) regardless
        fake_manager._delete_ok["tiny"] = False
        r = await client.delete(f"{API_PREFIX}/models/tiny")
        assert r.status_code == 200
        assert r.json() == {"deleted": False, "model": "tiny"}

    @pytest.mark.asyncio
    async def test_delete_unknown_returns_400(self, client):
        r = await client.delete(f"{API_PREFIX}/models/not-a-model")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# GET /whisper/debug/proxy — debug_proxy
# ---------------------------------------------------------------------------

class TestDebugProxy:
    @pytest.mark.asyncio
    async def test_debug_proxy_returns_env_keys(self, client, monkeypatch):
        # Set a known value to assert round-trip
        monkeypatch.setenv("HTTP_PROXY", "http://example.invalid:8080")
        monkeypatch.setenv("HF_HUB_DISABLE_PROGRESS_BARS", "1")

        r = await client.get(f"{API_PREFIX}/debug/proxy")
        assert r.status_code == 200
        body = r.json()
        for k in (
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SOCKS_PROXY",
            "http_proxy", "https_proxy", "all_proxy", "socks_proxy",
            "HF_HUB_DISABLE_PROGRESS_BARS", "HTTPX_DISABLE_PROXY",
        ):
            assert k in body
        assert body["HTTP_PROXY"] == "http://example.invalid:8080"
        assert body["HF_HUB_DISABLE_PROGRESS_BARS"] == "1"