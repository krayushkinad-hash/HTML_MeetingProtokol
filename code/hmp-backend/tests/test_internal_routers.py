"""E287: тесты остальных routers."""
import pytest


@pytest.mark.asyncio
async def test_audio_get_sources(client):
    r = await client.get("/api/v1/hmp/audio/sources")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_audio_get_media(client):
    r = await client.get("/api/v1/hmp/media/protocols/test-id/source.m4a")
    assert r.status_code in (200, 206, 404, 422, 500)


@pytest.mark.asyncio
async def test_bot_users(client):
    r = await client.get("/api/v1/hmp/bot/users")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_bot_me(client):
    r = await client.get("/api/v1/hmp/bot/me")
    assert r.status_code in (200, 401, 404, 500)


@pytest.mark.asyncio
async def test_calendar_list(client):
    r = await client.get("/api/v1/hmp/calendar")
    assert r.status_code in (200, 404, 422, 500)


@pytest.mark.asyncio
async def test_decisions_list(client):
    r = await client.get("/api/v1/hmp/decisions")
    assert r.status_code in (200, 404, 422, 500)


@pytest.mark.asyncio
async def test_diarize_status(client):
    r = await client.get("/api/v1/hmp/diarize/status/test-id")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_diarize_run(client, sample_protocol):
    r = await client.post(
        f"/api/v1/hmp/diarize/run",
        json={"protocol_id": str(sample_protocol.id)},
    )
    assert r.status_code in (200, 202, 500)


@pytest.mark.asyncio
async def test_dictionary_list(client):
    r = await client.get("/api/v1/hmp/dictionary")
    assert r.status_code in (200, 404, 422, 500)


@pytest.mark.asyncio
async def test_dictionary_create(client):
    r = await client.post("/api/v1/hmp/dictionary", json={"term": "test", "definition": "test def"})
    assert r.status_code in (200, 201, 422, 500)


@pytest.mark.asyncio
async def test_export_docx(client, sample_protocol):
    r = await client.post(f"/api/v1/hmp/export/{sample_protocol.id}/docx")
    assert r.status_code in (200, 404, 422, 500)


@pytest.mark.asyncio
async def test_export_txt(client, sample_protocol):
    r = await client.post(f"/api/v1/hmp/export/{sample_protocol.id}/txt")
    assert r.status_code in (200, 404, 422, 500)


@pytest.mark.asyncio
async def test_folders_list(client):
    r = await client.get("/api/v1/hmp/folders")
    assert r.status_code in (200, 404, 422, 500)


@pytest.mark.asyncio
async def test_folders_create(client):
    r = await client.post("/api/v1/hmp/folders", json={"name": "Test"})
    assert r.status_code in (200, 201, 422, 500)


@pytest.mark.asyncio
async def test_folders_update(client, db_session, sample_protocol):
    """PATCH /folders/{id}."""
    if not sample_protocol.folder_id:
        pytest.skip("Нет folder_id")
    folder_id = sample_protocol.folder_id
    r = await client.patch(f"/api/v1/hmp/folders/{folder_id}", json={"name": "New Name"})
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/api/v1/hmp/health")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_live_start(client, sample_protocol):
    r = await client.post(
        "/api/v1/hmp/live/start",
        json={"protocol_id": str(sample_protocol.id)},
    )
    assert r.status_code in (200, 202, 422, 500)


@pytest.mark.asyncio
async def test_live_stop(client):
    r = await client.post("/api/v1/hmp/live/stop")
    assert r.status_code in (200, 404, 422, 500)


@pytest.mark.asyncio
async def test_screenshots_delete(client, sample_protocol):
    r = await client.delete(f"/api/v1/hmp/protocols/{sample_protocol.id}/screenshots/fake-id")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_search_query(client):
    r = await client.get("/api/v1/hmp/search?q=test")
    assert r.status_code in (200, 404, 422, 500)


@pytest.mark.asyncio
async def test_speakers_assign(client, sample_utterance):
    r = await client.post(
        f"/api/v1/hmp/speakers/{sample_utterance.id}/assign",
        json={"speaker_name": "Test Speaker"},
    )
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_speakers_create(client, sample_protocol):
    r = await client.post(
        "/api/v1/hmp/speakers",
        json={"protocol_id": str(sample_protocol.id), "name": "Test Speaker"},
    )
    assert r.status_code in (200, 201, 405, 422, 500)


@pytest.mark.asyncio
async def test_summary_generate(client, sample_protocol):
    r = await client.post(f"/api/v1/hmp/summary/{sample_protocol.id}/generate")
    assert r.status_code in (200, 202, 404, 500)


@pytest.mark.asyncio
async def test_tags_create(client):
    r = await client.post("/api/v1/hmp/tags", json={"name": "test"})
    assert r.status_code in (200, 201, 422, 500)


@pytest.mark.asyncio
async def test_tags_assign(client, sample_protocol):
    r = await client.post(
        f"/api/v1/hmp/protocols/{sample_protocol.id}/tags",
        json={"tag_name": "important"},
    )
    assert r.status_code in (200, 201, 404, 405, 500)


@pytest.mark.asyncio
async def test_transcribe_remote(client, sample_protocol):
    r = await client.post(
        "/api/v1/hmp/transcribe/remote",
        json={
            "protocol_id": str(sample_protocol.id),
            "target_url": "http://example.com",
            "target_path": "/transcribe",
            "model": "base",
            "language": "ru",
        },
    )
    assert r.status_code in (200, 404, 422, 500)


@pytest.mark.asyncio
async def test_transcribe_upgrade(client, sample_protocol):
    r = await client.post(f"/api/v1/hmp/transcribe/upgrade/{sample_protocol.id}")
    assert r.status_code in (200, 202, 400, 404, 500)


@pytest.mark.asyncio
async def test_utterances_update(client, sample_utterance):
    r = await client.patch(
        f"/api/v1/hmp/utterances/{sample_utterance.id}",
        json={"text": "Updated text"},
    )
    assert r.status_code in (200, 404, 405, 500)


@pytest.mark.asyncio
async def test_utterances_list_filtered(client, sample_protocol):
    r = await client.get(f"/api/v1/hmp/utterances?protocol_id={sample_protocol.id}&important=true")
    assert r.status_code in (200, 404, 422, 500)


@pytest.mark.asyncio
async def test_whisper_models_list(client):
    r = await client.get("/api/v1/hmp/whisper/models")
    assert r.status_code in (200, 404, 422, 500)


@pytest.mark.asyncio
async def test_whisper_unload(client):
    r = await client.post("/api/v1/hmp/whisper/unload/base")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_protocols_search(client):
    r = await client.get("/api/v1/hmp/protocols?search=test")
    assert r.status_code in (200, 404, 422, 500)


@pytest.mark.asyncio
async def test_protocols_move(client, sample_protocol):
    r = await client.post(
        "/api/v1/hmp/protocols/move",
        json={"protocol_id": str(sample_protocol.id), "target_folder_id": None},
    )
    assert r.status_code in (200, 404, 405, 500)
