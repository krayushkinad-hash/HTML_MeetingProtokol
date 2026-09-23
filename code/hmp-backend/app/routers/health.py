"""Health check endpoints (NFR §9.5)."""
from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine

router = APIRouter()


@router.get("/health", summary="Simple health check")
async def health() -> dict:
    """Liveness probe."""
    return {
        "status": "ok",
        "version": settings.app_version,
        "env": settings.app_env,
}


@router.get("/health/deep", summary="Deep health check")
async def health_deep() -> dict:
    """Check DB + models + disk + RSS."""
    components = {}

    # Database
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        components["database"] = {"status": "ok"}
    except Exception as e:
        components["database"] = {"status": "error", "error": str(e)}

    # Disk
    import psutil
    disk = psutil.disk_usage("/")
    components["disk"] = {
        "status": "ok",
        "free_mb": disk.free // (1024 * 1024),
    }

    # RSS
    process = psutil.Process()
    rss_mb = process.memory_info().rss / (1024 * 1024)
    components["rss"] = {"status": "ok", "rss_mb": round(rss_mb, 1)}

    # Overall
    overall = "ok" if all(c["status"] == "ok" for c in components.values()) else "degraded"

    return {
        "status": overall,
        "components": components,
        "version": settings.app_version,
    }
