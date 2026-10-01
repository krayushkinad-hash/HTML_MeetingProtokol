"""Transcription router package.

Re-exports ``router`` (composed from :mod:`local`, :mod:`progress`,
:mod:`remote`, :mod:`upgrade`) so existing imports
``from app.routers import transcribe; transcribe.router`` keep working.

The original 1347-line ``transcribe.py`` file was split in 2026-09 into four
focused modules to improve readability and onboarding speed:

  * :mod:`local`    — queueing, status, pause, resume, cancel, health
  * :mod:`progress` — progress tracking helpers + progress endpoints
  * :mod:`remote`   — remote-Whisper proxy endpoints (``/remote``,
                      ``/remote/test-upload``)
  * :mod:`upgrade`  — weak-segment upgrade endpoint (US-086)

No behaviour was changed — every existing path remains available.
"""
from fastapi import APIRouter

from . import local, progress, remote, upgrade

router = APIRouter()

# Compose all sub-routers under the same parent. Each sub-module already
# declares its full path prefix (``/transcribe/...``), so we include them as-is.
router.include_router(local.router)
router.include_router(progress.router)
router.include_router(remote.router)
router.include_router(upgrade.router)


__all__ = ["router", "local", "progress", "remote", "upgrade"]