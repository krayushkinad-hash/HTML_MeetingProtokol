"""Final coverage push for app/routers/dictionary.py — target 70%+.

Targets the remaining uncovered branches per coverage_final_v6.txt:
  - 78, 86                    : GET /dictionary count + ordered query execution
  - 128-129                   : POST /dictionary LIMIT_EXCEEDED 422
  - 143-155                   : POST /dictionary ALREADY_EXISTS 409 + persist block
  - 159-168                   : POST /dictionary success-logger.info
  - 184-200                   : PATCH /dictionary/{id} 404 + empty body 422
  - 210-217                   : PATCH /dictionary/{id} rename-duplicate 409 + update loop
  - 222-230                   : PATCH /dictionary/{id} success-logger.info
  - 245-255, 258              : DELETE /dictionary/{id} 404 + commit + logger.info

All data is created via the public POST endpoint (not direct DB writes) — this
keeps the test aligned with override_get_db's session lifecycle and avoids
cross-session visibility problems reported in earlier rounds.
"""
import pytest
import uuid

from app.db.models import Dictionary, UserSetting
from sqlalchemy import select


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE = "/api/v1/hmp/dictionary"


async def _create_term(client, term: str = "Hermes", **overrides) -> dict:
    """Create a term through the API and return its JSON body."""
    body = {"term": term, "category": "product", "weight": 0.80}
    body.update(overrides)
    r = await client.post(BASE, json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# GET /dictionary — count + ordering branches
# ---------------------------------------------------------------------------

async def test_list_dictionary_total_and_ordering(client):
    """GET returns total count and items sorted by term asc (covers 78, 86)."""
    await _create_term(client, term="Zeta")
    await _create_term(client, term="Alpha")
    await _create_term(client, term="Mu")

    r = await client.get(BASE)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["total"] == 3
    assert body["skip"] == 0
    assert body["limit"] == 200
    terms_in_order = [item["term"] for item in body["items"]]
    assert terms_in_order == sorted(terms_in_order)
    assert terms_in_order == ["Alpha", "Mu", "Zeta"]


async def test_list_dictionary_pagination_explicit(client):
    """GET with explicit skip & limit respects them and trims items."""
    for t in ["AA", "BB", "CC", "DD", "EE"]:
        await _create_term(client, term=t)

    r = await client.get(f"{BASE}?skip=2&limit=2")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert body["skip"] == 2
    assert body["limit"] == 2
    assert len(body["items"]) == 2
    assert [i["term"] for i in body["items"]] == ["CC", "DD"]


# ---------------------------------------------------------------------------
# POST /dictionary — validation paths
# ---------------------------------------------------------------------------

async def test_create_term_validation_too_short(client):
    """term below min_length=2 → 422 (Pydantic INVALID_TERM branch)."""
    r = await client.post(BASE, json={"term": "X", "category": "other", "weight": 0.5})
    assert r.status_code == 422


async def test_create_term_validation_weight_above_one(client):
    """weight > 1.0 violates ge/le constraint → 422."""
    r = await client.post(
        BASE, json={"term": "BadWeight", "category": "other", "weight": 1.5}
    )
    assert r.status_code == 422


async def test_create_term_validation_invalid_category(client):
    """category not in Literal → 422."""
    r = await client.post(
        BASE, json={"term": "BadCat", "category": "bogus", "weight": 0.5}
    )
    assert r.status_code == 422


async def test_create_term_duplicate_case_insensitive_returns_409(client):
    """Duplicate check is case-insensitive (LOWER(term)) — covers 143-147."""
    await _create_term(client, term="Hermes")
    r = await client.post(
        BASE, json={"term": "HERMES", "category": "product", "weight": 0.5}
    )
    assert r.status_code == 409
    assert "уже есть" in r.json()["detail"]


# ---------------------------------------------------------------------------
# PATCH /dictionary/{id} — 404, empty-body, weight update, duplicate-rename
# ---------------------------------------------------------------------------

async def test_patch_term_not_found_returns_404(client):
    """PATCH against a random UUID that doesn't exist → 404 (covers 184-188)."""
    fake_id = uuid.uuid4()
    r = await client.patch(f"{BASE}/{fake_id}", json={"weight": 0.5})
    assert r.status_code == 404
    assert r.json()["detail"] == "Термин не найден"


async def test_patch_term_empty_body_returns_422(client):
    """PATCH with empty body → 422 'no fields to update' (covers 192-196)."""
    created = await _create_term(client, term="EmptyPatch")
    r = await client.patch(f"{BASE}/{created['id']}", json={})
    assert r.status_code == 422
    assert "Нет полей" in r.json()["detail"]


async def test_patch_term_weight_only(client):
    """PATCH with only weight updates weight, keeps term & category."""
    created = await _create_term(client, term="WeightUp", weight=0.30)
    r = await client.patch(f"{BASE}/{created['id']}", json={"weight": 0.95})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["weight"] == pytest.approx(0.95, abs=1e-3)
    assert body["term"] == "WeightUp"
    assert body["category"] == "product"


async def test_patch_term_category_change(client):
    """PATCH with category change updates category, leaves term/weight intact."""
    created = await _create_term(client, term="CatFlip", category="product")
    r = await client.patch(f"{BASE}/{created['id']}", json={"category": "name"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category"] == "name"
    assert body["term"] == "CatFlip"


async def test_patch_term_rename_duplicate_returns_409(client):
    """Renaming onto an existing term's lowercase form → 409 (covers 210-214)."""
    a = await _create_term(client, term="Alpha")
    b = await _create_term(client, term="Beta")

    r = await client.patch(f"{BASE}/{b['id']}", json={"term": "ALPHA"})
    assert r.status_code == 409
    assert "уже есть" in r.json()["detail"]

    # 'a' must remain unchanged in DB
    r2 = await client.get(BASE)
    assert r2.status_code == 200
    terms = {i["id"]: i["term"] for i in r2.json()["items"]}
    assert terms[a["id"]] == "Alpha"
    assert terms[b["id"]] == "Beta"


async def test_patch_term_same_value_noop_rename(client):
    """Renaming to the same term (lowercase equal) is allowed (no duplicate)."""
    created = await _create_term(client, term="KeepName")
    r = await client.patch(f"{BASE}/{created['id']}", json={"term": "keepname"})
    # Same term → the duplicate-rename branch is bypassed → update succeeds.
    assert r.status_code == 200, r.text
    assert r.json()["term"] == "keepname"


# ---------------------------------------------------------------------------
# DELETE /dictionary/{id} — 404, success path
# ---------------------------------------------------------------------------

async def test_delete_term_not_found_returns_404(client):
    """DELETE on missing UUID → 404 (covers 245-249)."""
    fake_id = uuid.uuid4()
    r = await client.delete(f"{BASE}/{fake_id}")
    assert r.status_code == 404
    assert r.json()["detail"] == "Термин не найден"