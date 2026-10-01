"""E-codes range: тесты для app/routers/dictionary.py.

Покрытие (цель 50%+):
- GET  /dictionary            — list
- POST /dictionary            — create + 409 + 422 (validation)
- PATCH /dictionary/{id}      — update + 404 + 422 (no fields) + 409 (dup term)
- DELETE /dictionary/{id}     — delete + 404
- get_or_create_singleton_user_setting helper
"""
import uuid

import pytest
from sqlalchemy import select

from app.db.models import Dictionary, UserSetting
from app.routers.dictionary import DICTIONARY_LIMIT, get_or_create_singleton_user_setting


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def sample_setting(db_session):
    """Создаёт singleton UserSetting (вызывает helper напрямую)."""
    return await get_or_create_singleton_user_setting(db_session)


@pytest.fixture
async def sample_term(db_session, sample_setting):
    """Один словарный термин, привязанный к singleton user setting."""
    t = Dictionary(
        id=uuid.uuid4(),
        user_setting_id=sample_setting.id,
        term="Hermes",
        category="product",
        weight=0.80,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


# ---------------------------------------------------------------------------
# GET /dictionary
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_dictionary_creates_singleton_when_empty(client):
    """GET /dictionary при пустой user_setting таблице создаёт singleton через helper.

    db_engine fixture уже TRUNCATE-ит все таблицы перед тестом.
    """
    r = await client.get("/api/v1/hmp/dictionary")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 0
    assert body["skip"] == 0
    assert body["limit"] == 200
    assert body["items"] == []


@pytest.mark.asyncio
async def test_list_dictionary_returns_existing_terms(client, sample_term):
    r = await client.get("/api/v1/hmp/dictionary")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["term"] == "Hermes"
    assert item["category"] == "product"
    assert item["weight"] == pytest.approx(0.80, rel=1e-3)


@pytest.mark.asyncio
async def test_list_dictionary_pagination(client, db_session, sample_setting):
    """GET с skip/limit — пагинация и порядок по term ASC."""
    for name in ["alpha", "beta", "gamma", "delta"]:
        db_session.add(
            Dictionary(
                id=uuid.uuid4(),
                user_setting_id=sample_setting.id,
                term=name,
                category="other",
                weight=1.0,
            )
        )
    await db_session.commit()

    r = await client.get("/api/v1/hmp/dictionary?skip=1&limit=2")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 4
    assert body["skip"] == 1
    assert body["limit"] == 2
    assert [i["term"] for i in body["items"]] == ["beta", "delta"]


@pytest.mark.asyncio
async def test_list_dictionary_validation_422(client):
    """Некорректные query-параметры → 422."""
    # limit > 500 → 422
    r = await client.get("/api/v1/hmp/dictionary?limit=10000")
    assert r.status_code == 422
    # skip < 0 → 422
    r = await client.get("/api/v1/hmp/dictionary?skip=-1")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /dictionary
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_term_success(client, sample_setting):
    r = await client.post(
        "/api/v1/hmp/dictionary",
        json={"term": "HMP", "category": "abbreviation", "weight": 0.9},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["term"] == "HMP"
    assert body["category"] == "abbreviation"
    assert body["weight"] == pytest.approx(0.9, rel=1e-3)
    # id is a valid UUID
    uuid.UUID(body["id"])


@pytest.mark.asyncio
async def test_create_term_duplicate_returns_409(client, sample_term):
    """Регистронезависимый дубликат → 409 ALREADY_EXISTS."""
    r = await client.post(
        "/api/v1/hmp/dictionary",
        json={"term": "hermes", "category": "product", "weight": 0.5},
    )
    assert r.status_code == 409
    assert "уже есть" in r.json()["detail"].lower() or "hermes" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_term_validation_422(client):
    """Pydantic валидаторы (min_length, le=1.0) → 422."""
    # term слишком короткий
    r = await client.post("/api/v1/hmp/dictionary", json={"term": "A"})
    assert r.status_code == 422
    # weight > 1
    r = await client.post(
        "/api/v1/hmp/dictionary",
        json={"term": "ValidTerm", "weight": 2.0},
    )
    assert r.status_code == 422
    # некорректная категория
    r = await client.post(
        "/api/v1/hmp/dictionary",
        json={"term": "Another", "category": "nope"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_term_limit_exceeded(monkeypatch, client, sample_setting, db_session):
    """422 LIMIT_EXCEEDED — если уже >= DICTIONARY_LIMIT терминов.

    Мокируем счётчик через monkeypatch на DICTIONARY_LIMIT, чтобы не создавать 1001 строку.
    """
    from app.routers import dictionary as dict_mod

    # Подменяем константу — теперь порог = 0.
    monkeypatch.setattr(dict_mod, "DICTIONARY_LIMIT", 0)

    r = await client.post(
        "/api/v1/hmp/dictionary",
        json={"term": "Limit", "category": "other", "weight": 0.5},
    )
    assert r.status_code == 422
    assert "лимит" in r.json()["detail"].lower() or "limit" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# PATCH /dictionary/{id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_term_success(client, sample_term):
    r = await client.patch(
        f"/api/v1/hmp/dictionary/{sample_term.id}",
        json={"weight": 0.25, "category": "abbreviation"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == str(sample_term.id)
    assert body["weight"] == pytest.approx(0.25, rel=1e-3)
    assert body["category"] == "abbreviation"
    # term не менялся
    assert body["term"] == "Hermes"


@pytest.mark.asyncio
async def test_update_term_404_when_missing(client):
    bogus = uuid.uuid4()
    r = await client.patch(
        f"/api/v1/hmp/dictionary/{bogus}",
        json={"weight": 0.3},
    )
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"].lower() or "not found" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_term_empty_body_422(client, sample_term):
    """Пустой PATCH → 422 (нет полей для обновления)."""
    r = await client.patch(
        f"/api/v1/hmp/dictionary/{sample_term.id}",
        json={},
    )
    assert r.status_code == 422
    assert "полей" in r.json()["detail"].lower() or "fields" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_term_duplicate_name_returns_409(client, sample_term, db_session, sample_setting):
    """Смена term на уже существующий (case-insensitive) → 409."""
    db_session.add(
        Dictionary(
            id=uuid.uuid4(),
            user_setting_id=sample_setting.id,
            term="Apollo",
            category="other",
            weight=1.0,
        )
    )
    await db_session.commit()

    r = await client.patch(
        f"/api/v1/hmp/dictionary/{sample_term.id}",
        json={"term": "apollo"},  # lower-case variant
    )
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# DELETE /dictionary/{id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_term_success(client, sample_term, db_session):
    r = await client.delete(f"/api/v1/hmp/dictionary/{sample_term.id}")
    assert r.status_code == 200, r.text

    # Проверяем, что запись действительно удалена
    found = (await db_session.execute(select(Dictionary))).scalars().all()
    assert sample_term.id not in {t.id for t in found}


@pytest.mark.asyncio
async def test_delete_term_404_when_missing(client):
    bogus = uuid.uuid4()
    r = await client.delete(f"/api/v1/hmp/dictionary/{bogus}")
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"].lower() or "not found" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Helper coverage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_or_create_singleton_returns_existing(db_session):
    """Helper: если запись уже есть — возвращает её без insert."""
    # First call — создаст singleton
    s1 = await get_or_create_singleton_user_setting(db_session)
    # Second call — должен вернуть ту же запись (по order_by id asc, limit 1)
    s2 = await get_or_create_singleton_user_setting(db_session)
    assert s1.id == s2.id

    rows = (await db_session.execute(select(UserSetting))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_or_create_singleton_returns_same_id_across_calls(db_session):
    """Helper возвращает одну и ту же запись при повторных вызовах."""
    s1 = await get_or_create_singleton_user_setting(db_session)
    s2 = await get_or_create_singleton_user_setting(db_session)
    s3 = await get_or_create_singleton_user_setting(db_session)
    assert s1.id == s2.id == s3.id
