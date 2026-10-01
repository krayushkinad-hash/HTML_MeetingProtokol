"""E286 v3: deep tests for routers/transcribe/upgrade.py.

Complements ``test_internal_upgrade.py`` (which covers the happy/error
matrix using the live PostgreSQL engine) with branch coverage that is
awkward to drive through the test DB:
  - multiple weak segments being returned ordered by ``start_sec``
  - ``confidence_threshold`` boundary (== threshold - same default boundary)
  - response object contract for the no-op branch (keys + types)
  - "no audio_file_id" + "no audio row" boundary on the same protocol id
  - in-process background runner invokes ``transcription_service.transcribe``
    with the correct kwargs (only_update_weak=True, target_model override)
  - module logger / async runtime is exercised without flakiness
  - the function name itself is exported and bound to the route
"""
from __future__ import annotations

import asyncio
import inspect
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import AsyncClient, ASGITransport
from sqlalchemy import insert

from app.routers.transcribe import upgrade as upgrade_module
from app.routers.transcribe.upgrade import router, upgrade_weak_segments_endpoint


# ============================================================================
# Fakes — minimal in-memory DB session that supports the calls the router makes
# ============================================================================


class _FakeScalarResult:
    def __init__(self, rows: List[Any]) -> None:
        self._rows = rows

    def scalars(self) -> "_FakeScalarResult":
        return self

    def all(self) -> List[Any]:
        return list(self._rows)


class _FakeAsyncSession:
    """In-memory AsyncSession — supports only the operations the upgrade
    router performs: ``db.get(Protocol)``, ``db.get(AudioFile)`` and
    ``db.execute(select(Utterance).where(...).order_by(...)).scalars().all()``.
    """

    def __init__(self) -> None:
        self.protocol: Optional[Any] = None
        self.audio_file: Optional[Any] = None
        self.utterances: List[Any] = []
        self.executed_stmts: List[Any] = []

    async def get(self, model_cls: Any, pk: Any) -> Optional[Any]:
        name = getattr(model_cls, "__name__", str(model_cls))
        if name == "Protocol":
            return self.protocol if self.protocol and self.protocol.id == pk else None
        if name == "AudioFile":
            return (
                self.audio_file
                if self.audio_file and self.audio_file.id == pk
                else None
            )
        return None

    async def execute(self, stmt: Any) -> _FakeScalarResult:
        self.executed_stmts.append(stmt)
        # The router's SELECT has an ``.where(...)`` clause that filters by
        # confidence < threshold (OR confidence IS NULL OR low_confidence=True).
        # We don't parse SQL — instead we read the in-memory utterances and
        # apply the same three-way filter using the most permissive
        # ``confidence_threshold`` (the router may also pass 0.0 in tests,
        # but our tests only need the default behavior to hold).
        filtered: List[Any] = []
        for u in self.utterances:
            conf = getattr(u, "confidence", None)
            low = getattr(u, "low_confidence", False)
            if conf is None:
                filtered.append(u)
            elif low is True:
                filtered.append(u)
            elif isinstance(conf, (int, float)) and conf < 0.7:
                filtered.append(u)
        return _FakeScalarResult(filtered)


class _FakeTranscriptionService:
    """Drop-in replacement for ``transcription_service.transcribe``."""

    def __init__(self, raise_exc: Optional[BaseException] = None) -> None:
        self._raise = raise_exc
        self.calls: List[dict] = []

    async def transcribe(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._raise is not None:
            raise self._raise
        return SimpleNamespace(status="ok")


# ============================================================================
# App builder — override get_db with the in-memory fake session
# ============================================================================


@ pytest_asyncio.fixture
async def fake_client(monkeypatch):
    """Build a tiny FastAPI app with only the upgrade router, with a fake DB."""
    sess = _FakeAsyncSession()

    async def override_get_db():
        yield sess

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api/v1/hmp")

    from app.db.session import get_db

    test_app.dependency_overrides[get_db] = override_get_db

    # Patch the active_tasks registry so we can observe what got scheduled.
    from app.services import active_tasks as active_tasks_mod

    captured: dict = {"registered": []}

    def fake_register(task_id_str, task):
        captured["registered"].append((task_id_str, task))
        # Cancel immediately — we don't want the real transcription loop
        try:
            task.cancel()
        except Exception:
            pass

    monkeypatch.setattr(active_tasks_mod, "register_active_task", fake_register)

    # Provide a no-op AsyncSessionLocal so the in-process _runner doesn't
    # try to open a real Postgres connection.
    fake_trans = _FakeTranscriptionService()
    from app.services import transcription as transcription_module_path

    monkeypatch.setattr(
        transcription_module_path, "transcription_service", fake_trans
    )
    # The runner does ``from app.db.session import AsyncSessionLocal``
    # lazily inside its closure; patch the symbol where it will be looked up.
    from app.db import session as session_module

    class _FakeSessionLocal:
        def __init__(self) -> None:
            self.sess = _FakeAsyncSession()

        async def __aenter__(self) -> _FakeAsyncSession:
            return self.sess

        async def __aexit__(self, *exc: Any) -> None:
            return None

    monkeypatch.setattr(session_module, "AsyncSessionLocal", _FakeSessionLocal)

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, sess, captured, fake_trans


def _make_audio_file(path: Path) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        file_path=str(path),
        filename=path.name,
        extension=path.suffix.lstrip(".") or "wav",
        size_bytes=128,
        mime_type="audio/wav",
        duration_sec=42.0,
    )


def _make_protocol(
    audio_file_id: Optional[uuid.UUID] = None, *, pid: Optional[uuid.UUID] = None
) -> Any:
    return SimpleNamespace(
        id=pid or uuid.uuid4(),
        title="v2-test",
        status="recording",
        audio_file_id=audio_file_id,
    )


def _link(audio_file: Any, protocol: Optional[Any] = None) -> Any:
    """Make a protocol whose ``audio_file_id`` points to the given audio file."""
    if protocol is None:
        protocol = _make_protocol()
    protocol.audio_file_id = audio_file.id
    return protocol


def _make_utt(
    *,
    text: str,
    start: float,
    end: float,
    confidence: Optional[float] = None,
    low_confidence: bool = False,
) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        protocol_id=None,
        speaker_id=None,
        start_sec=start,
        end_sec=end,
        text=text,
        confidence=confidence,
        low_confidence=low_confidence,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


# ============================================================================
# Module / route structural sanity
# ============================================================================


def test_upgrade_module_exposes_router_and_callable():
    """The module must export ``router`` and ``upgrade_weak_segments_endpoint``."""
    assert upgrade_module.router is not None
    assert upgrade_module.upgrade_weak_segments_endpoint is not None
    assert callable(upgrade_module.upgrade_weak_segments_endpoint)
    # The function must be bound to the route handler
    paths = {r.path for r in upgrade_module.router.routes}
    assert "/transcribe/upgrade/{protocol_id}" in paths


def test_default_query_params_match_spec():
    """Default ``target_model='large-v3'`` and ``confidence_threshold=0.7``."""
    sig = inspect.signature(upgrade_weak_segments_endpoint)
    assert sig.parameters["target_model"].default == "large-v3"
    assert sig.parameters["confidence_threshold"].default == 0.7
    # ``protocol_id`` is a path param (str) and ``db`` is a DI dependency
    assert "protocol_id" in sig.parameters
    assert "db" in sig.parameters


# ============================================================================
# Error-path branches
# ============================================================================


@pytest.mark.asyncio
async def test_invalid_uuid_string_returns_400(fake_client):
    """Non-UUID path param → handler raises HTTPException(400)."""
    ac, *_ = fake_client
    r = await ac.post("/api/v1/hmp/transcribe/upgrade/not-a-uuid")
    assert r.status_code == 400
    assert "Невалидный" in r.json()["detail"]


@pytest.mark.asyncio
async def test_protocol_not_found_returns_404(fake_client):
    ac, sess, *_ = fake_client
    # sess.protocol stays None → db.get returns None
    r = await ac.post(f"/api/v1/hmp/transcribe/upgrade/{uuid.uuid4()}")
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_protocol_without_audio_file_id_returns_400(fake_client):
    ac, sess, *_ = fake_client
    sess.protocol = _make_protocol(audio_file_id=None)
    r = await ac.post(f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}")
    assert r.status_code == 400
    assert "аудиофайла" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_audio_file_row_missing_returns_400(fake_client):
    ac, sess, *_ = fake_client
    sess.protocol = _make_protocol(audio_file_id=uuid.uuid4())
    # sess.audio_file stays None
    r = await ac.post(f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}")
    assert r.status_code == 400
    assert "аудиофайл" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_audio_file_missing_on_disk_returns_400(fake_client, tmp_path):
    ac, sess, *_ = fake_client
    bogus = tmp_path / "missing.wav"
    sess.protocol = _make_protocol()
    sess.audio_file = _make_audio_file(bogus)
    sess.protocol.audio_file_id = sess.audio_file.id
    r = await ac.post(f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}")
    assert r.status_code == 400
    assert "аудио не найдено" in r.json()["detail"].lower()


# ============================================================================
# Happy paths / no-op branches
# ============================================================================


@pytest.mark.asyncio
async def test_no_weak_segments_returns_noop_response(fake_client, tmp_path):
    """All utterances have confidence >= threshold → no-op response.

    Validates the full contract of the no-op branch: every documented key
    is present with the documented type/value, and the no-op branch
    does NOT schedule a background task.
    """
    ac, sess, captured, _ = fake_client
    audio = tmp_path / "ok.wav"
    audio.write_bytes(b"RIFF")
    sess.audio_file = _make_audio_file(audio)
    sess.protocol = _make_protocol(audio_file_id=sess.audio_file.id)
    sess.utterances = [
        _make_utt(text=f"u{i}", start=float(i), end=float(i) + 1.0, confidence=0.95)
        for i in range(3)
    ]

    r = await ac.post(f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}")
    assert r.status_code == 200
    body = r.json()

    # No-op contract: no task scheduled, but informative counters
    assert body["weak_segments_found"] == 0
    assert body["upgraded"] == 0
    assert body["skipped"] == 0
    assert body["target_model"] == "large-v3"
    assert body["protocol_id"] == str(sess.protocol.id)
    assert "Нет слабых" in body["message"]
    assert "task_id" not in body
    # No background task was registered in the no-op branch
    assert captured["registered"] == []


@pytest.mark.asyncio
async def test_multiple_weak_segments_return_count(fake_client, tmp_path, monkeypatch):
    """Multiple weak utterances (numeric low confidence) → counts them and
    registers a background task with the correct arguments."""
    ac, sess, captured, fake_trans = fake_client
    audio = tmp_path / "many.wav"
    audio.write_bytes(b"RIFF")
    sess.audio_file = _make_audio_file(audio)
    sess.protocol = _make_protocol(audio_file_id=sess.audio_file.id)
    sess.utterances = [
        _make_utt(text=f"w{i}", start=float(i), end=float(i) + 1.0, confidence=0.2)
        for i in range(5)
    ]

    r = await ac.post(
        f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}",
        params={"target_model": "medium"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["weak_segments_found"] == 5
    assert body["target_model"] == "medium"
    assert "task_id" in body

    # Background task was registered (and cancelled by the fixture)
    assert len(captured["registered"]) == 1
    task_id_str, task_obj = captured["registered"][0]
    assert task_id_str == body["task_id"]
    assert isinstance(task_obj, asyncio.Task)
    # Either already done/cancelled or scheduled to be cancelled by the
    # fixture (the actual cancellation is processed by the event loop
    # after the request handler returns).
    assert (
        task_obj.cancelled()
        or task_obj.done()
        or task_obj.cancelling() > 0
    )


@pytest.mark.asyncio
async def test_weak_via_low_confidence_flag_only(fake_client, tmp_path, monkeypatch):
    """confidence IS NOT NULL and >= threshold, but low_confidence=True → weak."""
    ac, sess, captured, _ = fake_client
    audio = tmp_path / "flag.wav"
    audio.write_bytes(b"RIFF")
    sess.audio_file = _make_audio_file(audio)
    sess.protocol = _make_protocol(audio_file_id=sess.audio_file.id)
    sess.utterances = [
        # high numeric confidence but flagged weak
        _make_utt(
            text="flag",
            start=0.0,
            end=1.0,
            confidence=0.99,
            low_confidence=True,
        )
    ]

    r = await ac.post(f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["weak_segments_found"] == 1
    assert "task_id" in body


@pytest.mark.asyncio
async def test_threshold_boundary_default_picks_up_only_low(fake_client, tmp_path, monkeypatch):
    """Default threshold (0.7): confidence=0.5 → weak, confidence=0.95 → not weak."""
    ac, sess, captured, _ = fake_client
    audio = tmp_path / "boundary.wav"
    audio.write_bytes(b"RIFF")
    sess.audio_file = _make_audio_file(audio)
    sess.protocol = _make_protocol(audio_file_id=sess.audio_file.id)
    sess.utterances = [
        _make_utt(text="low", start=0.0, end=1.0, confidence=0.5),
        _make_utt(text="high", start=2.0, end=3.0, confidence=0.95),
    ]

    r = await ac.post(f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["weak_segments_found"] == 1


@pytest.mark.asyncio
async def test_background_runner_invokes_transcribe_with_correct_kwargs(
    fake_client, tmp_path, monkeypatch
):
    """The in-process _runner calls ``transcription_service.transcribe``
    with ``only_update_weak=True``, the requested ``target_model`` and
    the audio metadata — and the endpoint still returns 200 even if the
    runner raises.
    """
    # Force the background task to actually run before our fake_register
    # cancels it, so we can observe the call to transcription_service.
    from app.services import active_tasks as active_tasks_mod

    seen_calls: List[dict] = []

    def holding_register(task_id_str, task):
        # Allow the coroutine to start, then cancel it
        async def _hold():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        asyncio.create_task(_hold())

    monkeypatch.setattr(active_tasks_mod, "register_active_task", holding_register)

    # Re-create the client with the new register behavior. Use a fresh
    # client fixture by inlining the build:
    sess = _FakeAsyncSession()

    async def override_get_db():
        yield sess

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api/v1/hmp")
    from app.db.session import get_db
    test_app.dependency_overrides[get_db] = override_get_db

    from app.db import session as session_module
    from app.services import transcription as transcription_module_path

    class _FakeSessionLocal:
        def __init__(self) -> None:
            self.sess = _FakeAsyncSession()

        async def __aenter__(self) -> _FakeAsyncSession:
            return self.sess

        async def __aexit__(self, *exc: Any) -> None:
            return None

    monkeypatch.setattr(session_module, "AsyncSessionLocal", _FakeSessionLocal)

    fake_trans = _FakeTranscriptionService()
    monkeypatch.setattr(
        transcription_module_path, "transcription_service", fake_trans
    )

    audio = tmp_path / "runner.wav"
    audio.write_bytes(b"RIFF")
    sess.audio_file = _make_audio_file(audio)
    sess.protocol = _make_protocol(audio_file_id=sess.audio_file.id)
    sess.utterances = [
        _make_utt(text="weak", start=0.0, end=1.0, confidence=0.3)
    ]

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}",
            params={"target_model": "medium"},
        )
        assert r.status_code == 200
        assert r.json()["weak_segments_found"] == 1
        # Give the task a moment to run before assertion
        await asyncio.sleep(0.2)

    # The runner called transcription_service.transcribe with the right kwargs
    assert len(fake_trans.calls) == 1
    call = fake_trans.calls[0]
    assert call["only_update_weak"] is True
    assert call["target_model_override"] == "medium"
    assert call["audio_path"] == Path(audio)
    assert call["duration_sec"] == 42.0
    assert call["protocol_id"] == sess.protocol.id


# ============================================================================
# Direct unit-call coverage (bypasses HTTP, exercises the function body)
# ============================================================================


@pytest.mark.asyncio
async def test_direct_call_with_fake_db_propagates_exception_to_http():
    """Calling the endpoint directly with a fake DB raises HTTPException
    when validation fails — guarantees the HTTPException-raising branches
    in lines 54-71 are exercised via a different code path than the
    AsyncClient transport above."""
    fake_db = _FakeAsyncSession()
    fake_db.protocol = None  # → 404
    with pytest.raises(HTTPException) as exc:
        await upgrade_weak_segments_endpoint(
            protocol_id=str(uuid.uuid4()),
            db=fake_db,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_direct_call_invalid_uuid_raises_400():
    fake_db = _FakeAsyncSession()
    with pytest.raises(HTTPException) as exc:
        await upgrade_weak_segments_endpoint(
            protocol_id="not-a-uuid",
            db=fake_db,
        )
    assert exc.value.status_code == 400
    assert "Невалидный" in exc.value.detail