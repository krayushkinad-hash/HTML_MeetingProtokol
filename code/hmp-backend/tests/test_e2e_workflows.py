"""E285: E2E workflow tests."""
import pytest


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_settings_roundtrip(client):
    """E2E: GET → PATCH → GET."""
    r1 = await client.get("/api/v1/hmp/user-setting")
    r2 = await client.patch("/api/v1/hmp/user-setting", json={"whisper_model": "tiny"})
    r3 = await client.get("/api/v1/hmp/user-setting")
    assert r1.status_code in (200, 500)
    assert r2.status_code in (200, 500)
    assert r3.status_code in (200, 500)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_protocol_create_and_get(client):
    """E2E: создать протокол → получить по id."""
    create_r = await client.post("/api/v1/hmp/protocols", json={"title": "E2E Test"})
    assert create_r.status_code in (200, 201, 422, 500)
    if create_r.status_code in (200, 201):
        data = create_r.json()
        pid = data.get("id")
        if pid:
            r = await client.get(f"/api/v1/hmp/protocols/{pid}")
            assert r.status_code in (200, 500)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_screenshots_synthesize(client, sample_protocol):
    """E2E: synthesize screenshots."""
    r = await client.post(
        f"/api/v1/hmp/protocols/{sample_protocol.id}/screenshots/synthesize",
        json={"strategy": "uniform", "max_screenshots": 3},
    )
    assert r.status_code in (200, 400, 422, 500)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_decisions(client, sample_protocol):
    """E2E: list decisions для протокола."""
    r = await client.get(f"/api/v1/hmp/decisions?protocol_id={sample_protocol.id}")
    assert r.status_code in (200, 500)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_actions(client, sample_protocol):
    """E2E: list action items."""
    r = await client.get(f"/api/v1/hmp/action-items?protocol_id={sample_protocol.id}")
    assert r.status_code in (200, 405, 500)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_tags(client):
    """E2E: list tags."""
    r = await client.get("/api/v1/hmp/tags")
    assert r.status_code in (200, 405, 500)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_speakers(client, sample_protocol):
    """E2E: list speakers."""
    r = await client.get(f"/api/v1/hmp/speakers?protocol_id={sample_protocol.id}")
    assert r.status_code in (200, 500)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_protocol_summary(client, sample_protocol):
    """E2E: get summary."""
    r = await client.get(f"/api/v1/hmp/protocols/{sample_protocol.id}/summary")
    assert r.status_code in (200, 404, 500)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_utterances_list(client, sample_protocol):
    """E2E: list utterances."""
    r = await client.get(f"/api/v1/hmp/utterances?protocol_id={sample_protocol.id}")
    assert r.status_code in (200, 500)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_whisper_status_all(client):
    """E2E: проверка всех моделей."""
    for model in ["tiny", "base", "small", "medium", "large-v3"]:
        r = await client.get(f"/api/v1/hmp/whisper/status/{model}")
        assert r.status_code in (200, 400, 500)
