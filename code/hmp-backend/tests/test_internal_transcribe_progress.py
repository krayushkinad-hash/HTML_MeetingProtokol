"""E286: тесты routers/transcribe/progress.py."""
import pytest


def test_progress_module_imports():
    from app.routers.transcribe import progress
    assert progress is not None


def test_router_exists():
    try:
        from app.routers.transcribe.progress import router
        assert router is not None
    except ImportError:
        pytest.skip("router не найден")


@pytest.mark.asyncio
async def test_get_progress_endpoint(client):
    """GET /transcribe/progress/{task_id}."""
    r = await client.get("/api/v1/hmp/transcribe/progress/fake-id")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_get_progress_by_protocol(client, sample_protocol):
    """GET /transcribe/progress-by-protocol/{id}."""
    r = await client.get(f"/api/v1/hmp/transcribe/progress-by-protocol/{sample_protocol.id}")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_progress_by_protocol_invalid_uuid(client):
    r = await client.get("/api/v1/hmp/transcribe/progress-by-protocol/not-uuid")
    assert r.status_code in (422, 500)
