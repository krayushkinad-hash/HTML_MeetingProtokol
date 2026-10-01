"""V1 coverage test for app/routers/ai.py — targets 50%+.

Endpoints covered:
- POST /ai/cleanup-text
- POST /ai/restore-punctuation
- POST /ai/review-transcript
- POST /ai/extract-decisions
- POST /ai/semantic-search
- POST /ai/translate
- POST /ai/check-grammar
- 404 / 422 error cases
"""
from __future__ import annotations

import uuid
from datetime import date as date_cls, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.db.models import Protocol, ProtocolStatus, Speaker, Utterance

pytestmark = pytest.mark.asyncio


# ============================================================================
# Fixtures — create objects in their own session to avoid clashing with
# the client fixture's session.
# ============================================================================

@pytest.fixture
async def make_factory(db_engine):
    sm = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def _make(model_cls, refresh: bool = True, **kwargs):
        async with sm() as s:
            obj = model_cls(**kwargs)
            s.add(obj)
            await s.commit()
            if refresh:
                # expire happens after commit; explicitly load all column attrs
                # so the instance remains usable after `s` closes.
                mapper = obj.__mapper__
                for col in mapper.columns:
                    getattr(obj, col.key)
            return obj

    return _make


async def _make_protocol(make_factory, **overrides) -> Protocol:
    defaults = dict(
        id=uuid.uuid4(),
        title="AI Test Protocol",
        status=ProtocolStatus.LOADED.value if hasattr(ProtocolStatus, "LOADED") else "loaded",
        date=date_cls(2026, 1, 15),
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return await make_factory(Protocol, **defaults)


async def _make_speaker(make_factory, protocol_id) -> Speaker:
    return await make_factory(
        Speaker,
        id=uuid.uuid4(),
        protocol_id=protocol_id,
        speaker_label="SPK_AI",
    )


async def _make_utterance(make_factory, protocol_id, speaker_id, text="Default", start=0.0, end=1.0, translation=None, lang=None):
    return await make_factory(
        Utterance,
        id=uuid.uuid4(),
        protocol_id=protocol_id,
        speaker_id=speaker_id,
        start_sec=start,
        end_sec=end,
        text=text,
        translation_text=translation,
        translation_language=lang,
    )


# ============================================================================
# /ai/cleanup-text
# ============================================================================

async def test_cleanup_text_basic(client: AsyncClient):
    r = await client.post("/api/v1/hmp/ai/cleanup-text", json={"text": "привет как дела"})
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "привет как дела"
    assert body["changed"] is False
    assert body["provider"] == "mock"
    assert "MOCK" in (body.get("notes") or "")


async def test_cleanup_text_with_protocol_id(client: AsyncClient, make_factory):
    p = await _make_protocol(make_factory)
    r = await client.post(
        "/api/v1/hmp/ai/cleanup-text",
        json={"text": "hello world", "protocol_id": str(p.id)},
    )
    assert r.status_code == 200
    assert r.json()["provider"] == "mock"


async def test_cleanup_text_protocol_404(client: AsyncClient):
    r = await client.post(
        "/api/v1/hmp/ai/cleanup-text",
        json={"text": "hi", "protocol_id": str(uuid.uuid4())},
    )
    assert r.status_code == 404


async def test_cleanup_text_empty_text_422(client: AsyncClient):
    r = await client.post("/api/v1/hmp/ai/cleanup-text", json={"text": ""})
    assert r.status_code == 422


# ============================================================================
# /ai/restore-punctuation
# ============================================================================

async def test_restore_punctuation_basic(client: AsyncClient):
    r = await client.post(
        "/api/v1/hmp/ai/restore-punctuation",
        json={"text": "привет как дела у тебя"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["changed"] is False
    assert body["provider"] == "mock"


async def test_restore_punctuation_with_protocol(client: AsyncClient, make_factory):
    p = await _make_protocol(make_factory)
    r = await client.post(
        "/api/v1/hmp/ai/restore-punctuation",
        json={"text": "asr text fragment", "protocol_id": str(p.id)},
    )
    assert r.status_code == 200


# ============================================================================
# /ai/review-transcript
# ============================================================================

async def test_review_transcript_basic(client: AsyncClient):
    r = await client.post(
        "/api/v1/hmp/ai/review-transcript",
        json={"text": "Расшифровка встречи: всё ок"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["quality_score"] == 1.0
    assert body["issues"] == []
    assert body["provider"] == "mock"


async def test_review_transcript_with_protocol(client: AsyncClient, make_factory):
    p = await _make_protocol(make_factory)
    r = await client.post(
        "/api/v1/hmp/ai/review-transcript",
        json={"text": "sample transcript", "protocol_id": str(p.id)},
    )
    assert r.status_code == 200
    assert r.json()["reviewed_text"] == "sample transcript"


# ============================================================================
# /ai/extract-decisions
# ============================================================================

async def test_extract_decisions_with_keywords(client: AsyncClient, make_factory):
    """Hits the keyword-matching branch via inline text (DB-load path is harder to test
    reliably because of cross-session visibility, but the same code is exercised
    by the inline-text test below)."""
    p = await _make_protocol(make_factory)
    inline_text = (
        "Вводная строка без ключевых слов.\n"
        "Мы решили продолжить работу над проектом.\n"
        "Команда договорилась о следующей встрече.\n"
        "Принято решение о бюджете.\n"
        "Заключительная строка без ключевых слов."
    )
    r = await client.post(
        "/api/v1/hmp/ai/extract-decisions",
        json={"protocol_id": str(p.id), "text": inline_text, "min_confidence": 0.5},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "mock"
    assert body["total_found"] >= 2
    assert len(body["decisions"]) >= 2
    # each decision has confidence & rationale
    for d in body["decisions"]:
        assert "confidence" in d
        assert "rationale" in d
        assert d["priority"] == "medium"
        assert d["confidence"] >= 0.5


async def test_extract_decisions_with_inline_text(client: AsyncClient, make_factory):
    """Uses the `text` field instead of loading from DB."""
    p = await _make_protocol(make_factory)
    inline_text = (
        "Вводная часть без ключевых слов совсем.\n"
        "Принято решение продолжить работу над проектом.\n"
        "Заключительная строка."
    )
    r = await client.post(
        "/api/v1/hmp/ai/extract-decisions",
        json={"protocol_id": str(p.id), "text": inline_text, "min_confidence": 0.5},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_found"] >= 1
    assert body["decisions"][0]["text"].startswith("Принято")


async def test_extract_decisions_min_confidence_filter(client: AsyncClient, make_factory):
    """min_confidence too high → empty result."""
    p = await _make_protocol(make_factory)
    r = await client.post(
        "/api/v1/hmp/ai/extract-decisions",
        json={
            "protocol_id": str(p.id),
            "text": "Мы решили что-то сделать важное",
            "min_confidence": 0.99,
        },
    )
    assert r.status_code == 200
    # confidence from one keyword ≈ 0.6, so filtered out
    assert r.json()["total_found"] == 0


async def test_extract_decisions_unknown_protocol_returns_empty(client: AsyncClient):
    """extract-decisions does NOT call _ensure_protocol — unknown protocol
    yields zero *DB-loaded* decisions but keyword-search still runs on inline text."""
    # Without text field, DB has no utterances → total_found == 0
    r = await client.post(
        "/api/v1/hmp/ai/extract-decisions",
        json={"protocol_id": str(uuid.uuid4())},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_found"] == 0
    assert body["decisions"] == []
    assert body["provider"] == "mock"


# ============================================================================
# /ai/semantic-search
# ============================================================================

async def test_semantic_search_basic(client: AsyncClient):
    r = await client.post(
        "/api/v1/hmp/ai/semantic-search",
        json={"query": "budget planning", "top_k": 5},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "budget planning"
    assert body["hits"] == []
    assert body["provider"] == "mock"


async def test_semantic_search_with_protocol(client: AsyncClient, make_factory):
    p = await _make_protocol(make_factory)
    r = await client.post(
        "/api/v1/hmp/ai/semantic-search",
        json={"query": "deadlines", "protocol_id": str(p.id), "top_k": 3},
    )
    assert r.status_code == 200
    assert r.json()["query"] == "deadlines"


async def test_semantic_search_top_k_validation(client: AsyncClient):
    """top_k > 50 → 422."""
    r = await client.post(
        "/api/v1/hmp/ai/semantic-search",
        json={"query": "x", "top_k": 999},
    )
    assert r.status_code == 422


# ============================================================================
# /ai/translate
# ============================================================================

async def test_translate_basic_new(client: AsyncClient, make_factory):
    """No cache → all 'new'."""
    p = await _make_protocol(make_factory)
    s = await _make_speaker(make_factory, p.id)
    await _make_utterance(make_factory, p.id, s.id, text="Привет", start=0.0, end=1.0)
    await _make_utterance(make_factory, p.id, s.id, text="Как дела", start=1.0, end=2.0)

    r = await client.post(
        "/api/v1/hmp/ai/translate",
        json={"protocol_id": str(p.id), "target_language": "en"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["new"] == 2
    assert body["cached"] == 0
    assert body["total"] == 2
    assert body["target_language"] == "en"
    for t in body["translations"]:
        assert t["translation_text"].startswith("[en]")


async def test_translate_cache_hit(client: AsyncClient, make_factory):
    """Already translated → 'cached' counter increments."""
    p = await _make_protocol(make_factory)
    s = await _make_speaker(make_factory, p.id)
    await _make_utterance(
        make_factory, p.id, s.id, text="Привет",
        start=0.0, end=1.0, translation="[en] Hello", lang="en",
    )

    r = await client.post(
        "/api/v1/hmp/ai/translate",
        json={"protocol_id": str(p.id), "target_language": "en"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["cached"] == 1
    assert body["new"] == 0


async def test_translate_utterance_ids_filter(client: AsyncClient, make_factory):
    """utterance_ids filters the set."""
    p = await _make_protocol(make_factory)
    s = await _make_speaker(make_factory, p.id)
    u1 = await _make_utterance(make_factory, p.id, s.id, text="A", start=0.0, end=1.0)
    await _make_utterance(make_factory, p.id, s.id, text="B", start=1.0, end=2.0)

    r = await client.post(
        "/api/v1/hmp/ai/translate",
        json={
            "protocol_id": str(p.id),
            "target_language": "en",
            "utterance_ids": [str(u1.id)],
        },
    )
    assert r.status_code == 200
    assert r.json()["total"] == 1


async def test_translate_protocol_404(client: AsyncClient):
    r = await client.post(
        "/api/v1/hmp/ai/translate",
        json={"protocol_id": str(uuid.uuid4()), "target_language": "en"},
    )
    assert r.status_code == 404


async def test_translate_empty_utterances(client: AsyncClient, make_factory):
    """Protocol exists but has no utterances."""
    p = await _make_protocol(make_factory)
    r = await client.post(
        "/api/v1/hmp/ai/translate",
        json={"protocol_id": str(p.id), "target_language": "en"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["translations"] == []


async def test_translate_target_language_422(client: AsyncClient):
    r = await client.post(
        "/api/v1/hmp/ai/translate",
        json={"protocol_id": str(uuid.uuid4()), "target_language": "x"},
    )
    assert r.status_code == 422


# ============================================================================
# /ai/check-grammar
# ============================================================================

async def test_check_grammar_double_space(client: AsyncClient):
    r = await client.post(
        "/api/v1/hmp/ai/check-grammar",
        json={"text": "привет  как дела"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["issue_count"] >= 1
    rules = {i["rule_id"] for i in body["issues"]}
    assert "DOUBLE_SPACE" in rules


async def test_check_grammar_typo(client: AsyncClient):
    r = await client.post(
        "/api/v1/hmp/ai/check-grammar",
        json={"text": "Это координально неправильно"},
    )
    assert r.status_code == 200
    body = r.json()
    rules = {i["rule_id"] for i in body["issues"]}
    assert "TYPO" in rules


async def test_check_grammar_no_issues(client: AsyncClient):
    r = await client.post(
        "/api/v1/hmp/ai/check-grammar",
        json={"text": "Всё хорошо."},
    )
    assert r.status_code == 200
    assert r.json()["issue_count"] == 0


async def test_check_grammar_with_utterance_id(client: AsyncClient):
    r = await client.post(
        "/api/v1/hmp/ai/check-grammar",
        json={"text": "тест", "utterance_id": str(uuid.uuid4()), "language": "en"},
    )
    assert r.status_code == 200
    assert r.json()["language"] == "en"