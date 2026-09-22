"""
HTML_MeetingProtokol Backend - FastAPI Application Entry Point.

Architecture: ADR-001 (FastAPI), ADR-007 (Local Backend).
NFR: QG-1 (privacy), QG-7 (RSS ≤4 GB), QG-12 (152-ФЗ).
"""
from contextlib import asynccontextmanager
from pathlib import Path

import os

# E061: Aggressively disable SOCKS/HTTPS proxy BEFORE any imports
# SOCKS proxy (socks4://) breaks huggingface_hub download
# This runs at module import time, before any service initializes
_proxy_vars = [
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SOCKS_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "socks_proxy",
    "NO_PROXY_BYPASS", "no_proxy_bypass",
]
for _var in _proxy_vars:
    if _var in os.environ:
        del os.environ[_var]

# E061b: Reset httpx cached client if it already exists
# (huggingface_hub creates httpx.Client at import time)
import sys
print("[main.py] E061: proxy env vars cleared", file=sys.stderr)
try:
    # If huggingface_hub was already imported, reset its cached client
    from huggingface_hub.utils import _http as _hf_http_mod
    if hasattr(_hf_http_mod, "_GLOBAL_CLIENT"):
        _hf_http_mod._GLOBAL_CLIENT = None
        print("[main.py] E061b: reset huggingface_hub cached client", file=sys.stderr)
except ImportError:
    # Not imported yet — will use clean env on first import
    pass

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.logging_config import configure_logging, get_logger
from app.core.monitoring import RSSMonitor
from app.core.middleware import CorrelationIdMiddleware, ProblemDetailsMiddleware
from app.db.session import init_db, close_db
from app.routers import (
    actions,
    ai,
    audio,
    bot,
    calendar,
    decisions,
    dictionary,
    diarize,
    export,
    folders,
    health,
    live,
    protocols,
    screenshots,
    search,
    speakers,
    summary,
    tags,
    transcribe,
    user_setting,
    utterances,
    admin,
    whisper_models,
)

# Initialize structured logging (NFR §9.3)
configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup + shutdown hooks."""
    logger.info("startup", env=settings.app_env, version=settings.app_version)

    # Initialize database
    await init_db()

    # Start RSS monitor (NFR §QG-7)
    rss_monitor = RSSMonitor(limit_mb=settings.rss_limit_mb)
    await rss_monitor.start()
    app.state.rss_monitor = rss_monitor

    logger.info("ready", rss_limit_mb=settings.rss_limit_mb)

    yield

    # Shutdown
    logger.info("shutdown")
    await rss_monitor.stop()
    await close_db()


def create_app() -> FastAPI:
    """Application factory."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Backend API for HTML_MeetingProtokol - local meeting protocols",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
        default_response_class=ORJSONResponse,  # Faster than stdlib json
        lifespan=lifespan,
    )

    # CORS middleware (NFR §14.6) - MUST be first for preflight to work
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    # Custom middleware (NFR §5.9 correlation IDs, RFC 7807)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(ProblemDetailsMiddleware)

    # Force CORS middleware - adds headers to ALL responses (NFR §14.6)
    @app.middleware("http")
    async def force_cors_headers(request: Request, call_next):
        # Handle preflight OPTIONS requests
        if request.method == "OPTIONS":
            from fastapi.responses import Response
            response = Response()
            origin = request.headers.get("origin", "*")
            response.headers["Access-Control-Allow-Origin"] = origin if origin else "*"
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "*"
            response.headers["Access-Control-Allow-Headers"] = "*"
            response.headers["Access-Control-Max-Age"] = "3600"
            return response

        response = await call_next(request)

        # Convert 404 or 204 on GET requests to null/empty (so frontend doesn't break)
        if response.status_code in (404, 204) and request.method == "GET":
            from fastapi.responses import JSONResponse
            path = request.url.path
            list_endpoints = [
                "/utterances", "/speakers", "/tags", "/decisions",
                "/action-items", "/screenshots", "/dictionary",
                "/protocols", "/bot/users", "/bot/sessions",
                "/transcribe", "/diarize", "/calendar"
            ]
            is_list = (
                any(path.endswith(ep) or path.endswith(ep + "/") for ep in list_endpoints)
                or "search" in path
                or "calendar" in path
            )
            return JSONResponse(
                status_code=200,
                content=[] if is_list else None,
                headers={
                    "Access-Control-Allow-Origin": request.headers.get("origin", "*"),
                    "Access-Control-Allow-Credentials": "true",
                }
            )

        # Add CORS headers to every response
        origin = request.headers.get("origin", "*")
        response.headers["Access-Control-Allow-Origin"] = origin if origin else "*"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        response.headers["Access-Control-Expose-Headers"] = "*"
        return response

    # Mount static files (for video streaming - NFR §3.3)
    static_path = Path(settings.protocols_dir).expanduser()
    static_path.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(static_path)), name="media")

    # Include routers (organized by domain - ADR §5.1)
    api_prefix = settings.api_prefix
    app.include_router(health.router, tags=["Health"])
    app.include_router(protocols.router, prefix=api_prefix, tags=["Protocols"])
    app.include_router(audio.router, prefix=api_prefix, tags=["Audio Files"])
    app.include_router(transcribe.router, prefix=api_prefix, tags=["Transcription"])
    app.include_router(diarize.router, prefix=api_prefix, tags=["Diarization"])
    app.include_router(utterances.router, prefix=api_prefix, tags=["Utterances"])
    app.include_router(speakers.router, prefix=api_prefix, tags=["Speakers"])
    app.include_router(calendar.router, prefix=api_prefix, tags=["Calendar"])
    app.include_router(search.router, prefix=api_prefix, tags=["Search"])
    app.include_router(actions.router, prefix=api_prefix, tags=["Action Items"])
    app.include_router(decisions.router, prefix=api_prefix, tags=["Decisions"])
    app.include_router(tags.router, prefix=api_prefix, tags=["Tags"])
    app.include_router(screenshots.router, prefix=api_prefix, tags=["Screenshots"])
    app.include_router(summary.router, prefix=api_prefix, tags=["Summary"])
    app.include_router(ai.router, prefix=api_prefix, tags=["AI"])
    app.include_router(export.router, prefix=api_prefix, tags=["Export"])
    app.include_router(dictionary.router, prefix=api_prefix, tags=["Dictionary"])
    app.include_router(user_setting.router, prefix=api_prefix, tags=["User Settings"])
    app.include_router(live.router, prefix=api_prefix, tags=["Live Mode"])
    app.include_router(bot.router, prefix=api_prefix, tags=["Telegram Bot"])
    app.include_router(folders.router, prefix=api_prefix, tags=["Folders"])
    app.include_router(admin.router, prefix=api_prefix, tags=["Admin"])
    app.include_router(whisper_models.router, prefix=api_prefix, tags=["Whisper"])

    return app


# Create the app instance
app = create_app()


def run() -> None:
    """Run uvicorn (for `hmp-backend` script)."""
    uvicorn.run(
        "app.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        workers=settings.backend_workers,  # ADR-009: 1 worker
        reload=settings.debug,
        log_config=None,  # Use structlog
    )


if __name__ == "__main__":
    run()
