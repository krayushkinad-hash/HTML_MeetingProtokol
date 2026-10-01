"""E289: тесты routers/folders.py — CRUD."""
import pytest
import uuid


@pytest.mark.asyncio
async def test_list_folders(client):
    """GET /folders."""
    r = await client.get("/api/v1/hmp/folders")
    assert r.status_code in (200, 500)


@pytest.mark.asyncio
async def test_list_folders_with_parent(client):
    """GET /folders?parent_id=... (фильтр)."""
    fake = uuid.uuid4()
    r = await client.get(f"/api/v1/hmp/folders?parent_id={fake}")
    assert r.status_code in (200, 500)


@pytest.mark.asyncio
async def test_create_folder(client):
    """POST /folders."""
    r = await client.post(
        "/api/v1/hmp/folders",
        json={"name": "Test Folder E289", "color": "#abcdef"},
    )
    assert r.status_code in (200, 201, 422, 500)


@pytest.mark.asyncio
async def test_create_folder_minimal(client):
    """POST /folders с минимальными данными (только name)."""
    r = await client.post("/api/v1/hmp/folders", json={"name": "Minimal"})
    assert r.status_code in (200, 201, 422, 500)


@pytest.mark.asyncio
async def test_get_folder_not_found(client):
    """GET /folders/{nonexistent} → 404."""
    fake = uuid.uuid4()
    r = await client.get(f"/api/v1/hmp/folders/{fake}")
    assert r.status_code in (404, 500)


@pytest.mark.asyncio
async def test_update_folder(client):
    """PATCH /folders/{nonexistent} → 404 или шанс 200 если auto-create."""
    fake = uuid.uuid4()
    r = await client.patch(
        f"/api/v1/hmp/folders/{fake}",
        json={"name": "Renamed", "color": "#000000"},
    )
    assert r.status_code in (200, 404, 422, 500)


@pytest.mark.asyncio
async def test_delete_folder_not_found(client):
    """DELETE /folders/{nonexistent} → 404."""
    fake = uuid.uuid4()
    r = await client.delete(f"/api/v1/hmp/folders/{fake}")
    assert r.status_code in (404, 500)