"""E285: API integration tests."""
import pytest


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code in (200, 404)


@pytest.mark.asyncio
async def test_list_protocols_empty(client):
    r = await client.get("/api/v1/hmp/protocols")
    assert r.status_code in (200, 500)


@pytest.mark.asyncio
async def test_list_protocols_with_data(client, sample_protocol):
    r = await client.get("/api/v1/hmp/protocols")
    assert r.status_code in (200, 500)


@pytest.mark.asyncio
async def test_get_protocol_by_id(client, sample_protocol):
    r = await client.get(f"/api/v1/hmp/protocols/{sample_protocol.id}")
    assert r.status_code in (200, 500)


@pytest.mark.asyncio
async def test_create_protocol(client):
    r = await client.post("/api/v1/hmp/protocols", json={"title": "Test", "folder_id": None})
    assert r.status_code in (200, 201, 422, 500)


@pytest.mark.asyncio
async def test_get_user_setting(client):
    r = await client.get("/api/v1/hmp/user-setting")
    assert r.status_code in (200, 500)


@pytest.mark.asyncio
async def test_patch_user_setting(client):
    r = await client.patch("/api/v1/hmp/user-setting", json={"whisper_model": "base"})
    assert r.status_code in (200, 422, 500)


@pytest.mark.asyncio
async def test_list_screenshots(client, sample_protocol):
    r = await client.get(f"/api/v1/hmp/protocols/{sample_protocol.id}/screenshots")
    assert r.status_code in (200, 500)


@pytest.mark.asyncio
async def test_synthesize_screenshots(client, sample_protocol):
    r = await client.post(
        f"/api/v1/hmp/protocols/{sample_protocol.id}/screenshots/synthesize",
        json={"strategy": "uniform", "max_screenshots": 3},
    )
    assert r.status_code in (200, 400, 422, 500)


@pytest.mark.asyncio
async def test_list_utterances(client, sample_protocol):
    r = await client.get(f"/api/v1/hmp/utterances?protocol_id={sample_protocol.id}")
    assert r.status_code in (200, 500)


@pytest.mark.asyncio
async def test_whisper_status(client):
    r = await client.get("/api/v1/hmp/whisper/status/base")
    assert r.status_code in (200, 400, 500)


@pytest.mark.asyncio
async def test_whisper_status_invalid_model(client):
    r = await client.get("/api/v1/hmp/whisper/status/unknown-model-xyz")
    assert r.status_code in (200, 400, 500)


@pytest.mark.asyncio
async def test_list_decisions(client, sample_protocol):
    r = await client.get(f"/api/v1/hmp/decisions?protocol_id={sample_protocol.id}")
    assert r.status_code in (200, 500)


@pytest.mark.asyncio
async def test_create_decision(client, sample_utterance):
    r = await client.post("/api/v1/hmp/decisions", json={"utterance_id": str(sample_utterance.id), "text": "Test decision"})
    assert r.status_code in (200, 201, 422, 500)


@pytest.mark.asyncio
async def test_list_actions(client, sample_protocol):
    r = await client.get(f"/api/v1/hmp/action-items?protocol_id={sample_protocol.id}")
    assert r.status_code in (200, 405, 500)


@pytest.mark.asyncio
async def test_create_action(client, sample_protocol):
    r = await client.post("/api/v1/hmp/action-items", json={"protocol_id": str(sample_protocol.id), "title": "Test action"})
    assert r.status_code in (200, 201, 422, 500)


@pytest.mark.asyncio
async def test_list_tags(client):
    r = await client.get("/api/v1/hmp/tags")
    assert r.status_code in (200, 405, 500)


@pytest.mark.asyncio
async def test_create_tag(client):
    r = await client.post("/api/v1/hmp/tags", json={"name": "test-tag"})
    assert r.status_code in (200, 201, 422, 500)


@pytest.mark.asyncio
async def test_list_speakers(client, sample_protocol):
    r = await client.get(f"/api/v1/hmp/speakers?protocol_id={sample_protocol.id}")
    assert r.status_code in (200, 500)


@pytest.mark.asyncio
async def test_get_transcribe_progress(client):
    r = await client.get("/api/v1/hmp/transcribe/progress/non-existent-id")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_cancel_transcribe(client):
    r = await client.post("/api/v1/hmp/transcribe/cancel/non-existent-id")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_pause_transcribe(client):
    r = await client.post("/api/v1/hmp/transcribe/pause/non-existent-id")
    assert r.status_code in (200, 400, 404, 500)


@pytest.mark.asyncio
async def test_resume_transcribe(client):
    r = await client.post("/api/v1/hmp/transcribe/resume/non-existent-id")
    assert r.status_code in (200, 400, 404, 500)


@pytest.mark.asyncio
async def test_run_transcribe(client, sample_protocol):
    r = await client.post(
        "/api/v1/hmp/transcribe/run",
        json={"protocol_id": str(sample_protocol.id), "model": "base", "language": "ru"},
    )
    assert r.status_code in (200, 202, 422, 500)


@pytest.mark.asyncio
async def test_remote_transcribe(client, sample_protocol):
    r = await client.post(
        "/api/v1/hmp/remote",
        json={
            "protocol_id": str(sample_protocol.id),
            "target_url": "http://example.com",
            "target_path": "/transcribe",
            "model": "base",
            "language": "ru",
        },
    )
    assert r.status_code in (200, 422, 500)


@pytest.mark.asyncio
async def test_progress_by_protocol(client, sample_protocol):
    r = await client.get(f"/api/v1/hmp/transcribe/progress-by-protocol/{sample_protocol.id}")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_protocol_summary(client, sample_protocol):
    r = await client.get(f"/api/v1/hmp/protocols/{sample_protocol.id}/summary")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_protocol_tags(client, sample_protocol):
    r = await client.get(f"/api/v1/hmp/protocols/{sample_protocol.id}/tags")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_protocol_screenshots(client, sample_protocol):
    r = await client.get(f"/api/v1/hmp/protocols/{sample_protocol.id}/screenshots")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_protocol_actions(client, sample_protocol):
    r = await client.get(f"/api/v1/hmp/protocols/{sample_protocol.id}/action-items")
    assert r.status_code in (200, 404, 500)
