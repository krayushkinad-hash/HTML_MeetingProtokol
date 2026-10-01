"""Direct-handler-call coverage tests for app/routers/tags.py.

WORKAROUND for `cov-tracking-anomaly-fastapi-lazy-imports`:
Calls `list_tags`, `create_tag`, `delete_tag` directly as Python async
functions instead of through the FastAPI HTTP layer (ASGITransport + httpx).

Root cause: pytest-cov's tracer does not record line executions on the
greenlet spawned by ASGITransport when the handler uses Depends(get_db).
Direct calls run on the test's own greenlet → tracer records every line.

See skill: ~/.hermes/profiles/alex3/skills/methodology/cov-tracking-anomaly-fastapi-lazy-imports/SKILL.md
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.db.models import Protocol, ProtocolStatus, Tag
from app.routers import tags as tags_module
from app.routers.tags import TagCreate

pytestmark = pytest.mark.asyncio

PREFIX_API = "/api/v1/hmp"


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def direct_db(db_engine):
    """Reuse conftest's db_engine — no second engine, no deadlock surface."""
    async_session = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


def _protocol_kwargs(**overrides) -> dict:
    defaults = dict(
        id=uuid.uuid4(),
        title="Tags direct-coverage Protocol",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return defaults


async def _insert_protocol(direct_db, **overrides) -> uuid.UUID:
    p = Protocol(**_protocol_kwargs(**overrides))
    direct_db.add(p)
    await direct_db.flush()
    return p.id


async def _insert_tag(direct_db, protocol_id: uuid.UUID, name: str = "seed-tag") -> Tag:
    t = Tag(
        id=uuid.uuid4(),
        protocol_id=protocol_id,
        name=name,
        source="manual",
        color=None,
    )
    direct_db.add(t)
    await direct_db.flush()
    await direct_db.refresh(t)
    return t


# Minimal Request stand-in for create_tag / delete_tag that only read
# `request.state.correlation_id`.
class _FakeRequest:
    class _State:
        correlation_id = None
    def __init__(self):
        self.state = self._State()


# ----------------------------------------------------------------------------
# list_tags — direct call
# ----------------------------------------------------------------------------


async def test_list_tags_direct_returns_sorted_dict(direct_db):
    proto_id = await _insert_protocol(direct_db)
    await _insert_tag(direct_db, proto_id, "charlie")
    await _insert_tag(direct_db, proto_id, "alpha")
    await _insert_tag(direct_db, proto_id, "bravo")

    result = await tags_module.list_tags(protocol_id=proto_id, db=direct_db)

    assert result["total"] == 3
    names = [item.name for item in result["items"]]
    assert names == ["alpha", "bravo", "charlie"]


async def test_list_tags_direct_404_missing_protocol(direct_db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await tags_module.list_tags(protocol_id=uuid.uuid4(), db=direct_db)
    assert exc_info.value.status_code == 404
    assert "не найден" in exc_info.value.detail.lower()


async def test_list_tags_direct_empty_protocol(direct_db):
    """Empty list returned when protocol exists but has no tags."""
    proto_id = await _insert_protocol(direct_db)
    result = await tags_module.list_tags(protocol_id=proto_id, db=direct_db)
    assert result == {"total": 0, "items": []}


# ----------------------------------------------------------------------------
# create_tag — direct call
# ----------------------------------------------------------------------------


async def test_create_tag_direct_happy_path(direct_db):
    proto_id = await _insert_protocol(direct_db)
    body = TagCreate(protocol_id=proto_id, name="direct-tag", color="#abcdef")
    req = _FakeRequest()

    resp = await tags_module.create_tag(body=body, request=req, db=direct_db)

    assert resp.name == "direct-tag"
    assert resp.color == "#abcdef"
    assert resp.protocol_id == proto_id
    assert resp.source == "manual"


async def test_create_tag_direct_404_missing_protocol(direct_db):
    from fastapi import HTTPException
    body = TagCreate(protocol_id=uuid.uuid4(), name="orphan")
    req = _FakeRequest()
    with pytest.raises(HTTPException) as exc_info:
        await tags_module.create_tag(body=body, request=req, db=direct_db)
    assert exc_info.value.status_code == 404


async def test_create_tag_direct_duplicate_returns_409(direct_db):
    """Duplicate (protocol_id, name) → DB unique violation → 409 from handler."""
    from fastapi import HTTPException
    proto_id = await _insert_protocol(direct_db)
    await _insert_tag(direct_db, proto_id, "dup-name")

    body = TagCreate(protocol_id=proto_id, name="dup-name")
    req = _FakeRequest()
    with pytest.raises(HTTPException) as exc_info:
        await tags_module.create_tag(body=body, request=req, db=direct_db)
    assert exc_info.value.status_code == 409
    assert "уже существует" in exc_info.value.detail.lower()


async def test_create_tag_direct_same_name_different_protocol(direct_db):
    """Tag uniqueness is per-protocol — different protocols accept the same name."""
    proto_a = await _insert_protocol(direct_db)
    proto_b = await _insert_protocol(direct_db)

    resp_a = await tags_module.create_tag(
        body=TagCreate(protocol_id=proto_a, name="shared"),
        request=_FakeRequest(),
        db=direct_db,
    )
    resp_b = await tags_module.create_tag(
        body=TagCreate(protocol_id=proto_b, name="shared"),
        request=_FakeRequest(),
        db=direct_db,
    )
    assert resp_a.id != resp_b.id
    assert resp_a.name == resp_b.name == "shared"


# ----------------------------------------------------------------------------
# delete_tag — direct call
# ----------------------------------------------------------------------------


async def test_delete_tag_direct_happy_path(direct_db):
    proto_id = await _insert_protocol(direct_db)
    tag = await _insert_tag(direct_db, proto_id, "to-delete")

    # Should not raise
    await tags_module.delete_tag(tag_id=tag.id, request=_FakeRequest(), db=direct_db)

    # Verify row removed
    from sqlalchemy import select
    result = await direct_db.execute(select(Tag).where(Tag.id == tag.id))
    assert result.scalar_one_or_none() is None


async def test_delete_tag_direct_404_missing(direct_db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await tags_module.delete_tag(tag_id=uuid.uuid4(), request=_FakeRequest(), db=direct_db)
    assert exc_info.value.status_code == 404
    assert "не найден" in exc_info.value.detail.lower()