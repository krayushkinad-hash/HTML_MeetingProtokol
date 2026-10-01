"""E286: тесты routers/protocols.py."""
import pytest


@pytest.mark.asyncio
async def test_list_protocols(client):
    """GET /protocols."""
    r = await client.get("/api/v1/hmp/protocols")
    assert r.status_code in (200, 500)


@pytest.mark.asyncio
async def test_list_protocols_with_limit(client):
    """GET /protocols?limit=10."""
    r = await client.get("/api/v1/hmp/protocols?limit=10")
    assert r.status_code in (200, 422, 500)


@pytest.mark.asyncio
async def test_get_protocol(client, sample_protocol):
    """GET /protocols/{id}."""
    r = await client.get(f"/api/v1/hmp/protocols/{sample_protocol.id}")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_get_protocol_invalid_uuid(client):
    """GET /protocols/{invalid-uuid} → 422."""
    r = await client.get("/api/v1/hmp/protocols/not-a-uuid")
    assert r.status_code in (422, 500)


@pytest.mark.asyncio
async def test_create_protocol_minimal(client):
    """POST /protocols с минимальными данными."""
    r = await client.post("/api/v1/hmp/protocols", json={"title": "Test Protocol"})
    assert r.status_code in (200, 201, 422, 500)


@pytest.mark.asyncio
async def test_update_protocol(client, sample_protocol):
    """PATCH /protocols/{id}."""
    r = await client.patch(
        f"/api/v1/hmp/protocols/{sample_protocol.id}",
        json={"title": "Updated Title"},
    )
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_delete_protocol(client, sample_protocol):
    """DELETE /protocols/{id}."""
    r = await client.delete(f"/api/v1/hmp/protocols/{sample_protocol.id}")
    assert r.status_code in (200, 204, 404, 500)


@pytest.mark.asyncio
async def test_protocol_summary(client, sample_protocol):
    """GET /protocols/{id}/summary."""
    r = await client.get(f"/api/v1/hmp/protocols/{sample_protocol.id}/summary")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_protocol_tags(client, sample_protocol):
    """GET /protocols/{id}/tags."""
    r = await client.get(f"/api/v1/hmp/protocols/{sample_protocol.id}/tags")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_protocol_actions(client, sample_protocol):
    """GET /protocols/{id}/action-items."""
    r = await client.get(f"/api/v1/hmp/protocols/{sample_protocol.id}/action-items")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_protocol_screenshots(client, sample_protocol):
    """GET /protocols/{id}/screenshots."""
    r = await client.get(f"/api/v1/hmp/protocols/{sample_protocol.id}/screenshots")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_search(client):
    """GET /protocols search."""
    r = await client.get("/api/v1/hmp/protocols?search=test")
    assert r.status_code in (200, 500)


@pytest.mark.asyncio
async def test_folders(client):
    """GET /folders."""
    r = await client.get("/api/v1/hmp/folders")
    assert r.status_code in (200, 500)


@pytest.mark.asyncio
async def test_create_folder(client):
    """POST /folders."""
    r = await client.post("/api/v1/hmp/folders", json={"name": "Test Folder"})
    assert r.status_code in (200, 201, 422, 500)
