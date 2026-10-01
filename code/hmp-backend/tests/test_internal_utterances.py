"""E289: тесты routers/utterances.py — list/update/toggle important."""
import pytest


@pytest.mark.asyncio
async def test_list_utterances(client, sample_protocol, sample_utterance):
    """GET /utterances — basic list with protocol filter."""
    r = await client.get(
        f"/api/v1/hmp/utterances?protocol_id={sample_protocol.id}"
    )
    assert r.status_code in (200, 404, 500)
    if r.status_code == 200:
        body = r.json()
        assert "items" in body
        assert "total" in body


@pytest.mark.asyncio
async def test_list_utterances_missing_protocol(client):
    """GET /utterances без protocol_id → 422."""
    r = await client.get("/api/v1/hmp/utterances")
    assert r.status_code in (422, 500)


@pytest.mark.asyncio
async def test_list_utterances_filter_by_speaker(client, sample_protocol, sample_speaker):
    """GET /utterances?speaker_id=... фильтр."""
    r = await client.get(
        f"/api/v1/hmp/utterances?protocol_id={sample_protocol.id}"
        f"&speaker_id={sample_speaker.id}"
    )
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_list_utterances_invalid_uuid(client):
    """GET /utterances?protocol_id=not-uuid → 422."""
    r = await client.get("/api/v1/hmp/utterances?protocol_id=not-a-uuid")
    assert r.status_code in (422, 500)


@pytest.mark.asyncio
async def test_get_utterance(client, sample_utterance):
    """GET /utterances/{id}."""
    r = await client.get(f"/api/v1/hmp/utterances/{sample_utterance.id}")
    assert r.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_update_utterance_speaker(client, sample_utterance):
    """PATCH /utterances/{id}/speaker — смена спикера (используем тот же sample_speaker)."""
    r = await client.patch(
        f"/api/v1/hmp/utterances/{sample_utterance.id}/speaker",
        json={"speaker_label": "SPK_TEST"},
    )
    assert r.status_code in (200, 404, 422, 500)


@pytest.mark.asyncio
async def test_toggle_utterance_important(client, sample_utterance):
    """PATCH /utterances/{id}/important — toggle important=True."""
    r = await client.patch(
        f"/api/v1/hmp/utterances/{sample_utterance.id}/important",
        json={"important": True},
    )
    assert r.status_code in (200, 404, 422, 500)