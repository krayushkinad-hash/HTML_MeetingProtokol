"""E-расширение: дополнительные тесты для app/routers/dictionary.py.

Цель — добить покрытие с ~50% до 70%+ по бранчам:
- PATCH: смена term на новое уникальное значение (term rename — happy path)
- PATCH: только term без других полей (одиночное обновление)
- PATCH: некорректный UUID в path → 422
- POST: default category ('other') когда category не передана
- POST: граничные значения weight (0.0 и 1.0)
- POST: дубликат с тем же регистром (case-sensitive совпадение)
- GET: skip за пределами списка → items пуст, total корректен
- DELETE: повторное удаление → 404 (запись отсутствует)
- DELETE: реальное удаление из БД
- DELETE: некорректный UUID в path → 422

NOTE: setup данных выполняется через POST /dictionary (а не через прямой
db_session.add) — это исключает cross-session race с override_get_db.
"""
import pytest
from sqlalchemy import select

from app.db.models import Dictionary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_term(client, term: str = "Hermes", **overrides) -> dict:
    """Создать термин через API и вернуть JSON-ответ."""
    body = {"term": term, "category": "product", "weight": 0.80}
    body.update(overrides)
    r = await client.post("/api/v1/hmp/dictionary", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# PATCH — дополнительные ветки
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_term_rename_success(client):
    """PATCH c term на новое уникальное имя → 200 и новое значение сохранено."""
    created = await _create_term(client, term="Hermes")
    r = await client.patch(
        f"/api/v1/hmp/dictionary/{created['id']}",
        json={"term": "HermesNew"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["term"] == "HermesNew"
    # category и weight остались прежними
    assert body["category"] == "product"
    assert body["weight"] == pytest.approx(0.80, rel=1e-3)


@pytest.mark.asyncio
async def test_patch_only_term_field(client):
    """PATCH только с term → category/weight не трогаются (default behaviour)."""
    created = await _create_term(client, term="HermesRenamable")
    r = await client.patch(
        f"/api/v1/hmp/dictionary/{created['id']}",
        json={"term": "HermesRenamed"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["term"] == "HermesRenamed"
    assert body["category"] == "product"
    assert body["weight"] == pytest.approx(0.80, rel=1e-3)


@pytest.mark.asyncio
async def test_patch_invalid_uuid_returns_422(client):
    """PATCH с некорректным UUID → 422 (валидация path-параметра FastAPI)."""
    r = await client.patch(
        "/api/v1/hmp/dictionary/not-a-uuid",
        json={"weight": 0.3},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST — граничные значения и defaults
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_term_default_category(client):
    """POST без category → category = 'other' (default Pydantic)."""
    r = await client.post(
        "/api/v1/hmp/dictionary",
        json={"term": "DefaultCat"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["category"] == "other"


@pytest.mark.asyncio
async def test_create_term_weight_boundary_values(client):
    """POST с weight = 0.0 и weight = 1.0 — границы легитимны."""
    r0 = await client.post(
        "/api/v1/hmp/dictionary",
        json={"term": "MinWeight", "weight": 0.0},
    )
    assert r0.status_code == 201, r0.text
    assert r0.json()["weight"] == pytest.approx(0.0, abs=1e-6)

    r1 = await client.post(
        "/api/v1/hmp/dictionary",
        json={"term": "MaxWeight", "weight": 1.0},
    )
    assert r1.status_code == 201, r1.text
    assert r1.json()["weight"] == pytest.approx(1.0, abs=1e-6)


@pytest.mark.asyncio
async def test_create_term_duplicate_exact_case(client):
    """POST с тем же term (тот же регистр) → 409 ALREADY_EXISTS."""
    await _create_term(client, term="Hermes")
    r = await client.post(
        "/api/v1/hmp/dictionary",
        json={"term": "Hermes", "category": "product", "weight": 0.5},
    )
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# GET — пагинация за пределами
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_dictionary_skip_beyond_returns_empty(client):
    """GET с skip > total → items пуст, total всё ещё показывает реальный count."""
    await _create_term(client, term="OneTerm")
    r = await client.get("/api/v1/hmp/dictionary?skip=10&limit=5")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"] == []
    assert body["skip"] == 10
    assert body["limit"] == 5


# ---------------------------------------------------------------------------
# DELETE — повторное удаление и валидация
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_term_then_again_returns_404(client):
    """DELETE один раз → 200; второй раз по тому же id → 404."""
    created = await _create_term(client, term="DeleteMe")
    first = await client.delete(f"/api/v1/hmp/dictionary/{created['id']}")
    assert first.status_code == 200, first.text

    second = await client.delete(f"/api/v1/hmp/dictionary/{created['id']}")
    assert second.status_code == 404


@pytest.mark.asyncio
async def test_delete_term_removes_from_db(client, db_engine):
    """DELETE реально убирает запись из БД (проверка через прямой запрос)."""
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    created = await _create_term(client, term="GoneTerm")
    r = await client.delete(f"/api/v1/hmp/dictionary/{created['id']}")
    assert r.status_code == 200, r.text

    # Проверяем через отдельный сеанс с тем же engine
    Session = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as verify_session:
        rows = (await verify_session.execute(select(Dictionary))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_delete_invalid_uuid_returns_422(client):
    """DELETE с некорректным UUID → 422 (валидация path-параметра)."""
    r = await client.delete("/api/v1/hmp/dictionary/not-a-uuid")
    assert r.status_code == 422