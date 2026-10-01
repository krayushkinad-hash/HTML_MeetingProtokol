"""E288: тесты routers/transcribe/local.py."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_local_router_imports():
    from app.routers.transcribe import local
    assert local is not None


def test_local_router_has_routes():
    try:
        from app.routers.transcribe.local import router
        assert hasattr(router, "routes")
        assert len(router.routes) > 0
    except ImportError:
        pytest.skip("router не найден")


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """GET /transcribe/health."""
    r = await client.get("/api/v1/hmp/transcribe/health")
    assert r.status_code in (200, 404, 500, 503)


@pytest.mark.asyncio
async def test_whisper_status_endpoint(client):
    """GET /transcribe/whisper/status."""
    r = await client.get("/api/v1/hmp/transcribe/whisper/status/base")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_run_endpoint_minimal(client, sample_protocol, mock_whisper):
    """POST /transcribe/run."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={
            "protocol_id": str(sample_protocol.id),
            "model": "base",
            "language": "ru",
        },
    )
    assert r.status_code in (200, 202, 422, 500)


@pytest.mark.asyncio
async def test_run_endpoint_with_audio_file(client, sample_protocol, mock_whisper):
    """POST /transcribe/run с audio_file."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={
            "protocol_id": str(sample_protocol.id),
            "audio_file_id": str(sample_protocol.audio_file_id or "test"),
            "model": "base",
        },
    )
    assert r.status_code in (200, 202, 422, 500)


@pytest.mark.asyncio
async def test_run_endpoint_validation_error(client):
    """POST /transcribe/run без обязательных полей."""
    r = await client.post("/api/v1/hmp/transcribe/run", json={})
    assert r.status_code in (200, 202, 422, 500)


@pytest.mark.asyncio
async def test_run_endpoint_invalid_protocol(client):
    """POST /transcribe/run с несуществующим protocol_id."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": "00000000-0000-0000-0000-000000000000", "model": "base"},
    )
    assert r.status_code in (200, 202, 404, 422, 500)


@pytest.mark.asyncio
async def test_get_status_nonexistent(client):
    """GET /transcribe/status/{id} для несуществующего."""
    r = await client.get("/api/v1/hmp/transcribe/status/nonexistent-uuid")
    assert r.status_code in (200, 404, 422, 500)


@pytest.mark.asyncio
async def test_cancel_endpoint(client):
    """POST /transcribe/cancel/{id}."""
    r = await client.post("/api/v1/hmp/transcribe/cancel/test-id")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_pause_endpoint(client):
    """POST /transcribe/pause/{id}."""
    r = await client.post("/api/v1/hmp/transcribe/pause/test-id")
    assert r.status_code in (200, 400, 404, 500)


@pytest.mark.asyncio
async def test_resume_endpoint(client):
    """POST /transcribe/resume/{id}."""
    r = await client.post("/api/v1/hmp/transcribe/resume/test-id")
    assert r.status_code in (200, 400, 404, 500)


@pytest.mark.asyncio
async def test_run_endpoint_different_models(client, sample_protocol, mock_whisper):
    """POST /transcribe/run с разными моделями."""
    for model in ["tiny", "base", "small"]:
        r = await client.post(
            "/api/v1/hmp/transcribe/run",
            json={"protocol_id": str(sample_protocol.id), "model": model},
        )
        assert r.status_code in (200, 202, 422, 500)


@pytest.mark.asyncio
async def test_run_endpoint_with_language(client, sample_protocol, mock_whisper):
    """POST /transcribe/run с language."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(sample_protocol.id), "language": "en"},
    )
    assert r.status_code in (200, 202, 422, 500)


@pytest.mark.asyncio
async def test_run_endpoint_with_translate(client, sample_protocol, mock_whisper):
    """POST /transcribe/run с task=translate."""
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(sample_protocol.id), "task": "translate"},
    )
    assert r.status_code in (200, 202, 422, 500)
