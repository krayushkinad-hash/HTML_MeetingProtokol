"""Whisper Model Management API (US-058).

Endpoints:
- GET    /whisper/models                    — list all models
- GET    /whisper/active                    — current active model
- POST   /whisper/active/{name}            — change active model
- POST   /whisper/download/{name}           — start download (returns task_id)
- GET    /whisper/progress/{name}           — current download status
- GET    /whisper/status/{name}             — is model cached?
- DELETE /whisper/models/{name}            — remove model from cache
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path as PathParam, status
from pydantic import BaseModel

from app.core.logging_config import get_logger
from app.services.whisper_models import (
    AVAILABLE_MODELS,
    DownloadProgress,
    model_manager,
)
from app.services.whisper_models import ModelInfo

logger = get_logger(__name__)
router = APIRouter(prefix="/whisper", tags=["whisper"])


class ModelsResponse(BaseModel):
    models: list[ModelInfo]
    active: str
    cache_dir: str
    available: list[str]


class ModelInfoResponse(BaseModel):
    info: ModelInfo


class DownloadResponse(BaseModel):
    """Response when download starts."""
    model: str
    status: str
    message: str
    info: ModelInfo | None = None


class DeleteResponse(BaseModel):
    deleted: bool
    model: str


class ActiveModelResponse(BaseModel):
    active: str


class ModelStatusResponse(BaseModel):
    model: str
    downloaded: bool
    expected_size_mb: int | None
    size_mb: float | None
    path: str | None = None


def _validate_model_name(name: str) -> str:
    if name not in AVAILABLE_MODELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown model: {name}. Available: {AVAILABLE_MODELS}",
        )
    return name


@router.get("/models", response_model=ModelsResponse, summary="List all Whisper models")
async def list_models() -> ModelsResponse:
    """List all available Whisper models with download status."""
    models = model_manager.get_models()
    return ModelsResponse(
        models=models,
        active=model_manager.get_active_model(),
        cache_dir=str(model_manager.cache_dir),
        available=list(AVAILABLE_MODELS),
    )


@router.get("/models/{name}", response_model=ModelInfoResponse)
async def get_model_info(
    name: Annotated[str, PathParam(description="Model name")]
) -> ModelInfoResponse:
    """Get detailed info for a specific model."""
    _validate_model_name(name)
    info = model_manager.get_model_info(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Model not found: {name}")
    return ModelInfoResponse(info=info)




@router.get(
    "/debug/proxy",
    summary="Debug endpoint — show current proxy state (E061)",
)
async def debug_proxy() -> dict:
    """Show current proxy env vars to diagnose SOCKS/HTTP issues."""
    import os
    return {
        "HTTP_PROXY": os.environ.get("HTTP_PROXY"),
        "HTTPS_PROXY": os.environ.get("HTTPS_PROXY"),
        "ALL_PROXY": os.environ.get("ALL_PROXY"),
        "SOCKS_PROXY": os.environ.get("SOCKS_PROXY"),
        "http_proxy": os.environ.get("http_proxy"),
        "https_proxy": os.environ.get("https_proxy"),
        "all_proxy": os.environ.get("all_proxy"),
        "socks_proxy": os.environ.get("socks_proxy"),
        "HF_HUB_DISABLE_PROGRESS_BARS": os.environ.get("HF_HUB_DISABLE_PROGRESS_BARS"),
        "HTTPX_DISABLE_PROXY": os.environ.get("HTTPX_DISABLE_PROXY"),
    }

@router.get("/active", response_model=ActiveModelResponse)
async def get_active() -> ActiveModelResponse:
    """Get currently configured active model."""
    return ActiveModelResponse(active=model_manager.get_active_model())


@router.post("/active/{name}", response_model=ActiveModelResponse)
async def set_active(
    name: Annotated[str, PathParam(description="Model name")]
) -> ActiveModelResponse:
    """Set which model should be used by transcription service.

    Affects new transcriptions only (does not re-download model).
    """
    _validate_model_name(name)
    ok = model_manager.set_active_model(name)
    if not ok:
        raise HTTPException(status_code=500, detail=f"Failed to set: {name}")
    return ActiveModelResponse(active=name)


@router.post(
    "/download/{name}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DownloadResponse,
    summary="Download Whisper model (background task)",
)
async def download_model(
    name: Annotated[str, PathParam(description="Model name")]
) -> DownloadResponse:
    """Start downloading a model. Poll /whisper/progress/{name} for status.

    The download runs in background. Returns immediately.
    """
    _validate_model_name(name)

    # Already downloaded?
    if model_manager.is_downloaded(name):
        info = model_manager.get_model_info(name)
        return DownloadResponse(
            model=name,
            status="already_downloaded",
            message="Model already in cache. No download needed.",
            info=info,
        )

    # Start download in background (fire-and-forget asyncio task)
    async def _download_task():
        progress = await model_manager.download_model(name)
        if progress.success:
            logger.info("model_downloaded", model=name)
        else:
            logger.error("model_download_failed", model=name, error=progress.error)

    # Use asyncio.create_task to start background download
    asyncio.create_task(_download_task())

    info = model_manager.get_model_info(name)
    return DownloadResponse(
        model=name,
        status="downloading",
        message=f"Download started. Poll /whisper/progress/{name} for status.",
        info=info,
    )


@router.get(
    "/progress/{name}",
    response_model=dict,  # E076: must be dict, not DownloadProgress (Pydantic strips @property)
    summary="Get download progress for a model",
)
async def get_progress(
    name: Annotated[str, PathParam(description="Model name")]
) -> dict:
    """Get current download progress.

    Returns dict with:
    - model_name
    - total_bytes / downloaded_bytes
    - percent (0-100)
    - speed_mbps (MB/s)
    - elapsed_sec (seconds)
    - eta_sec (seconds)
    - success (None if still running)
    - error (message if failed)
    """
    _validate_model_name(name)
    progress = model_manager.get_download_progress(name)

    if progress is None:
        # Never started
        info = model_manager.get_model_info(name)
        if info and info.downloaded:
            # Already done
            done_progress = DownloadProgress(
                model_name=name,
                total_bytes=int((info.size_on_disk_mb or 0) * 1024 * 1024),
                downloaded_bytes=int((info.size_on_disk_mb or 0) * 1024 * 1024),
                finished_at=info.last_checked,
                success=True,
            )
            return done_progress.to_dict()
        # Not started
        not_started = DownloadProgress(
            model_name=name,
            success=None,
            downloaded_bytes=0,
            total_bytes=0,
        )
        return not_started.to_dict()

    # E076: must call to_dict() explicitly so Pydantic includes @property values
    return progress.to_dict()


@router.get("/status/{name}", response_model=ModelStatusResponse)
async def get_status(
    name: Annotated[str, PathParam(description="Model name")]
) -> ModelStatusResponse:
    """Check whether a model is downloaded + size on disk."""
    _validate_model_name(name)
    info = model_manager.get_model_info(name)
    downloaded = model_manager.is_downloaded(name)
    return ModelStatusResponse(
        model=name,
        downloaded=downloaded,
        expected_size_mb=info.size_mb if info else None,
        size_mb=info.size_on_disk_mb if info and info.size_on_disk_mb else 0.0,
        path=info.path if info else None,
    )


@router.delete("/models/{name}", response_model=DeleteResponse)
async def delete_model(
    name: Annotated[str, PathParam(description="Model name")]
) -> DeleteResponse:
    """Remove downloaded model from cache (frees disk space)."""
    _validate_model_name(name)
    ok = model_manager.delete_model(name)
    return DeleteResponse(deleted=ok, model=name)
