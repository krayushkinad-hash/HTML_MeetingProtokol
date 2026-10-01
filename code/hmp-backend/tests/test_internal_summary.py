"""Coverage tests for app/routers/summary.py — targets 50%+.

Endpoints covered:
- GET  /api/v1/hmp/protocols/{protocol_id}/summary  (null/absent/existing/deleted)
- POST /api/v1/hmp/ai/summarize                     (create / regenerate / 404 / 422)
"""
from __future__ import annotations

import uuid
from datetime import date as date_cls, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.db.models import Protocol, ProtocolStatus, Summary, Utterance

pytestmark = pytest.mark.asyncio


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
async def make_factory(db_engine):
    sm = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def _make(model_cls, **kwargs):
        async with sm() as s:
            obj = model_cls(**kwargs)
            s.add(obj)
            await s.commit()
            # Load column attrs so the instance stays usable after session closes
            mapper = obj.__mapper__
            for col in mapper.columns:
                getattr(obj, col.key)
            return obj

    return _make


async def _make_protocol(make_factory, **overrides) -> Protocol:
    defaults = dict(
        id=uuid.uuid4(),
        title="Summary Test Protocol",
        status=ProtocolStatus.LOADED.value if hasattr(ProtocolStatus, "LOADED") else "loaded",
        date=date_cls(2026, 2, 1),
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return await make_factory(Protocol, **defaults)


async def _make_utterance(make_factory, protocol_id, start=0.0, text="Hello world"):
    return await make_factory(
        Utterance,
        id=uuid.uuid4(),
        protocol_id=protocol_id,
        start_sec=start,
        end_sec=start + 1.0,
        text=text,
    )


# ============================================================================
# GET /protocols/{protocol_id}/summary
# ============================================================================

async def test_get_summary_protocol_not_found_returns_null(client: AsyncClient):
    """Missing protocol → endpoint returns None (200 with null body)."""
    r = await client.get(f"/api/v1/hmp/protocols/{uuid.uuid4()}/summary")
    assert r.status_code == 200
    assert r.json() is None


async def test_get_summary_no_summary_yet_returns_null(client: AsyncClient, make_factory):
    """Protocol exists but summary not generated yet → None."""
    p = await _make_protocol(make_factory)
    r = await client.get(f"/api/v1/hmp/protocols/{p.id}/summary")
    assert r.status_code == 200
    assert r.json() is None


async def test_get_summary_protocol_soft_deleted_returns_null(client: AsyncClient, make_factory):
    """Soft-deleted protocol → null (treated like missing)."""
    p = await _make_protocol(make_factory, deleted_at=datetime.now(timezone.utc))
    r = await client.get(f"/api/v1/hmp/protocols/{p.id}/summary")
    assert r.status_code == 200
    assert r.json() is None


async def test_get_summary_existing_returns_object(client: AsyncClient, make_factory):
    """Pre-seeded summary row → endpoint returns SummaryResponse shape."""
    p = await _make_protocol(make_factory)
    await make_factory(
        Summary,
        id=uuid.uuid4(),
        protocol_id=p.id,
        text="Саммари для теста.",
        provider="hermes",
        model="hermes-v1",
        tokens_used=42,
        generated_at=datetime.now(timezone.utc),
        regenerated=0,
    )
    r = await client.get(f"/api/v1/hmp/protocols/{p.id}/summary")
    assert r.status_code == 200
    body = r.json()
    assert body is not None
    assert body["protocol_id"] == str(p.id)
    assert body["text"] == "Саммари для теста."
    assert body["provider"] == "hermes"
    assert body["tokens_used"] == 42
    assert body["regenerated"] == 0


async def test_get_summary_invalid_uuid_422(client: AsyncClient):
    """Non-UUID path param → 422 validation error."""
    r = await client.get("/api/v1/hmp/protocols/not-a-uuid/summary")
    assert r.status_code == 422


# ============================================================================
# POST /ai/summarize — create
# ============================================================================

async def test_create_summary_basic(client: AsyncClient, make_factory):
    """First-time generation creates a Summary row and returns 201."""
    p = await _make_protocol(make_factory)
    await _make_utterance(make_factory, p.id, start=0.0, text="Первая реплика.")

    r = await client.post(
        "/api/v1/hmp/ai/summarize",
        json={"protocol_id": str(p.id), "style": "brief", "max_words": 200},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["protocol_id"] == str(p.id)
    assert body["provider"] == "hermes"
    assert "MOCK" in body["text"]
    assert body["tokens_used"] is not None and body["tokens_used"] > 0
    assert "generated_at" in body


async def test_create_summary_detailed_style(client: AsyncClient, make_factory):
    """style='detailed' → text contains the 'Подробное саммари' prefix."""
    p = await _make_protocol(make_factory)
    await _make_utterance(make_factory, p.id, text="Развёрнутое содержание встречи.")
    r = await client.post(
        "/api/v1/hmp/ai/summarize",
        json={"protocol_id": str(p.id), "style": "detailed", "max_words": 500},
    )
    assert r.status_code == 201
    assert "Подробное саммари" in r.json()["text"]


async def test_create_summary_structured_style(client: AsyncClient, make_factory):
    """style='structured' → text contains 'Структурированное саммари' prefix."""
    p = await _make_protocol(make_factory)
    await _make_utterance(make_factory, p.id)
    r = await client.post(
        "/api/v1/hmp/ai/summarize",
        json={"protocol_id": str(p.id), "style": "structured", "max_words": 500},
    )
    assert r.status_code == 201
    assert "Структурированное саммари" in r.json()["text"]


async def test_create_summary_empty_transcript(client: AsyncClient, make_factory):
    """Protocol with no utterances → still succeeds, snippet marker '[пусто]'."""
    p = await _make_protocol(make_factory)
    r = await client.post(
        "/api/v1/hmp/ai/summarize",
        json={"protocol_id": str(p.id), "style": "brief", "max_words": 200},
    )
    assert r.status_code == 201
    body = r.json()
    assert "[пусто]" in body["text"]


# ============================================================================
# POST /ai/summarize — regenerate
# ============================================================================

async def test_regenerate_summary_updates_row(client: AsyncClient, make_factory):
    """Second call updates the same row (same id) and changes the text."""
    p = await _make_protocol(make_factory)
    await _make_utterance(make_factory, p.id, text="Изначальный текст.")

    first = await client.post(
        "/api/v1/hmp/ai/summarize",
        json={"protocol_id": str(p.id), "style": "brief", "max_words": 200},
    )
    assert first.status_code == 201
    first_id = first.json()["id"]

    second = await client.post(
        "/api/v1/hmp/ai/summarize",
        json={"protocol_id": str(p.id), "style": "detailed", "max_words": 500},
    )
    assert second.status_code == 201
    body = second.json()
    assert body["id"] == first_id  # same row updated
    assert "Подробное саммари" in body["text"]

    # GET endpoint exposes regenerated counter (SummaryResponse includes it)
    fetched = await client.get(f"/api/v1/hmp/protocols/{p.id}/summary")
    assert fetched.status_code == 200
    assert fetched.json()["regenerated"] == 1


# ============================================================================
# POST /ai/summarize — error cases
# ============================================================================

async def test_create_summary_protocol_not_found_404(client: AsyncClient):
    """Unknown protocol → 404."""
    r = await client.post(
        "/api/v1/hmp/ai/summarize",
        json={"protocol_id": str(uuid.uuid4()), "style": "brief"},
    )
    assert r.status_code == 404
    assert "Протокол не найден" in (r.json().get("detail") or "")


async def test_create_summary_soft_deleted_404(client: AsyncClient, make_factory):
    """Soft-deleted protocol → 404."""
    p = await _make_protocol(make_factory, deleted_at=datetime.now(timezone.utc))
    r = await client.post(
        "/api/v1/hmp/ai/summarize",
        json={"protocol_id": str(p.id), "style": "brief"},
    )
    assert r.status_code == 404


async def test_create_summary_invalid_style_422(client: AsyncClient, make_factory):
    """style not in Literal['brief','detailed','structured'] → 422."""
    p = await _make_protocol(make_factory)
    r = await client.post(
        "/api/v1/hmp/ai/summarize",
        json={"protocol_id": str(p.id), "style": "haiku", "max_words": 300},
    )
    assert r.status_code == 422


async def test_create_summary_max_words_out_of_range_422(client: AsyncClient, make_factory):
    """max_words < 100 or > 2000 → 422 (ge/le constraint)."""
    p = await _make_protocol(make_factory)
    r = await client.post(
        "/api/v1/hmp/ai/summarize",
        json={"protocol_id": str(p.id), "style": "brief", "max_words": 50},
    )
    assert r.status_code == 422


async def test_create_summary_missing_protocol_id_422(client: AsyncClient):
    """Required field missing → 422."""
    r = await client.post(
        "/api/v1/hmp/ai/summarize",
        json={"style": "brief", "max_words": 200},
    )
    assert r.status_code == 422