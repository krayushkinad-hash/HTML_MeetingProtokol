"""E-new: тесты для app/routers/health.py — цель 70%+ coverage.

Endpoints:
- GET /health      — liveness probe
- GET /health/deep — DB ping + disk + RSS + overall status
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


# ============================================================
# GET /health (liveness probe)
# ============================================================

@pytest.mark.asyncio
async def test_health_ok(client):
    """GET /health → 200 with status/version/env."""
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "env" in body


@pytest.mark.asyncio
async def test_health_version_matches_settings(client):
    """GET /health возвращает реальные значения из settings."""
    from app.core.config import settings

    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == settings.app_version
    assert body["env"] == settings.app_env


@pytest.mark.asyncio
async def test_health_direct():
    """Прямой вызов функции health() без HTTP-стека."""
    from app.routers.health import health

    result = await health()
    assert result["status"] == "ok"
    assert "version" in result
    assert "env" in result


# ============================================================
# GET /health/deep — happy path (DB доступна)
# ============================================================

@pytest.mark.asyncio
async def test_health_deep_ok(client):
    """GET /health/deep → 200 + components {database, disk, rss} + status ok."""
    r = await client.get("/health/deep")
    assert r.status_code == 200
    body = r.json()
    assert "components" in body
    assert "database" in body["components"]
    assert "disk" in body["components"]
    assert "rss" in body["components"]
    assert body["components"]["database"]["status"] == "ok"
    assert body["components"]["disk"]["status"] == "ok"
    assert body["components"]["rss"]["status"] == "ok"
    assert body["status"] == "ok"
    assert "version" in body


@pytest.mark.asyncio
async def test_health_deep_disk_free_mb_is_int(client):
    """disk.free_mb — целое число мегабайт."""
    r = await client.get("/health/deep")
    assert r.status_code == 200
    free_mb = r.json()["components"]["disk"]["free_mb"]
    assert isinstance(free_mb, int)
    assert free_mb >= 0


@pytest.mark.asyncio
async def test_health_deep_rss_mb_is_number(client):
    """rss.rss_mb — float, округлённый до 1 знака."""
    r = await client.get("/health/deep")
    assert r.status_code == 200
    rss = r.json()["components"]["rss"]["rss_mb"]
    assert isinstance(rss, (int, float))
    assert rss > 0


# ============================================================
# GET /health/deep — degraded path (DB недоступна)
# ============================================================

def _make_engine_cm_for_execute(exc: Exception = None, ok: bool = True):
    """Возвращает fake engine c async context manager `begin()`.

    exc: если задан — execute() бросит его (имитация падения БД).
    ok:  если True — execute() вернёт None (имитация успешного SELECT 1).
    """
    fake_conn = MagicMock()
    if exc is not None:
        fake_conn.execute = AsyncMock(side_effect=exc)
    else:
        fake_conn.execute = AsyncMock(return_value=None)

    fake_begin = MagicMock()
    fake_begin.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_begin.__aexit__ = AsyncMock(return_value=None)

    fake_engine = MagicMock()
    fake_engine.begin = MagicMock(return_value=fake_begin)
    return fake_engine


@pytest.mark.asyncio
async def test_health_deep_db_error_returns_degraded(monkeypatch):
    """Если SELECT 1 падает, status=degraded, components.database.status=error."""
    from app.routers import health as health_module
    from app.routers.health import health_deep

    fake_engine = _make_engine_cm_for_execute(exc=RuntimeError("simulated DB outage"))
    monkeypatch.setattr(health_module, "engine", fake_engine)

    result = await health_deep()

    assert result["status"] == "degraded"
    assert result["components"]["database"]["status"] == "error"
    assert "simulated DB outage" in result["components"]["database"]["error"]
    # disk + rss всё равно ok (psutil установлен)
    assert result["components"]["disk"]["status"] == "ok"
    assert result["components"]["rss"]["status"] == "ok"


@pytest.mark.asyncio
async def test_health_deep_db_error_via_http(client, monkeypatch):
    """HTTP-обёртка: GET /health/deep → 200 + status=degraded при сбое БД."""
    from app.routers import health as health_module

    fake_engine = _make_engine_cm_for_execute(exc=ConnectionError("db down"))
    monkeypatch.setattr(health_module, "engine", fake_engine)

    r = await client.get("/health/deep")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["components"]["database"]["status"] == "error"
    assert "db down" in body["components"]["database"]["error"]


# ============================================================
# Прямой вызов health_deep() — happy path (для coverage ветки ok)
# ============================================================

@pytest.mark.asyncio
async def test_health_deep_direct_ok(monkeypatch):
    """Прямой вызов health_deep() с замоканным engine — все компоненты ok."""
    from app.routers import health as health_module
    from app.routers.health import health_deep

    fake_engine = _make_engine_cm_for_execute()
    monkeypatch.setattr(health_module, "engine", fake_engine)

    result = await health_deep()
    assert result["status"] == "ok"
    assert result["components"]["database"]["status"] == "ok"
    assert result["components"]["disk"]["status"] == "ok"
    assert result["components"]["rss"]["status"] == "ok"
    assert "version" in result


# ============================================================
# Защита от падения импорта psutil — спецификация поведения
# ============================================================

@pytest.mark.asyncio
async def test_health_deep_overall_status_logic_with_db_only_ok():
    """Покрытие ветки overall = 'ok' (all components ok) —

    Все компоненты возвращают ok → status='ok'.
    """
    from app.routers import health as health_module
    from app.routers.health import health_deep

    fake_engine = _make_engine_cm_for_execute()
    with patch.object(health_module, "engine", fake_engine):
        result = await health_deep()

    assert result["status"] == "ok"
    assert all(c["status"] == "ok" for c in result["components"].values())


@pytest.mark.asyncio
async def test_health_deep_status_degraded_when_only_db_fails(monkeypatch):
    """Если database упал, а disk+rss ok — overall='degraded'."""
    from app.routers import health as health_module
    from app.routers.health import health_deep

    fake_engine = _make_engine_cm_for_execute(exc=Exception("db boom"))
    monkeypatch.setattr(health_module, "engine", fake_engine)

    result = await health_deep()
    assert result["status"] == "degraded"
    assert result["components"]["database"]["status"] == "error"
    assert result["components"]["disk"]["status"] == "ok"
    assert result["components"]["rss"]["status"] == "ok"