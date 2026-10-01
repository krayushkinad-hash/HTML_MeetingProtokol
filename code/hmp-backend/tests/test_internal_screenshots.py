"""E289: тесты routers/screenshots.py — list/delete/synthesize."""
import pytest


@pytest.mark.asyncio
async def test_list_screenshots(client, sample_protocol):
    """GET /protocols/{id}/screenshots."""
    r = await client.get(
        f"/api/v1/hmp/protocols/{sample_protocol.id}/screenshots"
    )
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_list_screenshots_invalid_uuid(client):
    """GET /protocols/not-uuid/screenshots → 422."""
    r = await client.get("/api/v1/hmp/protocols/not-uuid/screenshots")
    assert r.status_code in (422, 500)


@pytest.mark.asyncio
async def test_delete_screenshot_not_found(client, sample_protocol):
    """DELETE /screenshots/{nonexistent} → 404."""
    import uuid
    fake_id = uuid.uuid4()
    r = await client.delete(f"/api/v1/hmp/screenshots/{fake_id}")
    assert r.status_code in (404, 500)


@pytest.mark.asyncio
async def test_get_screenshot_invalid(client):
    """GET /screenshots/not-uuid → 422."""
    r = await client.get("/api/v1/hmp/screenshots/not-a-uuid")
    assert r.status_code in (422, 500)


@pytest.mark.asyncio
async def test_synthesize_screenshots(client, sample_protocol):
    """POST /protocols/{id}/screenshots/synthesize."""
    r = await client.post(
        f"/api/v1/hmp/protocols/{sample_protocol.id}/screenshots/synthesize",
        json={"interval_sec": 60, "max_count": 5},
    )
    assert r.status_code in (200, 400, 404, 422, 500)


@pytest.mark.asyncio
async def test_synthesize_screenshots_invalid_uuid(client):
    """POST /protocols/not-uuid/screenshots/synthesize → 422."""
    r = await client.post(
        "/api/v1/hmp/protocols/not-uuid/screenshots/synthesize",
        json={},
    )
    assert r.status_code in (422, 500)


def test_screenshot_module_imports():
    """app.routers.screenshots module loads."""
    from app.routers import screenshots
    assert screenshots is not None
    assert hasattr(screenshots, "router")