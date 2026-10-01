"""V2 coverage test for app/routers/ai.py — targets 90%+.

Adds branch coverage beyond test_internal_ai.py:

  * _ensure_protocol with protocol.deleted_at != None → 404
  * extract-decisions: DB-load branch (text=None) — loads utterances from DB
  * extract-decisions: multi-keyword match → confidence capped at 0.95
  * extract-decisions: short-line skip (line length < 5)
  * translate: cache miss → translation_language mismatch → new path
  * translate: persists translation_text + translation_language on Utterance
  * translate: updates Protocol.translation_language
  * translate: mixed cached/new
  * check-grammar: SPACE_BEFORE_PUNCT branch
  * check-grammar: NO_SPACE_AFTER_PUNCT branch (incl. start==0 skip)
  * check-grammar: CAPITAL_AFTER_DOT branch
  * check-grammar: multiple TYPO branches
  * check-grammar: corrected text differs from input
  * check-grammar: language echo + utterance_id accepted

Design note: this file uses a single session-scoped engine + AsyncClient
to avoid per-test TRUNCATE deadlocks on the test DB. Each test creates
rows via the shared engine (cleanup is best-effort via DELETE in the
fixture finalizer).
"""
from __future__ import annotations

import os
import uuid
from datetime import date as date_cls, datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete as _delete, select as _select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Protocol, ProtocolStatus, Speaker, Utterance
from app.db.session import get_db
from app.main import app

pytestmark = pytest.mark.asyncio

PREFIX = "/api/v1/hmp"

TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://hmp:hmp_password@localhost:5432/html_mp_test",
)


@pytest_asyncio.fixture(scope="function")
async def ctx():
    """Per-test engine + AsyncClient. Each test owns its own engine/pool,
    avoiding cross-test transaction/connection leakage."""
    eng = create_async_engine(TEST_DATABASE_URL, echo=False, pool_size=10, max_overflow=20)
    sm = sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with sm() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                # Force a clean state for next request
                try:
                    await session.close()
                except Exception:
                    pass

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield sm, ac
    app.dependency_overrides.clear()
    await eng.dispose()


async def _make_protocol(ctx, **overrides) -> Protocol:
    sm, _ = ctx
    defaults = dict(
        id=uuid.uuid4(),
        title="AI V2 Protocol",
        status=ProtocolStatus.LOADED.value,
        date=date_cls(2026, 2, 20),
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    async with sm() as s:
        obj = Protocol(**defaults)
        s.add(obj)
        await s.commit()
        await s.refresh(obj)
        return obj


async def _make_speaker(ctx, protocol_id) -> Speaker:
    sm, _ = ctx
    async with sm() as s:
        obj = Speaker(id=uuid.uuid4(), protocol_id=protocol_id, speaker_label="SPK_V2")
        s.add(obj)
        await s.commit()
        await s.refresh(obj)
        return obj


async def _make_utterance(
    ctx, protocol_id, speaker_id,
    text="Sample", start=0.0, end=1.0, translation=None, lang=None,
):
    sm, _ = ctx
    async with sm() as s:
        obj = Utterance(
            id=uuid.uuid4(),
            protocol_id=protocol_id,
            speaker_id=speaker_id,
            start_sec=start,
            end_sec=end,
            text=text,
            translation_text=translation,
            translation_language=lang,
        )
        s.add(obj)
        await s.commit()
        await s.refresh(obj)
        return obj


# ===========================================================================
# _ensure_protocol — soft-deleted protocol → 404
# ===========================================================================

async def test_ensure_protocol_soft_deleted_404(ctx):
    """Protocol exists but deleted_at is set → 404 (covers the
    `protocol.deleted_at is not None` branch in _ensure_protocol)."""
    _, ac = ctx
    p = await _make_protocol(ctx, deleted_at=datetime.now(timezone.utc))
    r = await ac.post(
        f"{PREFIX}/ai/cleanup-text",
        json={"text": "hello", "protocol_id": str(p.id)},
    )
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"]


async def test_ensure_protocol_valid_cleanup_text(ctx):
    """Protocol exists + not deleted → 200 (covers the happy branch)."""
    _, ac = ctx
    p = await _make_protocol(ctx)
    r = await ac.post(
        f"{PREFIX}/ai/cleanup-text",
        json={"text": "hello world", "protocol_id": str(p.id)},
    )
    assert r.status_code == 200
    assert r.json()["provider"] == "mock"


async def test_ensure_protocol_valid_restore_punctuation(ctx):
    """Same _ensure_protocol happy branch via restore-punctuation."""
    _, ac = ctx
    p = await _make_protocol(ctx)
    r = await ac.post(
        f"{PREFIX}/ai/restore-punctuation",
        json={"text": "asr text", "protocol_id": str(p.id)},
    )
    assert r.status_code == 200


async def test_ensure_protocol_soft_deleted_review_transcript(ctx):
    """review-transcript also routes through _ensure_protocol (soft-deleted)."""
    _, ac = ctx
    p = await _make_protocol(ctx, deleted_at=datetime.now(timezone.utc))
    r = await ac.post(
        f"{PREFIX}/ai/review-transcript",
        json={"text": "ok", "protocol_id": str(p.id)},
    )
    assert r.status_code == 404


async def test_ensure_protocol_valid_semantic_search(ctx):
    """semantic-search also routes through _ensure_protocol (happy)."""
    _, ac = ctx
    p = await _make_protocol(ctx)
    r = await ac.post(
        f"{PREFIX}/ai/semantic-search",
        json={"query": "find this", "protocol_id": str(p.id), "top_k": 4},
    )
    assert r.status_code == 200
    assert r.json()["query"] == "find this"


# ===========================================================================
# /ai/extract-decisions — DB-load + multi-keyword + short-line branches
# ===========================================================================

async def test_extract_decisions_load_from_db(ctx):
    """`text=None` branch → loads utterances from DB and joins their text."""
    _, ac = ctx
    p = await _make_protocol(ctx)
    s = await _make_speaker(ctx, p.id)
    await _make_utterance(
        ctx, p.id, s.id,
        start=0.0, end=1.0, text="Вводная строка без ключевых слов вовсе",
    )
    await _make_utterance(
        ctx, p.id, s.id,
        start=1.0, end=2.0, text="Мы решили запустить новый процесс.",
    )

    r = await ac.post(
        f"{PREFIX}/ai/extract-decisions",
        json={"protocol_id": str(p.id)},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "mock"
    assert body["total_found"] == 1
    d = body["decisions"][0]
    assert d["text"].startswith("Мы решили")
    assert d["confidence"] >= 0.5
    assert d["priority"] == "medium"
    assert d["timestamp_sec"] is not None
    assert d["source_utterance_id"] is not None
    assert "решили" in d["rationale"]


async def test_extract_decisions_multi_keyword_confidence_capped(ctx):
    """Multiple keywords → confidence capped at 0.95."""
    _, ac = ctx
    p = await _make_protocol(ctx)
    inline_text = (
        "Команда решили договорились принято решение утвердили согласовали план проекта"
    )
    r = await ac.post(
        f"{PREFIX}/ai/extract-decisions",
        json={"protocol_id": str(p.id), "text": inline_text, "min_confidence": 0.5},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_found"] == 1
    assert body["decisions"][0]["confidence"] == 0.95


async def test_extract_decisions_short_line_skipped(ctx):
    """Lines with `len(line_lower) < 5` after strip → skipped."""
    _, ac = ctx
    p = await _make_protocol(ctx)
    r = await ac.post(
        f"{PREFIX}/ai/extract-decisions",
        json={"protocol_id": str(p.id), "text": "ок\nтак\n"},
    )
    assert r.status_code == 200
    assert r.json()["total_found"] == 0


async def test_extract_decisions_empty_line_skipped(ctx):
    """Empty / whitespace-only lines → skipped."""
    _, ac = ctx
    p = await _make_protocol(ctx)
    inline_text = "\n\n   \nрешили запустить процесс полностью и качественно\n"
    r = await ac.post(
        f"{PREFIX}/ai/extract-decisions",
        json={"protocol_id": str(p.id), "text": inline_text},
    )
    assert r.status_code == 200
    assert r.json()["total_found"] == 1


async def test_extract_decisions_text_truncated_at_500(ctx):
    """Decision text sliced to 500 chars max."""
    _, ac = ctx
    p = await _make_protocol(ctx)
    long_line = "решили " + "слово " * 200
    r = await ac.post(
        f"{PREFIX}/ai/extract-decisions",
        json={"protocol_id": str(p.id), "text": long_line.strip()},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_found"] == 1
    assert len(body["decisions"][0]["text"]) <= 500


# ===========================================================================
# /ai/translate — cache miss + DB persistence + protocol-language update
# ===========================================================================

async def test_translate_cache_miss_persists_utterance(ctx):
    """Utterance has translation_text=None → goes through the *new* branch."""
    sm, ac = ctx
    p = await _make_protocol(ctx)
    s = await _make_speaker(ctx, p.id)
    u = await _make_utterance(
        ctx, p.id, s.id,
        text="Hola", start=0.0, end=1.0,
        translation=None, lang=None,
    )

    r = await ac.post(
        f"{PREFIX}/ai/translate",
        json={"protocol_id": str(p.id), "target_language": "es"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["new"] == 1
    assert body["cached"] == 0
    assert body["translations"][0]["translation_text"].startswith("[es]")
    assert body["translations"][0]["translation_language"] == "es"

    async with sm() as sess:
        row = (await sess.execute(_select(Utterance).where(Utterance.id == u.id))).scalar_one()
        assert row.translation_text is not None
        assert row.translation_language == "es"


async def test_translate_updates_protocol_translation_language(ctx):
    """After translation, Protocol.translation_language is set to the target."""
    sm, ac = ctx
    p = await _make_protocol(ctx)
    s = await _make_speaker(ctx, p.id)
    await _make_utterance(ctx, p.id, s.id, text="Hola", start=0.0, end=1.0)

    r = await ac.post(
        f"{PREFIX}/ai/translate",
        json={"protocol_id": str(p.id), "target_language": "de"},
    )
    assert r.status_code == 200

    async with sm() as sess:
        row = (await sess.execute(_select(Protocol).where(Protocol.id == p.id))).scalar_one()
        assert row.translation_language == "de"


async def test_translate_mixed_cached_and_new(ctx):
    """Mixed: one cached + one new translation."""
    _, ac = ctx
    p = await _make_protocol(ctx)
    s = await _make_speaker(ctx, p.id)
    await _make_utterance(
        ctx, p.id, s.id,
        text="cached", start=0.0, end=1.0,
        translation="[en] cached-text", lang="en",
    )
    await _make_utterance(
        ctx, p.id, s.id,
        text="new one", start=1.0, end=2.0,
        translation=None, lang=None,
    )

    r = await ac.post(
        f"{PREFIX}/ai/translate",
        json={"protocol_id": str(p.id), "target_language": "en"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["cached"] == 1
    assert body["new"] == 1
    assert body["total"] == 2


# ===========================================================================
# /ai/check-grammar — every heuristic branch
# ===========================================================================

async def test_check_grammar_space_before_punct(ctx):
    """` +([,.!?:;])` → SPACE_BEFORE_PUNCT issue."""
    _, ac = ctx
    r = await ac.post(
        f"{PREFIX}/ai/check-grammar",
        json={"text": "Привет ,мир"},
    )
    assert r.status_code == 200
    body = r.json()
    rules = {i["rule_id"] for i in body["issues"]}
    assert "SPACE_BEFORE_PUNCT" in rules


async def test_check_grammar_no_space_after_punct(ctx):
    """Missing space after punct (start != 0) → NO_SPACE_AFTER_PUNCT issue."""
    _, ac = ctx
    r = await ac.post(
        f"{PREFIX}/ai/check-grammar",
        json={"text": "Привет.мир"},
    )
    assert r.status_code == 200
    body = r.json()
    rules = {i["rule_id"] for i in body["issues"]}
    assert "NO_SPACE_AFTER_PUNCT" in rules


async def test_check_grammar_no_space_after_punct_at_start_skipped(ctx):
    """When match starts at offset 0 → skipped branch."""
    _, ac = ctx
    r = await ac.post(
        f"{PREFIX}/ai/check-grammar",
        json={"text": ".привет"},
    )
    assert r.status_code == 200
    body = r.json()
    rules = {i["rule_id"] for i in body["issues"]}
    assert "NO_SPACE_AFTER_PUNCT" not in rules


async def test_check_grammar_capital_after_dot(ctx):
    """`.\\s*[а-яё]` → CAPITAL_AFTER_DOT issue."""
    _, ac = ctx
    r = await ac.post(
        f"{PREFIX}/ai/check-grammar",
        json={"text": "Конец. начало"},
    )
    assert r.status_code == 200
    body = r.json()
    rules = {i["rule_id"] for i in body["issues"]}
    assert "CAPITAL_AFTER_DOT" in rules


async def test_check_grammar_multiple_typos(ctx):
    """Multiple typos in COMMON_TYPOS → multiple TYPO issues."""
    _, ac = ctx
    r = await ac.post(
        f"{PREFIX}/ai/check-grammar",
        json={"text": "Это координально и прийдти сложно и в течении дня"},
    )
    assert r.status_code == 200
    body = r.json()
    typo_issues = [i for i in body["issues"] if i["rule_id"] == "TYPO"]
    assert len(typo_issues) >= 3
    originals = {i["original"] for i in typo_issues}
    assert "координально" in originals
    assert "прийдти" in originals
    assert "в течении дня" in originals


async def test_check_grammar_corrected_differs(ctx):
    """When issues exist, `corrected` text differs from input."""
    _, ac = ctx
    r = await ac.post(
        f"{PREFIX}/ai/check-grammar",
        json={"text": "координально  неверно"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["issue_count"] > 0
    assert body["corrected"] != body["text"]
    assert "кардинально" in body["corrected"]
    assert "  " not in body["corrected"]


async def test_check_grammar_language_and_utterance_id_echo(ctx):
    """Echoes language and accepts utterance_id."""
    _, ac = ctx
    uid = uuid.uuid4()
    r = await ac.post(
        f"{PREFIX}/ai/check-grammar",
        json={"text": "всё ок", "language": "en", "utterance_id": str(uid)},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["language"] == "en"
    assert body["provider"] == "mock"


async def test_check_grammar_no_issues_passthrough(ctx):
    """Clean text → corrected equals original, issue_count == 0."""
    _, ac = ctx
    r = await ac.post(
        f"{PREFIX}/ai/check-grammar",
        json={"text": "Всё хорошо. Да."},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["issue_count"] == 0
    assert body["corrected"] == body["text"]
    assert body["issues"] == []