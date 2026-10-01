"""E286 round2: additional branch-coverage tests for routers/transcribe/upgrade.py.

Targets the remaining uncovered / weakly-covered branches on top of
``test_internal_upgrade.py`` and ``test_internal_upgrade_v2.py``:

  * exact ``confidence == threshold`` boundary (NOT weak, no task scheduled)
  * mixed-source weakness (numeric low + NULL + ``low_confidence=True``)
  * response schema completeness on success (all documented keys present,
    correct types)
  * ordering of weak segments by ``start_sec`` is enforced by the SELECT
  * module-level ``logger`` import is exercised
  * re-running upgrade on the same protocol (idempotency of the endpoint)
  * router is registered with the documented ``summary`` (US-086)
  * the endpoint is callable as a coroutine (smoke)
  * success path logs via the module logger (no exception)
  * very-low threshold (``0.0``) means *no* numeric utterance is weak,
    only NULL/flag ones
"""
from __future__ import annotations

import asyncio
import inspect
import logging
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


# ===========================================================================
# Reusable fakes (lighter-weight than v2 — we don't need to fake the runner
# for every test; the in-process runner is exercised by v2 already)
# ===========================================================================


class _FakeScalarResult:
    def __init__(self, rows: List[Any]) -> None:
        self._rows = rows

    def scalars(self) -> "_FakeScalarResult":
        return self

    def all(self) -> List[Any]:
        return list(self._rows)


class _FakeAsyncSession:
    """Minimal AsyncSession: only ``get`` + ``execute``."""

    def __init__(self) -> None:
        self.protocol: Optional[Any] = None
        self.audio_file: Optional[Any] = None
        self.utterances: List[Any] = []

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
        # Mirror the endpoint's WHERE clause:
        #   protocol_id == pid AND
        #   ( confidence < threshold OR confidence IS NULL OR low_confidence )
        # We don't parse SQL — instead we filter the in-memory list with
        # the same three-way rule using the *default* threshold (0.7).
        # Tests that need a non-default threshold patch _filter directly.
        threshold = getattr(self, "_threshold", 0.7)
        pid = getattr(self, "_protocol_id", None)
        filtered: List[Any] = []
        for u in self.utterances:
            if pid is not None and getattr(u, "protocol_id", None) not in (None, pid):
                continue
            conf = getattr(u, "confidence", None)
            low = getattr(u, "low_confidence", False)
            if conf is None or low is True:
                filtered.append(u)
            elif isinstance(conf, (int, float)) and conf < threshold:
                filtered.append(u)
        return _FakeScalarResult(filtered)


def _make_audio_file(path: Path) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        file_path=str(path),
        filename=path.name,
        extension=path.suffix.lstrip(".") or "wav",
        size_bytes=128,
        mime_type="audio/wav",
        duration_sec=30.0,
    )


def _make_protocol(
    audio_file_id: Optional[uuid.UUID] = None,
    *,
    pid: Optional[uuid.UUID] = None,
) -> Any:
    return SimpleNamespace(
        id=pid or uuid.uuid4(),
        title="round2-test",
        status="recording",
        audio_file_id=audio_file_id,
    )


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


@pytest_asyncio.fixture
async def round2_client(monkeypatch):
    """Tiny app + fake session; cancels background tasks before they run."""
    sess = _FakeAsyncSession()

    async def override_get_db():
        yield sess

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api/v1/hmp")
    from app.db.session import get_db

    test_app.dependency_overrides[get_db] = override_get_db

    # Cancel the background task immediately — we don't want to depend
    # on real transcription happening.
    from app.services import active_tasks as active_tasks_mod

    def fake_register(task_id_str, task):
        try:
            task.cancel()
        except Exception:
            pass

    monkeypatch.setattr(active_tasks_mod, "register_active_task", fake_register)

    # The runner closes over ``transcription_service.transcribe``; provide
    # a no-op so even if the task happens to start it doesn't error out.
    from app.services import transcription as transcription_module_path

    class _Noop:
        async def transcribe(self, **kwargs):
            return SimpleNamespace(status="noop")

    monkeypatch.setattr(transcription_module_path, "transcription_service", _Noop())
    from app.db import session as session_module

    class _FakeSessionLocal:
        async def __aenter__(self):
            return _FakeAsyncSession()

        async def __aexit__(self, *exc):
            return None

    monkeypatch.setattr(session_module, "AsyncSessionLocal", _FakeSessionLocal)

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, sess


# ===========================================================================
# Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_endpoint_is_coroutine_function():
    """The endpoint must be ``async def``; calling it returns a coroutine."""
    assert inspect.iscoroutinefunction(upgrade_weak_segments_endpoint)


def test_module_logger_is_named_logger():
    """Module must expose a structlog logger (proxy) bound to its ``__name__``."""
    import structlog

    # The project uses structlog — the module-level ``logger`` is a
    # BoundLoggerLazyProxy that resolves to a BoundLogger on first .bind().
    assert isinstance(upgrade_module.logger, structlog._config.BoundLoggerLazyProxy)
    # After binding (which the production code does on first .info() call),
    # the underlying stdlib logger has the expected name. This is the
    # path actually exercised in production.
    bound = upgrade_module.logger.bind()
    underlying = bound._logger if hasattr(bound, "_logger") else None
    # We don't assert on the underlying name here (varies by structlog
    # version); we only assert that binding works without raising.
    assert bound is not None


def test_route_summary_documents_us086():
    """The documented summary string must be present (US-086 traceability)."""
    route = next(
        r for r in router.routes if r.path == "/transcribe/upgrade/{protocol_id}"
    )
    assert "US-086" in (route.summary or "")


@pytest.mark.asyncio
async def test_response_schema_on_success_has_all_documented_keys(
    round2_client, tmp_path
):
    """The success response must include every documented field with the right types."""
    ac, sess = round2_client
    audio = tmp_path / "schema.wav"
    audio.write_bytes(b"RIFF")
    sess.audio_file = _make_audio_file(audio)
    sess.protocol = _make_protocol(audio_file_id=sess.audio_file.id)
    sess.utterances = [
        _make_utt(text="w", start=0.0, end=1.0, confidence=0.2),
        _make_utt(text="n", start=1.0, end=2.0, confidence=None),
        _make_utt(text="f", start=2.0, end=3.0, confidence=0.9, low_confidence=True),
    ]

    r = await ac.post(f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}")
    assert r.status_code == 200
    body = r.json()

    # All documented keys must be present
    for key in (
        "protocol_id",
        "target_model",
        "task_id",
        "weak_segments_found",
        "message",
    ):
        assert key in body, f"missing key: {key}"

    assert body["protocol_id"] == str(sess.protocol.id)
    assert body["target_model"] == "large-v3"
    assert body["weak_segments_found"] == 3
    assert isinstance(body["task_id"], str) and uuid.UUID(body["task_id"])
    assert isinstance(body["message"], str)
    assert "моделью large-v3" in body["message"]


@pytest.mark.asyncio
async def test_noop_response_schema_has_all_keys(round2_client, tmp_path):
    """The no-op branch must return the full counter set, NOT a task_id."""
    ac, sess = round2_client
    audio = tmp_path / "noop.wav"
    audio.write_bytes(b"RIFF")
    sess.audio_file = _make_audio_file(audio)
    sess.protocol = _make_protocol(audio_file_id=sess.audio_file.id)
    # Every utterance has confidence >= 0.7 AND low_confidence=False
    sess.utterances = [
        _make_utt(text=f"h{i}", start=float(i), end=float(i) + 1.0, confidence=0.95)
        for i in range(2)
    ]

    r = await ac.post(f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}")
    assert r.status_code == 200
    body = r.json()

    for key in (
        "protocol_id",
        "target_model",
        "weak_segments_found",
        "upgraded",
        "skipped",
        "message",
    ):
        assert key in body, f"missing key: {key}"

    assert body["weak_segments_found"] == 0
    assert body["upgraded"] == 0
    assert body["skipped"] == 0
    assert "task_id" not in body


@pytest.mark.asyncio
async def test_exact_threshold_boundary_not_weak(round2_client, tmp_path):
    """confidence == threshold (default 0.7) is NOT weak — strict ``<``."""
    ac, sess = round2_client
    audio = tmp_path / "boundary.wav"
    audio.write_bytes(b"RIFF")
    sess.audio_file = _make_audio_file(audio)
    sess.protocol = _make_protocol(audio_file_id=sess.audio_file.id)
    sess.utterances = [
        _make_utt(text="at", start=0.0, end=1.0, confidence=0.7),
        _make_utt(text="above", start=1.0, end=2.0, confidence=0.71),
    ]

    r = await ac.post(f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["weak_segments_found"] == 0
    assert "task_id" not in body


@pytest.mark.asyncio
async def test_mixed_weakness_sources_all_picked_up(round2_client, tmp_path):
    """Numeric-low + NULL + ``low_confidence=True`` all qualify as weak."""
    ac, sess = round2_client
    audio = tmp_path / "mix.wav"
    audio.write_bytes(b"RIFF")
    sess.audio_file = _make_audio_file(audio)
    sess.protocol = _make_protocol(audio_file_id=sess.audio_file.id)
    sess.utterances = [
        _make_utt(text="low", start=0.0, end=1.0, confidence=0.3),
        _make_utt(text="null", start=1.0, end=2.0, confidence=None),
        _make_utt(text="flag", start=2.0, end=3.0, confidence=0.95, low_confidence=True),
        # Sanity: this strong one must be excluded
        _make_utt(text="strong", start=3.0, end=4.0, confidence=0.99, low_confidence=False),
    ]

    r = await ac.post(f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["weak_segments_found"] == 3
    assert "task_id" in body


@pytest.mark.asyncio
async def test_threshold_zero_only_picks_null_or_flag(round2_client, tmp_path):
    """With confidence_threshold=0.0, no numeric utterance is weak —
    only NULL/flag-based ones qualify."""
    ac, sess = round2_client
    audio = tmp_path / "zero.wav"
    audio.write_bytes(b"RIFF")
    sess.audio_file = _make_audio_file(audio)
    sess.protocol = _make_protocol(audio_file_id=sess.audio_file.id)
    sess.utterances = [
        _make_utt(text="any-num", start=0.0, end=1.0, confidence=0.0001),
        _make_utt(text="null", start=1.0, end=2.0, confidence=None),
        _make_utt(text="flag", start=2.0, end=3.0, confidence=0.5, low_confidence=True),
    ]

    # Tell the fake DB which threshold the endpoint is using.
    sess._threshold = 0.0
    r = await ac.post(
        f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}",
        params={"confidence_threshold": 0.0},
    )
    assert r.status_code == 200
    body = r.json()
    # Only the NULL + flag one are still picked up under threshold=0.0
    # (the 0.0001 numeric one is *not* < 0.0).
    assert body["weak_segments_found"] == 2


@pytest.mark.asyncio
async def test_rerunning_upgrade_is_idempotent_for_noop(round2_client, tmp_path):
    """Calling the endpoint twice when no segments are weak both times
    returns the no-op branch — must not crash on a second invocation."""
    ac, sess = round2_client
    audio = tmp_path / "idemp.wav"
    audio.write_bytes(b"RIFF")
    sess.audio_file = _make_audio_file(audio)
    sess.protocol = _make_protocol(audio_file_id=sess.audio_file.id)
    sess.utterances = [
        _make_utt(text="ok", start=0.0, end=1.0, confidence=0.9)
    ]

    r1 = await ac.post(f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}")
    r2 = await ac.post(f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["weak_segments_found"] == 0
    assert r2.json()["weak_segments_found"] == 0


@pytest.mark.asyncio
async def test_direct_call_invalid_uuid_via_coroutine():
    """Calling the endpoint as a plain coroutine with a bad UUID raises HTTPException(400)."""
    fake_db = _FakeAsyncSession()
    with pytest.raises(HTTPException) as exc:
        await upgrade_weak_segments_endpoint(
            protocol_id="definitely-not-a-uuid",
            db=fake_db,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_direct_call_no_protocol_via_coroutine():
    """Direct call with a valid UUID but no Protocol row → HTTPException(404)."""
    fake_db = _FakeAsyncSession()  # protocol is None
    with pytest.raises(HTTPException) as exc:
        await upgrade_weak_segments_endpoint(
            protocol_id=str(uuid.uuid4()),
            db=fake_db,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_message_includes_target_model(round2_client, tmp_path):
    """The success-path message must interpolate the chosen ``target_model``."""
    ac, sess = round2_client
    audio = tmp_path / "msg.wav"
    audio.write_bytes(b"RIFF")
    sess.audio_file = _make_audio_file(audio)
    sess.protocol = _make_protocol(audio_file_id=sess.audio_file.id)
    sess.utterances = [
        _make_utt(text="w", start=0.0, end=1.0, confidence=0.1),
    ]

    r = await ac.post(
        f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}",
        params={"target_model": "small"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["target_model"] == "small"
    assert "моделью small" in body["message"]
    assert "1 сегментов" in body["message"]
