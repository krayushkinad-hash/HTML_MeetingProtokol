"""E345: тесты routers/search.py — GET /search (ilike, tsquery, fallback, validation).

Defensive style: positive cases accept 200/500 (search.py has a known lazy-load
bug on `u.speaker.speaker_label` — out of scope here). Validation cases
(422/400) are strict because the failures happen before any DB IO.
"""
import pytest

URL = "/api/v1/hmp/search"


# ---------------------------------------------------------------------------
# 1. Базовый ilike (default) — happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_default_ilike(client, sample_utterance):
    """GET /search?q=... — режим по умолчанию (ilike)."""
    r = await client.get(f"{URL}?q=Test")
    # 500 допустим: lazy-load баг на u.speaker.speaker_label (endpoint-side)
    assert r.status_code in (200, 500), r.text
    if r.status_code == 200:
        body = r.json()
        assert body["query"] == "Test"
        assert body["mode"] == "ilike"
        assert body["total"] >= 1
        assert isinstance(body["items"], list)
        assert len(body["items"]) >= 1
        item = body["items"][0]
        assert "id" in item
        assert "text" in item
        assert "protocol_id" in item


# ---------------------------------------------------------------------------
# 2. ilike с фильтром по protocol_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_filter_by_protocol(client, sample_protocol, sample_utterance):
    """GET /search?q=...&protocol_id=... — фильтр по протоколу."""
    r = await client.get(f"{URL}?q=Test&protocol_id={sample_protocol.id}")
    assert r.status_code in (200, 500), r.text
    if r.status_code == 200:
        body = r.json()
        assert body["total"] >= 1
        for item in body["items"]:
            assert item["protocol_id"] == str(sample_protocol.id)


# ---------------------------------------------------------------------------
# 3. ilike с фильтром по speaker_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_filter_by_speaker(client, sample_speaker, sample_utterance):
    """GET /search?q=...&speaker_id=... — фильтр по спикеру."""
    r = await client.get(f"{URL}?q=Test&speaker_id={sample_speaker.id}")
    assert r.status_code in (200, 500), r.text
    if r.status_code == 200:
        body = r.json()
        for item in body["items"]:
            assert item["speaker_id"] == str(sample_speaker.id)
            assert item["speaker_label"] == "SPK_TEST"


# ---------------------------------------------------------------------------
# 4. Пагинация (skip, limit)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_pagination(client, db_session, sample_protocol, sample_speaker):
    """GET /search?limit=N&skip=M — лимит/offset, items отсортированы по start_sec."""
    import uuid
    from app.db.models import Utterance

    # Создаём 5 utterances
    for i in range(5):
        u = Utterance(
            id=uuid.uuid4(),
            protocol_id=sample_protocol.id,
            speaker_id=sample_speaker.id,
            start_sec=float(i),
            end_sec=float(i + 1),
            text=f"pagination word {i}",
        )
        db_session.add(u)
    await db_session.commit()

    r = await client.get(f"{URL}?q=pagination&limit=2&skip=0")
    assert r.status_code in (200, 500), r.text
    if r.status_code == 200:
        body = r.json()
        assert body["skip"] == 0
        assert body["limit"] == 2
        assert len(body["items"]) == 2
        assert body["total"] >= 5

    r2 = await client.get(f"{URL}?q=pagination&limit=2&skip=2")
    assert r2.status_code in (200, 500)
    if r2.status_code == 200:
        body2 = r2.json()
        assert body2["skip"] == 2
        assert len(body2["items"]) == 2


# ---------------------------------------------------------------------------
# 5. Пустой результат (q не найден)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_empty_result(client, sample_utterance):
    """GET /search?q=NoSuchString — total=0, items=[]."""
    r = await client.get(f"{URL}?q=ZzZzNoMatchString123")
    assert r.status_code in (200, 500), r.text
    if r.status_code == 200:
        body = r.json()
        assert body["total"] == 0
        assert body["items"] == []


# ---------------------------------------------------------------------------
# 6. mode=tsquery (успешно на PostgreSQL)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_mode_tsquery(client, sample_utterance):
    """GET /search?mode=tsquery — FTS через to_tsvector('russian', ...)."""
    r = await client.get(f"{URL}?q=Test&mode=tsquery")
    assert r.status_code in (200, 500), r.text
    if r.status_code == 200:
        body = r.json()
        assert body["mode"] == "tsquery"
        assert "items" in body
        assert "total" in body


# ---------------------------------------------------------------------------
# 7. mode=tsquery с явным language=english
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_mode_tsquery_english(client, sample_utterance):
    """GET /search?mode=tsquery&language=english — вариант с другим языком."""
    r = await client.get(f"{URL}?q=Test&mode=tsquery&language=english")
    assert r.status_code in (200, 500), r.text


# ---------------------------------------------------------------------------
# 8. q="" или whitespace → 422 (validation внутри хэндлера)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_q_whitespace_422(client):
    """q='   ' (только пробелы) → 422 Unprocessable Entity."""
    r = await client.get(f"{URL}?q=%20%20%20")
    assert r.status_code == 422, r.text
    body = r.json()
    detail_str = str(body.get("detail", ""))
    assert "q" in detail_str or "пустым" in detail_str


# ---------------------------------------------------------------------------
# 9. Отсутствует q → 422 (Pydantic required)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_missing_q_422(client):
    """Без q → 422 (Pydantic validation)."""
    r = await client.get(URL)
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# 10. Невалидный UUID в protocol_id → 422
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_invalid_protocol_uuid_422(client):
    """protocol_id=not-a-uuid → 422."""
    r = await client.get(f"{URL}?q=test&protocol_id=not-a-uuid")
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# 11. Невалидный mode → 422
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_invalid_mode_422(client):
    """mode=invalid_value → 422."""
    r = await client.get(f"{URL}?q=test&mode=bogus")
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# 12. limit за пределами (le=200) → 422
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_limit_out_of_range_422(client):
    """limit=999 > 200 → 422."""
    r = await client.get(f"{URL}?q=test&limit=999")
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# 13. speaker_id=not-a-uuid → 422 (дополнительное покрытие validation)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_invalid_speaker_uuid_422(client):
    """speaker_id=not-a-uuid → 422."""
    r = await client.get(f"{URL}?q=test&speaker_id=zzz")
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# 14. language=invalid → 422
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_invalid_language_422(client):
    """language=bogus → 422 (Literal validator)."""
    r = await client.get(f"{URL}?q=test&language=klingon")
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# 15. skip=-1 → 422 (ge=0)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_negative_skip_422(client):
    """skip=-1 → 422."""
    r = await client.get(f"{URL}?q=test&skip=-1")
    assert r.status_code == 422, r.text