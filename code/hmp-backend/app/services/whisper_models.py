"""Whisper Model Manager — explicit control + progress + validation.

US-058: Явное управление моделями Whisper через settings + UI.

Endpoints (US-058):
- GET  /whisper/models         — list available models and their status
- POST /whisper/download/{size} — download model with progress
- GET  /whisper/progress/{size} — current download progress
- DELETE /whisper/{size}       — remove model files
- POST /whisper/active/{size}  — set active model

Сейчас реализован только сервис (без API роутера).
"""
from __future__ import annotations

# E061: Disable SOCKS/HTTP proxies at module import (BEFORE huggingface_hub loads)
# SOCKS proxy (socks4://127.0.0.1:10808) breaks huggingface_hub download
import os as _os
_PROXY_VARS = [
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SOCKS_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "socks_proxy",
]
for _pvar in _PROXY_VARS:
    if _pvar in _os.environ:
        del _os.environ[_pvar]
_os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

# E061c: Monkey-patch urllib.request.getproxies() to return {} 
# (E061: urllib читает socks proxy из registry/env даже после os.environ cleanup)
import urllib.request as _e061_urllib
_original_getproxies = _e061_urllib.getproxies
_e061_urllib.getproxies = lambda: {}

# Also patch build_opener as defense-in-depth
_orig_e061_build_opener = _e061_urllib.build_opener

def _e061_proxy_free_opener(*handlers):
    import urllib.request as _ur
    return _orig_e061_build_opener(*[_h for _h in handlers
                                       if not isinstance(_h, (_ur.ProxyHandler,))])

_e061_urllib.build_opener = _e061_proxy_free_opener
try:
    _e061_urllib.install_opener(_e061_proxy_free_opener())
except Exception:
    pass

import asyncio
import hashlib
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)


# Стандартные размеры моделей faster-whisper
# name: (size_mb, hf_repo)
MODELS = {
    "tiny": (75, "Systran/faster-whisper-tiny"),
    "base": (140, "Systran/faster-whisper-base"),
    "small": (460, "Systran/faster-whisper-small"),
    "medium": (1500, "Systran/faster-whisper-medium"),
    "large-v2": (3000, "Systran/faster-whisper-large-v2"),
    "large-v3": (3100, "Systran/faster-whisper-large-v3"),
    # distil variants (English-only, smaller, faster)
    "distil-small-en": (310, "Systran/faster-distil-whisper-small.en"),
    "distil-medium-en": (780, "Systran/faster-distil-whisper-medium.en"),
    "distil-large-v3": (1500, "Systran/faster-distil-whisper-large-v3"),
}


@dataclass
class ModelInfo:
    """Information about a Whisper model."""
    name: str
    size_mb: int
    repo: str
    downloaded: bool = False
    path: str | None = None
    size_on_disk_mb: float | None = None
    last_checked: float = field(default_factory=time.time)


@dataclass
class DownloadProgress:
    """Current download progress.

    IMPORTANT (E075):
    - _last_instant_speed and _last_instant_time MUST be declared as fields
      so they survive asdict() serialization and dataclass copying.
    - started_at is initialized to 0.0 (NOT time.time()) so we can detect
      "first real byte" and set it correctly.
    """
    model_name: str
    total_bytes: int = 0
    downloaded_bytes: int = 0
    # E075: started_at = 0.0 — будет установлен при первом реальном байте
    started_at: float = 0.0
    finished_at: float | None = None
    success: bool | None = None
    error: str | None = None

    # E075: Rolling speed tracking — declared as FIELDS for stability
    _last_instant_speed: float = field(default=0.0, repr=False, compare=False)
    _last_instant_time: float = field(default=0.0, repr=False, compare=False)

    @property
    def percent(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return min(100.0, (self.downloaded_bytes / self.total_bytes) * 100)

    @property
    def elapsed_sec(self) -> float:
        """Time elapsed since download actually started.

        Returns 0 if download hasn't started yet (started_at == 0).
        This prevents negative speed values before first byte.
        """
        if self.started_at == 0:
            return 0.0
        end = self.finished_at or time.time()
        return end - self.started_at

    @property
    def speed_mbps(self) -> float:
        """Calculate download speed in MB/s.

        Uses rolling average from polling (E074/E075) if available.
        Falls back to overall average.
        """
        # Prefer rolling speed (more accurate)
        if self._last_instant_speed > 0.01:
            return self._last_instant_speed
        # Fallback: overall average
        if self.elapsed_sec <= 0:
            return 0.0
        return (self.downloaded_bytes / 1024 / 1024) / self.elapsed_sec

    def calculate_eta_sec(self) -> float:
        """Calculate estimated time remaining (seconds)."""
        speed = self.speed_mbps
        if speed <= 0.001 or self.total_bytes == 0:
            return 0.0
        remaining_bytes = max(0, self.total_bytes - self.downloaded_bytes)
        remaining_mb = remaining_bytes / 1024 / 1024
        return remaining_mb / speed

    def to_dict(self) -> dict:
        """Serialize to dict."""
        # E071: Force total_bytes from MODELS if 0
        if self.total_bytes == 0:
            from app.services.whisper_models import MODELS
            if self.model_name in MODELS:
                size_mb, _ = MODELS[self.model_name]
                self.total_bytes = size_mb * 1024 * 1024

        d = asdict(self)
        d["percent"] = self.percent
        d["elapsed_sec"] = self.elapsed_sec
        d["speed_mbps"] = self.speed_mbps
        d["eta_sec"] = self.calculate_eta_sec()
        return d
class WhisperModelManager:
    """Manage Whisper model downloads and caching."""

    def __init__(self, cache_dir: Path | None = None):
        """Initialize with custom or default cache directory."""
        self.cache_dir = cache_dir or self._default_cache_dir()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._downloads: dict[str, DownloadProgress] = {}
        logger.info("whisper_manager_initialized", cache_dir=str(self.cache_dir))

    @staticmethod
    def _default_cache_dir() -> Path:
        """Get default cache directory based on settings."""
        hf_cache = os.environ.get("HF_HUB_CACHE")
        if hf_cache:
            return Path(hf_cache)

        # Default: ~/.cache/huggingface/hub on Linux/Mac, %LOCALAPPDATA% on Win
        if os.name == "nt":
            base = os.environ.get("LOCALAPPDATA") or os.environ.get("USERPROFILE")
            if base:
                return Path(base) / ".cache" / "huggingface" / "hub"
        else:
            home = os.environ.get("HOME", "/tmp")
            return Path(home) / ".cache" / "huggingface" / "hub"

        return Path("/tmp") / "huggingface" / "hub"

    def get_models(self) -> list[ModelInfo]:
        """List all models with their download status."""
        results = []
        for name, (size_mb, repo) in MODELS.items():
            path, on_disk = self._find_cached_model(name)
            results.append(
                ModelInfo(
                    name=name,
                    size_mb=size_mb,
                    repo=repo,
                    downloaded=on_disk > 0,
                    path=str(path) if path else None,
                    size_on_disk_mb=round(on_disk / 1024 / 1024, 1) if on_disk > 0 else None,
                )
            )
        return results

    def get_active_model(self) -> str:
        """Get currently configured model from settings."""
        return settings.whisper_model

    def get_model_info(self, name: str) -> ModelInfo | None:
        """Get info for specific model."""
        if name not in MODELS:
            return None
        size_mb, repo = MODELS[name]
        path, on_disk = self._find_cached_model(name)
        return ModelInfo(
            name=name,
            size_mb=size_mb,
            repo=repo,
            downloaded=on_disk > 0,
            path=str(path) if path else None,
            size_on_disk_mb=round(on_disk / 1024 / 1024, 1) if on_disk > 0 else None,
        )

    def _find_cached_model(self, name: str) -> tuple[Path | None, int]:
        """Find cached model files. Returns (path, size_bytes)."""
        # HuggingFace cache structure: models--{org}--{model}/snapshots/{hash}/
        repo = MODELS.get(name, (None, ""))[1]
        if not repo:
            return None, 0

        repo_cache_name = "models--" + repo.replace("/", "--")
        repo_dir = self.cache_dir / repo_cache_name

        if not repo_dir.exists():
            return None, 0

        # Find snapshot directory
        snapshots_dir = repo_dir / "snapshots"
        if not snapshots_dir.exists():
            return None, 0

        snapshots = list(snapshots_dir.iterdir())
        if not snapshots:
            return None, 0

        # Take latest snapshot
        latest_snapshot = sorted(snapshots)[-1]

        # Compute total size
        total = 0
        for f in latest_snapshot.rglob("*"):
            if f.is_file():
                total += f.stat().st_size

        return latest_snapshot, total

    def is_downloaded(self, name: str) -> bool:
        """Check if model is fully downloaded."""
        _, size = self._find_cached_model(name)
        if name not in MODELS:
            return False
        expected_size = MODELS[name][0] * 1024 * 1024
        # Allow 10% variance (compression differences)
        return size > expected_size * 0.9

    async def download_model(
        self,
        name: str,
        progress_callback: Callable[[DownloadProgress], None] | None = None,
    ) -> DownloadProgress:
        """Download model with progress tracking.

        Args:
            name: Model name (e.g., 'tiny', 'large-v3')
            progress_callback: Optional callback for progress updates
        """
        if name not in MODELS:
            progress = DownloadProgress(
                model_name=name,
                success=False,
                error=f"Unknown model: {name}. Available: {list(MODELS.keys())}",
                finished_at=time.time(),
            )
            self._downloads[name] = progress
            return progress

        # E061: Proxy already disabled at module import (top of file)
        # Just create progress and call impl
        progress = DownloadProgress(model_name=name)
        self._downloads[name] = progress

        return await self._download_model_impl(name, progress, progress_callback)

    async def _download_model_impl(
        self, name: str, progress: DownloadProgress,
        progress_callback: Callable[[DownloadProgress], None] | None = None,
    ) -> DownloadProgress:
        """Internal: actually perform the download (called by download_model wrapper)."""
        self._downloads[name] = progress
        log_callback = progress_callback or (lambda p: None)

        try:
            size_mb, repo = MODELS[name]
            logger.info("whisper_download_started", model=name, repo=repo, size_mb=size_mb)

            # E061: urllib.request.getproxies() reads socks proxy even after
            # os.environ cleanup (Windows registry). Monkey-patch is MANDATORY.
            import urllib.request
            _original_getproxies = urllib.request.getproxies
            urllib.request.getproxies = lambda: {}

            # hf_transfer uses its own HTTP client and ignores proxies={}
            # in snapshot_download — disable via env
            os.environ["HF_HUB_DISABLE_HF_TRANSFER"] = "1"
            os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

            try:
                # E061d: Use set_client_factory to create httpx.Client WITHOUT proxy
                # (proxies={} in snapshot_download is IGNORED, see huggingface_hub warning)
                # Solution: override _GLOBAL_CLIENT_FACTORY with one that uses trust_env=False
                import httpx
                from huggingface_hub import snapshot_download
                from huggingface_hub.utils import _http as _hf_http
                from huggingface_hub.utils import tqdm as hf_tqdm

                # Save original factory (use getattr for compat with old hf_hub)
                _orig_client_factory = getattr(
                    _hf_http, "_GLOBAL_CLIENT_FACTORY", None
                )

                # Proxy-free factory: trust_env=False tells httpx to NOT read env vars
                def _proxy_free_factory() -> httpx.Client:
                    return httpx.Client(
                        follow_redirects=True,
                        timeout=httpx.Timeout(30.0),
                        trust_env=False,  # ← KEY: do not use env vars for proxy
                    )

                # Install our factory - safely (handle old hf_hub versions)
                if _orig_client_factory is not None:
                    _hf_http._GLOBAL_CLIENT_FACTORY = _proxy_free_factory
                # Always try to reset cached client
                if hasattr(_hf_http, "_GLOBAL_CLIENT"):
                    _hf_http._GLOBAL_CLIENT = None
                logger.info(
                    "hf_client_factory_proxy_free_installed",
                    has_factory=_orig_client_factory is not None,
                )

                # Fallback: if _GLOBAL_CLIENT_FACTORY doesn't exist (old hf_hub),
                # try set_client_factory (which is always available)
                if _orig_client_factory is None:
                    try:
                        from huggingface_hub import set_client_factory
                        set_client_factory(_proxy_free_factory)
                        logger.info("hf_set_client_factory_used")
                    except Exception as sf_err:
                        logger.warning("set_client_factory_failed", error=str(sf_err))

                # Custom tqdm - just disable visual output
                # (polling handles progress updates separately)
                class ProgressTqdm(hf_tqdm):
                    """Track download progress and update progress object.

                    Multiple hooks (update, refresh, close) ensure we catch
                    progress at any stage of download.
                    """

                    def _safe_update(self):
                        """Update progress from current tqdm state."""
                        try:
                            # self.n = current bytes downloaded
                            if hasattr(self, "n") and self.n is not None:
                                # n might be in different units; assume bytes for hf_hub
                                progress.downloaded_bytes = max(
                                    progress.downloaded_bytes,
                                    int(self.n)
                                )
                            # self.total = total expected bytes
                            if hasattr(self, "total") and self.total:
                                progress.total_bytes = max(
                                    progress.total_bytes, int(self.total)
                                )
                        except (TypeError, ValueError):
                            pass

                    def update(self, n: int = 1):
                        super().update(n)
                        self._safe_update()

                    def refresh(self, *args, **kwargs):
                        # Called by hf_hub periodically
                        super().refresh(*args, **kwargs)
                        self._safe_update()

                    def close(self, *args, **kwargs):
                        # Called when download finishes
                        self._safe_update()
                        # Final state
                        if progress.total_bytes and progress.downloaded_bytes:
                            progress.downloaded_bytes = max(
                                progress.downloaded_bytes, progress.total_bytes
                            )
                        super().close(*args, **kwargs)

                    def __init__(self, *args, **kwargs):
                        kwargs.setdefault("disable", True)
                        # Capture initial total from kwargs (passed by hf_hub)
                        if "total" in kwargs and kwargs["total"]:
                            progress.total_bytes = max(
                                progress.total_bytes, int(kwargs["total"])
                            )
                        super().__init__(*args, **kwargs)
                        self._safe_update()

                # Download in background thread
                _stop_polling = asyncio.Event()

                async def _poll_cache_size():
                    """Poll cache directory size while download runs.

                    Sum ALL files in ALL snapshots (not just one).
                    Track rolling average speed for accurate display.
                    """
                    expected_total = size_mb * 1024 * 1024
                    progress.total_bytes = expected_total

                    # Track for rolling average speed calculation
                    last_bytes = 0
                    last_time = time.time()
                    poll_count = 0

                    while not _stop_polling.is_set():
                        try:
                            repo_cache_name = "models--" + repo.replace("/", "--")
                            repo_dir = self.cache_dir / repo_cache_name
                            if repo_dir.exists():
                                # Sum size of ALL files in ALL snapshots + blobs
                                total_size = 0
                                found_files = []
                                for f in repo_dir.rglob("*"):
                                    if f.is_file():
                                        # Skip lock files
                                        if f.name.endswith(".lock"):
                                            continue
                                        try:
                                            total_size += f.stat().st_size
                                            found_files.append(f.name)
                                        except (OSError, FileNotFoundError):
                                            # File might be in progress
                                            pass

                                if total_size > 0:
                                    progress.downloaded_bytes = max(
                                        progress.downloaded_bytes,
                                        total_size
                                    )
                                    progress.total_bytes = expected_total

                                    # E074: Set started_at on first real data
                                    if progress.started_at == 0:
                                        progress.started_at = time.time()

                                    # E074: Calculate rolling speed
                                    # Average over last few polls for stability
                                    now = time.time()
                                    poll_count += 1

                                    # E074: Calculate BOTH rolling and overall speed
                                    # Set started_at on FIRST real data
                                    if progress.started_at == 0 or progress.downloaded_bytes == 0:
                                        # Will be set when we have real data
                                        pass

                                    if poll_count >= 2 and last_bytes > 0:
                                        # Delta speed over this poll interval
                                        elapsed_since_last = now - last_time
                                        if elapsed_since_last > 0:
                                            bytes_delta = total_size - last_bytes

                                            # ALWAYS set rolling speed (even if bytes_delta is small)
                                            # Use overall speed as fallback
                                            overall_elapsed = now - progress.started_at if progress.started_at > 0 else 1
                                            if overall_elapsed > 0:
                                                overall_speed = (total_size / 1024 / 1024) / overall_elapsed
                                            else:
                                                overall_speed = 0

                                            if bytes_delta > 0:
                                                # Instant speed from this delta
                                                instant_speed = bytes_delta / elapsed_since_last / 1024 / 1024
                                                prev_speed = getattr(progress, '_last_instant_speed', instant_speed)
                                                # Smooth: 70% instant + 30% previous
                                                smooth_speed = 0.7 * instant_speed + 0.3 * prev_speed
                                            else:
                                                # No new bytes - use overall as fallback
                                                smooth_speed = overall_speed

                                            progress._last_instant_speed = max(smooth_speed, overall_speed * 0.5)
                                            progress._last_instant_time = now

                                    last_bytes = total_size
                                    last_time = now

                                    logger.info(
                                        "download_progress",
                                        model=name,
                                        downloaded=progress.downloaded_bytes,
                                        total=progress.total_bytes,
                                        percent=progress.percent,
                                        files=found_files[:5],
                                    )
                        except Exception as poll_err:
                            logger.debug("poll_err", error=str(poll_err))
                        await asyncio.sleep(0.5)  # poll every 500ms

                def _do_download():
                    return snapshot_download(
                        repo_id=repo,
                        cache_dir=str(self.cache_dir),
                        tqdm_class=ProgressTqdm,
                        local_files_only=False,
                        # proxies={} IGNORED — use set_client_factory instead
                    )

                # Start polling task and download in parallel
                poll_task = asyncio.create_task(_poll_cache_size())
                try:
                    path = await asyncio.to_thread(_do_download)
                finally:
                    _stop_polling.set()
                    await poll_task
                progress.finished_at = time.time()
                progress.success = True
                progress.downloaded_bytes = progress.total_bytes
                logger.info(
                    "whisper_download_completed",
                    model=name,
                    path=str(path),
                    elapsed_sec=progress.elapsed_sec,
                )
            finally:
                # Restore original client factory + getproxies
                # Use hasattr/getattr for compatibility with old hf_hub
                if "_orig_client_factory" in dir() and _orig_client_factory is not None:
                    try:
                        _hf_http._GLOBAL_CLIENT_FACTORY = _orig_client_factory
                    except AttributeError:
                        pass
                if hasattr(_hf_http, "_GLOBAL_CLIENT"):
                    try:
                        _hf_http._GLOBAL_CLIENT = None
                    except AttributeError:
                        pass
                if "_original_getproxies" in dir():
                    urllib.request.getproxies = _original_getproxies
        except Exception as e:
            progress.finished_at = time.time()
            progress.success = False
            # Include exception type for better diagnosis
            error_msg = f"{type(e).__name__}: {str(e)}"
            progress.error = error_msg[:500]
            logger.exception(
                "whisper_download_failed",
                model=name,
                error=error_msg,
                exc_type=type(e).__name__,
            )

        return progress

    def get_download_progress(self, name: str) -> DownloadProgress | None:
        """Get current download progress for a model."""
        return self._downloads.get(name)

    def delete_model(self, name: str) -> bool:
        """Delete a downloaded model."""
        if name not in MODELS:
            return False

        _, repo = MODELS[name]
        repo_cache_name = "models--" + repo.replace("/", "--")
        repo_dir = self.cache_dir / repo_cache_name

        if not repo_dir.exists():
            return False

        try:
            shutil.rmtree(repo_dir)
            logger.info("whisper_model_deleted", model=name)
            return True
        except Exception as e:
            logger.error("whisper_model_delete_failed", model=name, error=str(e))
            return False

    def set_active_model(self, name: str) -> bool:
        """Persist which model should be used (in-memory + .env.user)."""
        if name not in MODELS:
            return False

        # Update in-memory settings
        settings.whisper_model = name
        logger.info("whisper_active_model_changed", model=name)
        return True


# Singleton
model_manager = WhisperModelManager()

# Public list of model names
AVAILABLE_MODELS = sorted(list(MODELS.keys()))
