"""Direct-handler-call coverage tests for app/routers/dictionary.py.

WORKAROUND for `cov-tracking-anomaly-fastapi-lazy-imports`:
Calls `list_dictionary`, `create_term`, `update_term`, `delete_term` directly
as Python async functions instead of through the FastAPI HTTP layer
(ASGITransport + httpx). pytest-cov records line executions on the test's own
greenlet, missing nothing under direct calls.

See skill: ~/.hermes/profiles/alex3/skills/methodology/cov-tracking-anomaly-fastapi-lazy-imports/SKILL.md
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.db.models import Dictionary, UserSetting
from app.routers import dictionary as dict_module
from app.schemas import DictionaryTermCreate, DictionaryTermUpdate

pytestmark = pytest.mark.asyncio


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def direct_db(db_engine):
    """Reuse conftest's db_engine — no second engine, no deadlock surface."""
    async_session = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


class _FakeRequest:
    """Minimal stand-in for create_term / update_term / delete_term.

    Each handler reads `request.state.correlation_id` via getattr(..., None).
    """
    class _State:
        correlation_id = None

    def __init__(self):
        self.state = self._State()


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


async def _seed_user_setting(direct_db) -> UserSetting:
    """Insert a UserSetting so Dictionary FK is satisfiable.

    Unique values per field keep tests idempotent across the truncated schema.
    """
    s = UserSetting(
        llm_provider="hermes",
        whisper_model="large-v3",
        theme="auto",
        notifications_enabled=True,
        hotkey_show_search="Ctrl+K",
    )
    direct_db.add(s)
    await direct_db.commit()
    await direct_db.refresh(s)
    return s


async def _seed_term(
    direct_db,
    user_setting_id: uuid.UUID,
    term: str = "seed-term",
    category: str = "other",
    weight: float = 1.0,
) -> Dictionary:
    t = Dictionary(
        user_setting_id=user_setting_id,
        term=term,
        category=category,
        weight=weight,
    )
    direct_db.add(t)
    await direct_db.commit()
    await direct_db.refresh(t)
    return t


# ----------------------------------------------------------------------------
# get_or_create_singleton_user_setting — list_dictionary trigger path
# ----------------------------------------------------------------------------


async def test_list_dictionary_direct_creates_singleton(direct_db):
    """First call must seed UserSetting and return empty dict page.

    NOTE: skip/limit default to FastAPI ``Query`` objects in the handler
    signature; under direct calls SQLAlchemy's ``.offset()`` rejects those,
    so we pass plain ints to exercise the real code path.
    """
    result = await dict_module.list_dictionary(skip=0, limit=200, db=direct_db)

    assert result["total"] == 0
    assert result["items"] == []
    assert result["skip"] == 0
    assert result["limit"] == 200

    # Singleton UserSetting row now exists
    from sqlalchemy import select

    found = (await direct_db.execute(select(UserSetting))).scalars().all()
    assert len(found) == 1


async def test_list_dictionary_direct_returns_sorted_items(direct_db):
    user_setting = await _seed_user_setting(direct_db)
    await _seed_term(direct_db, user_setting.id, "charlie")
    await _seed_term(direct_db, user_setting.id, "alpha")
    await _seed_term(direct_db, user_setting.id, "bravo")

    result = await dict_module.list_dictionary(skip=0, limit=200, db=direct_db)

    assert result["total"] == 3
    names = [item.term for item in result["items"]]
    assert names == ["alpha", "bravo", "charlie"]


async def test_list_dictionary_direct_skip_and_limit(direct_db):
    user_setting = await _seed_user_setting(direct_db)
    for n in ["a", "b", "c", "d", "e"]:
        await _seed_term(direct_db, user_setting.id, n)

    # skip=2, limit=2 → ["c", "d"]
    result = await dict_module.list_dictionary(skip=2, limit=2, db=direct_db)

    assert result["skip"] == 2
    assert result["limit"] == 2
    assert result["total"] == 5
    names = [item.term for item in result["items"]]
    assert names == ["c", "d"]


# ----------------------------------------------------------------------------
# create_term — direct call
# ----------------------------------------------------------------------------


async def test_create_term_direct_happy_path(direct_db):
    user_setting = await _seed_user_setting(direct_db)
    body = DictionaryTermCreate(term="alpha", category="name", weight=0.7)
    req = _FakeRequest()

    resp = await dict_module.create_term(body=body, request=req, db=direct_db)

    assert resp.term == "alpha"
    assert resp.category == "name"
    assert resp.weight == 0.7
    assert resp.id is not None


async def test_create_term_direct_409_case_insensitive_duplicate(direct_db):
    """Existing 'Alpha' must block creation of 'ALPHA'."""
    from fastapi import HTTPException

    user_setting = await _seed_user_setting(direct_db)
    await _seed_term(direct_db, user_setting.id, "Alpha")

    body = DictionaryTermCreate(term="ALPHA")
    req = _FakeRequest()
    with pytest.raises(HTTPException) as exc_info:
        await dict_module.create_term(body=body, request=req, db=direct_db)
    assert exc_info.value.status_code == 409
    assert "уже есть" in exc_info.value.detail.lower()


# ----------------------------------------------------------------------------
# update_term — direct call
# ----------------------------------------------------------------------------


async def test_update_term_direct_404_missing(direct_db):
    from fastapi import HTTPException

    body = DictionaryTermUpdate(term="ghost")
    with pytest.raises(HTTPException) as exc_info:
        await dict_module.update_term(
            term_id=uuid.uuid4(), body=body, request=_FakeRequest(), db=direct_db
        )
    assert exc_info.value.status_code == 404
    assert "не найден" in exc_info.value.detail.lower()


async def test_update_term_direct_422_empty_payload(direct_db):
    """No fields provided → 422 UNPROCESSABLE_ENTITY."""
    from fastapi import HTTPException

    user_setting = await _seed_user_setting(direct_db)
    term = await _seed_term(direct_db, user_setting.id, "baseline")

    body = DictionaryTermUpdate()  # no fields
    with pytest.raises(HTTPException) as exc_info:
        await dict_module.update_term(
            term_id=term.id, body=body, request=_FakeRequest(), db=direct_db
        )
    assert exc_info.value.status_code == 422


async def test_update_term_direct_renames_with_collision(direct_db):
    """Renaming into another term's name (case-insensitive) → 409."""
    from fastapi import HTTPException

    user_setting = await _seed_user_setting(direct_db)
    a = await _seed_term(direct_db, user_setting.id, "alpha")
    await _seed_term(direct_db, user_setting.id, "bravo")

    body = DictionaryTermUpdate(term="BRAVO")
    with pytest.raises(HTTPException) as exc_info:
        await dict_module.update_term(
            term_id=a.id, body=body, request=_FakeRequest(), db=direct_db
        )
    assert exc_info.value.status_code == 409


async def test_update_term_direct_renames_to_same_value_lower(direct_db):
    """Updating term to same text in different case must NOT trigger dup check.

    The `new_term.lower() != term.term.lower()` guard skips the duplicate SELECT
    when the new term (lower-cased) equals the current one.
    """
    user_setting = await _seed_user_setting(direct_db)
    a = await _seed_term(direct_db, user_setting.id, "alpha")

    body = DictionaryTermUpdate(term="ALPHA")
    resp = await dict_module.update_term(
        term_id=a.id, body=body, request=_FakeRequest(), db=direct_db
    )
    assert resp.term == "ALPHA"


async def test_update_term_direct_updates_weight_and_category(direct_db):
    user_setting = await _seed_user_setting(direct_db)
    a = await _seed_term(direct_db, user_setting.id, "alpha")

    body = DictionaryTermUpdate(category="product", weight=0.42)
    resp = await dict_module.update_term(
        term_id=a.id, body=body, request=_FakeRequest(), db=direct_db
    )
    assert resp.category == "product"
    assert float(resp.weight) == pytest.approx(0.42)


# ----------------------------------------------------------------------------
# delete_term — direct call
# ----------------------------------------------------------------------------


async def test_delete_term_direct_happy_path(direct_db):
    from sqlalchemy import select

    user_setting = await _seed_user_setting(direct_db)
    term = await _seed_term(direct_db, user_setting.id, "doomed")

    await dict_module.delete_term(term_id=term.id, request=_FakeRequest(), db=direct_db)

    row = (
        await direct_db.execute(select(Dictionary).where(Dictionary.id == term.id))
    ).scalar_one_or_none()
    assert row is None


async def test_delete_term_direct_404_missing(direct_db):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await dict_module.delete_term(
            term_id=uuid.uuid4(), request=_FakeRequest(), db=direct_db
        )
    assert exc_info.value.status_code == 404
    assert "не найден" in exc_info.value.detail.lower()