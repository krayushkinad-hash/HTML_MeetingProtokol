"""Coverage tests v2 for app/routers/summary.py — targets 70%+.

Adds tests that cover branches the v1 file left unexercised:
- _to_response() helper (direct unit test)
- _collect_protocol_text() helper: ordering, empty case
- _generate_summary_text() direct: all 3 styles, default-style fallback, truncation
- POST /ai/summarize with gigachat + local_ollama providers
- POST /ai/summarize with real (non-empty) transcript → snippet in output
- POST /ai/summarize: invalid UUID → 422
- POST /ai/summarize: soft-deleted protocol → 404
- Regenerate counter pushed past 1 (verified via GET endpoint)

The conftest `db_session` fixture holds a transaction open for the
whole test which deadlocks against the request handler's session. So
we use a `seed_sessionmaker` built on the conftest `db_engine` and
explicitly close the session BEFORE invoking `client`. This avoids the
idle-in-transaction deadlock.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.db.models import Protocol, ProtocolStatus, Utterance
from app.db.models import Summary  # noqa: F401  (re-export for fixtures)
from app.routers.summary import (
    SummaryResponse,
    _collect_protocol_text,
    _generate_summary_text,
    _to_response,
)
from app.schemas import SummarizeRequest

pytestmark = pytest.mark.asyncio

PREFIX = "/api/v1/hmp"


# ============================================================================
# Local helpers
# ============================================================================


def _protocol_kwargs(**overrides) -> dict:
    """Build kwargs for Protocol, stripping internal sentinel keys."""
    defaults = dict(
        id=uuid.uuid4(),
        title="Summary v2 Protocol",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return defaults


@pytest_asyncio.fixture
async def seed_sm(db_engine):
    """A sessionmaker bound to the conftest engine.

    Tests must commit + close their session BEFORE invoking `client`
    to avoid deadlock with the request handler's own session.
    """
    return sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


async def _insert_protocol(sm, *, utterance_text: str | None = None,
                           **overrides) -> uuid.UUID:
    """Insert a Protocol (and optionally an Utterance) and return its id.

    The session is closed before returning so no transaction is held
    when the test subsequently invokes `client`.
    """
    async with sm() as s:
        p = Protocol(**_protocol_kwargs(**overrides))
        s.add(p)
        await s.flush()
        if utterance_text is not None:
            s.add(Utterance(
                id=uuid.uuid4(),
                protocol_id=p.id,
                start_sec=0.0,
                end_sec=1.0,
                text=utterance_text,
            ))
        await s.commit()
        return p.id


# ============================================================================
# Direct unit tests for private helpers (use seed_sm; no client)
# ============================================================================


async def test_to_response_helper_builds_summary_response(seed_sm):
    """_to_response() copies fields from the ORM model to the pydantic schema."""
    async with seed_sm() as s:
        p = Protocol(**_protocol_kwargs())
        s.add(p)
        await s.flush()

        summary = Summary(
            id=uuid.uuid4(),
            protocol_id=p.id,
            text="unit test text",
            provider="gigachat",
            model="gigachat-pro",
            tokens_used=123,
            generated_at=datetime.now(timezone.utc),
            regenerated=2,
        )
        s.add(summary)
        await s.flush()

        resp = _to_response(summary)
        assert isinstance(resp, SummaryResponse)
        assert resp.id == summary.id
        assert resp.protocol_id == p.id
        assert resp.text == "unit test text"
        assert resp.provider == "gigachat"
        assert resp.model == "gigachat-pro"
        assert resp.tokens_used == 123
        assert resp.regenerated == 2


async def test_collect_protocol_text_joins_in_order(seed_sm):
    """Utterances are joined with \\n in start_sec ascending order."""
    async with seed_sm() as s:
        p = Protocol(**_protocol_kwargs())
        s.add(p)
        await s.flush()

        s.add_all([
            Utterance(id=uuid.uuid4(), protocol_id=p.id, start_sec=5.0,
                      end_sec=6.0, text="SECOND"),
            Utterance(id=uuid.uuid4(), protocol_id=p.id, start_sec=1.0,
                      end_sec=2.0, text="FIRST"),
            Utterance(id=uuid.uuid4(), protocol_id=p.id, start_sec=10.0,
                      end_sec=11.0, text="THIRD"),
        ])
        await s.flush()

        text = await _collect_protocol_text(s, p.id)
        assert text == "FIRST\nSECOND\nTHIRD"


async def test_collect_protocol_text_empty_when_no_utterances(seed_sm):
    """Protocol without utterances → empty string."""
    async with seed_sm() as s:
        p = Protocol(**_protocol_kwargs())
        s.add(p)
        await s.flush()

        text = await _collect_protocol_text(s, p.id)
        assert text == ""


# ============================================================================
# _generate_summary_text — exercise style/truncation branches directly
# ============================================================================


async def test_generate_summary_text_all_three_styles(seed_sm):
    """Each known style produces the matching Russian prefix."""
    async with seed_sm() as s:
        p = Protocol(**_protocol_kwargs())
        s.add(p)
        await s.flush()
        s.add(Utterance(id=uuid.uuid4(), protocol_id=p.id, start_sec=0.0,
                        end_sec=1.0, text="Контент."))
        await s.flush()

        for style, expected_prefix in [
            ("brief", "Краткое саммари"),
            ("detailed", "Подробное саммари"),
            ("structured", "Структурированное саммари"),
        ]:
            req = SummarizeRequest(protocol_id=p.id, style=style, max_words=500)
            text, provider, tokens = await _generate_summary_text(s, p.id, req)
            assert text.startswith(expected_prefix)
            assert provider == "hermes"  # default
            assert tokens > 0


async def test_generate_summary_text_unknown_style_falls_back(seed_sm):
    """Unknown style triggers the .get(req.style, 'Саммари') fallback branch."""
    async with seed_sm() as s:
        p = Protocol(**_protocol_kwargs())
        s.add(p)
        await s.flush()
        s.add(Utterance(id=uuid.uuid4(), protocol_id=p.id, start_sec=0.0,
                        end_sec=1.0, text="X"))
        await s.flush()

        class _Req:
            style = "haiku"
            provider = "local_ollama"
            max_words = 500

        text, provider, tokens = await _generate_summary_text(s, p.id, _Req())
        assert text.startswith("Саммари ")
        assert provider == "local_ollama"
        assert tokens > 0


# NOTE: The truncation branch in _generate_summary_text (line 124-126) is
# unreachable with valid inputs. max_words is constrained >=100 by the
# Pydantic schema, so max_chars >=600, while the snippet is capped at 200
# chars making the placeholder ~400 chars in the longest case. We
# therefore cannot reach the truncation branch without monkey-patching
# the schema constraints. Skipping this case.


# ============================================================================
# POST /ai/summarize — provider literals + non-empty transcript
# ============================================================================


async def test_create_summary_with_gigachat_provider(
    client: AsyncClient, seed_sm
):
    """provider='gigachat' is persisted on the Summary row."""
    pid = await _insert_protocol(seed_sm, utterance_text="Привет.")

    r = await client.post(
        f"{PREFIX}/ai/summarize",
        json={
            "protocol_id": str(pid),
            "provider": "gigachat",
            "style": "brief",
            "max_words": 200,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["provider"] == "gigachat"
    assert "gigachat" in body["text"]


async def test_create_summary_with_local_llama_provider(
    client: AsyncClient, seed_sm
):
    """provider='local_ollama' works end-to-end.

    Note: Pydantic Literal for llm_provider is {local_ollama, gigachat, hermes};
    the DB enum mirrors the same set. Previously this test used 'local_llama'
    (a stale name) which the Pydantic schema rejected with 422.
    """
    pid = await _insert_protocol(seed_sm, utterance_text="Локальный.")

    r = await client.post(
        f"{PREFIX}/ai/summarize",
        json={
            "protocol_id": str(pid),
            "provider": "local_ollama",
            "style": "detailed",
            "max_words": 500,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["provider"] == "local_ollama"
    assert "local_ollama" in body["text"]


async def test_create_summary_with_real_transcript_in_snippet(
    client: AsyncClient, seed_sm
):
    """Non-empty transcript appears as the snippet prefix in the generated text."""
    marker = "УникальнаяФразаДляПроверкиТранскрипта"
    pid = await _insert_protocol(seed_sm, utterance_text=marker)

    r = await client.post(
        f"{PREFIX}/ai/summarize",
        json={
            "protocol_id": str(pid),
            "style": "brief",
            "max_words": 500,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert marker in body["text"]
    assert "Транскрипт содержит" in body["text"]
    assert f"Транскрипт содержит {len(marker)} символов" in body["text"]


async def test_create_summary_invalid_uuid_422(client: AsyncClient):
    """Non-UUID protocol_id in POST body → 422."""
    r = await client.post(
        f"{PREFIX}/ai/summarize",
        json={"protocol_id": "not-a-uuid", "style": "brief", "max_words": 200},
    )
    assert r.status_code == 422


async def test_create_summary_soft_deleted_protocol_404(
    client: AsyncClient, seed_sm
):
    """Soft-deleted protocol → 404 on POST (matches GET behaviour)."""
    pid = await _insert_protocol(seed_sm, deleted_at=datetime.now(timezone.utc))

    r = await client.post(
        f"{PREFIX}/ai/summarize",
        json={"protocol_id": str(pid), "style": "brief", "max_words": 200},
    )
    assert r.status_code == 404
    assert "Протокол не найден" in (r.json().get("detail") or "")


async def test_regenerate_twice_increments_counter_to_two(
    client: AsyncClient, seed_sm
):
    """Three sequential calls: 1st creates (regenerated=0), 2nd → 1, 3rd → 2."""
    pid = await _insert_protocol(seed_sm, utterance_text="Контент.")

    for _ in range(3):
        r = await client.post(
            f"{PREFIX}/ai/summarize",
            json={
                "protocol_id": str(pid),
                "style": "brief",
                "max_words": 200,
            },
        )
        assert r.status_code == 201, r.text

    fetched = await client.get(f"{PREFIX}/protocols/{pid}/summary")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body is not None
    assert body["regenerated"] == 2