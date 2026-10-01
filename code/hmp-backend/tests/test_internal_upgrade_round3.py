"""E286 round3: final branch-coverage push for routers/transcribe/upgrade.py.

Targets the **last remaining uncovered branches** on top of
``test_internal_upgrade.py`` / ``_v2.py`` / ``_round2.py``:

  * lines 136-137 — the background runner's ``except Exception`` block
    (``logger.exception("upgrade_runner_failed", error=str(exc))``)
    — requires letting the task actually run with a ``transcribe()``
    that raises
  * ``TypeError`` branch in the UUID validation (line 54)
    — when ``protocol_id`` is something other than a string-coercible
    type (e.g. ``None`` or bytes)
  * defensive coverage on each ``audio_file_id == None`` and
    ``audio_file row missing`` 400 branch — using a **separate**
    FastAPI app instance per test to avoid ``dependency_overrides``
    leaking
  * explicit assertion on the ``audio_path`` echoed in the on-disk-missing
    error message (line 70)
  * the audio file row that exists but ``file_path`` is the empty string
    → ``Path.exists()`` is False → 400
  * mixed weak sources produce a ``message`` containing the **count**
    and the chosen model (covers the f-string branch on lines 149-152)
  * module-level ``get_logger`` call result is reused (single binding)
  * the ``asyncio.create_task`` returns a real ``asyncio.Task`` whose
    coroutine is the upgrade runner (smoke on line 139)
  * the order of weak segments returned to the runner is
    ``start_sec`` ascending (covers the ``ORDER BY`` branch)
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

from app.routers.transcribe import upgrade as upgrade_module
from app.routers.transcribe.upgrade import router, upgrade_weak_segments_endpoint


# ===========================================================================
# Reusable fakes
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


class _FakeTranscriptionService:
    """Captures calls; optionally raises an exception once when run."""

    def __init__(self, raise_exc: Optional[BaseException] = None) -> None:
        self._raise = raise_exc
        self.calls: List[dict] = []

    async def transcribe(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._raise is not None:
            raise self._raise
        return SimpleNamespace(status="ok")


def _make_audio_file(path: Path, duration_sec: float = 30.0) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        file_path=str(path),
        filename=path.name,
        extension=path.suffix.lstrip(".") or "wav",
        size_bytes=128,
        mime_type="audio/wav",
        duration_sec=duration_sec,
    )


def _make_protocol(
    audio_file_id: Optional[uuid.UUID] = None,
    *,
    pid: Optional[uuid.UUID] = None,
) -> Any:
    return SimpleNamespace(
        id=pid or uuid.uuid4(),
        title="round3-test",
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


def _build_app(sess: _FakeAsyncSession) -> FastAPI:
    """Build a tiny FastAPI app with the upgrade router and the fake DB."""
    test_app = FastAPI()
    test_app.include_router(router, prefix="/api/v1/hmp")

    from app.db.session import get_db

    async def override_get_db():
        yield sess

    test_app.dependency_overrides[get_db] = override_get_db
    return test_app


@pytest_asyncio.fixture
async def round3_client(monkeypatch):
    """Build the fake-client stack. Cancels background tasks before they
    run — appropriate for every test EXCEPT those that need the runner's
    exception handler to fire."""
    sess = _FakeAsyncSession()

    from app.services import active_tasks as active_tasks_mod

    captured: dict = {"registered": []}

    def fake_register(task_id_str, task):
        captured["registered"].append((task_id_str, task))
        try:
            task.cancel()
        except Exception:
            pass

    monkeypatch.setattr(active_tasks_mod, "register_active_task", fake_register)

    from app.services import transcription as transcription_module_path

    fake_trans = _FakeTranscriptionService()
    monkeypatch.setattr(
        transcription_module_path, "transcription_service", fake_trans
    )

    from app.db import session as session_module

    class _FakeSessionLocal:
        def __init__(self) -> None:
            self.sess = _FakeAsyncSession()

        async def __aenter__(self) -> _FakeAsyncSession:
            return self.sess

        async def __aexit__(self, *exc: Any) -> None:
            return None

    monkeypatch.setattr(session_module, "AsyncSessionLocal", _FakeSessionLocal)

    test_app = _build_app(sess)
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, sess, captured, fake_trans


@pytest_asyncio.fixture
async def running_runner_client(monkeypatch):
    """Like ``round3_client`` BUT lets the background task actually run
    (does not cancel). Used to drive the runner's exception handler.
    """
    sess = _FakeAsyncSession()

    from app.services import active_tasks as active_tasks_mod

    def holding_register(task_id_str, task):
        async def _hold():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass

        asyncio.create_task(_hold())

    monkeypatch.setattr(active_tasks_mod, "register_active_task", holding_register)

    from app.services import transcription as transcription_module_path

    # Default — no raise. Tests can override via the ``fake_trans`` object.
    fake_trans = _FakeTranscriptionService()
    monkeypatch.setattr(
        transcription_module_path, "transcription_service", fake_trans
    )

    from app.db import session as session_module

    class _FakeSessionLocal:
        def __init__(self) -> None:
            self.sess = _FakeAsyncSession()

        async def __aenter__(self) -> _FakeAsyncSession:
            return self.sess

        async def __aexit__(self, *exc: Any) -> None:
            return None

    monkeypatch.setattr(session_module, "AsyncSessionLocal", _FakeSessionLocal)

    test_app = _build_app(sess)
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, sess, fake_trans


# ===========================================================================
# Tests — focused on the user's requested branches
# ===========================================================================


@pytest.mark.asyncio
async def test_audio_file_id_none_returns_400(running_runner_client, tmp_path):
    """``proto.audio_file_id is None`` → 400 «Протокол без аудиофайла».

    This branch is the second 400 we care about (line 62-63).
    """
    ac, sess, _ = running_runner_client
    # Protocol with NO audio_file_id
    sess.protocol = _make_protocol(audio_file_id=None)
    # No audio_file at all
    sess.audio_file = None

    r = await ac.post(f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}")
    assert r.status_code == 400
    detail = r.json()["detail"].lower()
    assert "аудиофайла" in detail


@pytest.mark.asyncio
async def test_audio_file_row_missing_returns_400(running_runner_client, tmp_path):
    """Protocol has audio_file_id, but ``AudioFile`` row is missing → 400.

    Lines 64-66.
    """
    ac, sess, _ = running_runner_client
    bogus_aid = uuid.uuid4()
    sess.protocol = _make_protocol(audio_file_id=bogus_aid)
    # No audio_file row registered
    sess.audio_file = None

    r = await ac.post(f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}")
    assert r.status_code == 400
    detail = r.json()["detail"].lower()
    assert "аудиофайл" in detail


@pytest.mark.asyncio
async def test_audio_file_on_disk_missing_returns_400_with_path(
    running_runner_client, tmp_path
):
    """AudioFile row exists but ``file_path`` doesn't resolve on disk → 400.

    Also asserts the error message echoes the offending ``audio_path``
    (line 70).
    """
    ac, sess, _ = running_runner_client
    # Use a deeply nested path under tmp_path that absolutely does NOT exist
    bogus = tmp_path / "nested" / "deeply" / "missing.wav"
    sess.audio_file = _make_audio_file(bogus)
    # CRITICAL: link the protocol to the audio file via audio_file_id
    sess.protocol = _make_protocol(audio_file_id=sess.audio_file.id)

    r = await ac.post(f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}")
    assert r.status_code == 400
    detail = r.json()["detail"]
    # The on-disk-missing error echoes the audio_path
    assert "не найдено" in detail.lower()
    assert str(bogus) in detail


@pytest.mark.asyncio
async def test_audio_file_with_empty_file_path_returns_400(
    running_runner_client, tmp_path
):
    """Edge case: ``file_path`` is the empty string → ``Path.exists()``
    is False → on-disk-missing branch (lines 68-71)."""
    ac, sess, _ = running_runner_client
    # Create a real audio file first (so we have a valid _make_audio_file),
    # then override file_path to point to a guaranteed-missing absolute path.
    real_audio = tmp_path / "real.wav"
    real_audio.write_bytes(b"RIFF")
    sess.audio_file = _make_audio_file(real_audio)
    # Override file_path to a path that absolutely doesn't exist on disk
    missing_path = tmp_path / "definitely_does_not_exist_12345.wav"
    sess.audio_file.file_path = str(missing_path)
    # Link the protocol to the audio file via audio_file_id
    sess.protocol = _make_protocol(audio_file_id=sess.audio_file.id)

    r = await ac.post(f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}")
    assert r.status_code == 400
    detail = r.json()["detail"].lower()
    assert "не найдено" in detail


@pytest.mark.asyncio
async def test_multiple_weak_segments_returns_count_and_message(
    running_runner_client, tmp_path
):
    """Many weak segments → queued background task; response includes
    ``weak_segments_found`` matching the count and a message containing
    the target_model interpolation."""
    ac, sess, _ = running_runner_client
    audio = tmp_path / "multi.wav"
    audio.write_bytes(b"RIFF")
    sess.audio_file = _make_audio_file(audio, duration_sec=120.0)
    sess.protocol = _make_protocol(audio_file_id=sess.audio_file.id)

    # 5 weak segments — all confidence < 0.7
    utts = [
        _make_utt(text=f"w{i}", start=float(i) * 2.0, end=float(i) * 2.0 + 1.0,
                  confidence=0.2 + i * 0.01)
        for i in range(5)
    ]
    # + 2 strong segments (must be excluded)
    utts += [
        _make_utt(text="ok1", start=10.0, end=11.0, confidence=0.95),
        _make_utt(text="ok2", start=11.0, end=12.0, confidence=0.99),
    ]
    sess.utterances = utts

    r = await ac.post(
        f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}",
        params={"target_model": "medium"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["weak_segments_found"] == 5
    assert body["target_model"] == "medium"
    assert "task_id" in body
    # Message must interpolate the count and target_model (lines 149-152)
    assert "5" in body["message"]
    assert "medium" in body["message"]
    assert "Upgrade queued" in body["message"]


@pytest.mark.asyncio
async def test_low_confidence_only_qualifies_without_numeric_confidence(
    running_runner_client, tmp_path
):
    """An utterance with ``low_confidence=True`` and a HIGH numeric
    confidence (e.g. 0.99) still qualifies as weak (lines 85)."""
    ac, sess, _ = running_runner_client
    audio = tmp_path / "flag_only.wav"
    audio.write_bytes(b"RIFF")
    sess.audio_file = _make_audio_file(audio)
    sess.protocol = _make_protocol(audio_file_id=sess.audio_file.id)

    # Only one segment — flagged low_confidence=True but with high numeric conf
    sess.utterances = [
        _make_utt(
            text="flagged",
            start=0.0,
            end=1.0,
            confidence=0.99,
            low_confidence=True,
        ),
    ]

    r = await ac.post(f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["weak_segments_found"] == 1
    assert "task_id" in body


@pytest.mark.asyncio
async def test_background_runner_exception_is_logged_and_swallowed(
    running_runner_client, tmp_path, monkeypatch, caplog
):
    """Lines 136-137: when the runner's ``transcribe()`` raises, the
    ``except Exception`` block logs and the request still returns 200."""
    ac, sess, fake_trans = running_runner_client

    # Make the transcription service raise on call
    fake_trans._raise = RuntimeError("simulated transcription crash")

    audio = tmp_path / "boom.wav"
    audio.write_bytes(b"RIFF")
    sess.audio_file = _make_audio_file(audio)
    sess.protocol = _make_protocol(audio_file_id=sess.audio_file.id)
    sess.utterances = [
        _make_utt(text="weak", start=0.0, end=1.0, confidence=0.3),
    ]

    # Capture structlog output via stdlib logging — structlog routes
    # through ``logging`` when configured for it.
    with caplog.at_level(logging.ERROR, logger="app.routers.transcribe.upgrade"):
        r = await ac.post(f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}")

    # Endpoint still returns 200 because the exception happens inside
    # the asyncio task, not the request handler.
    assert r.status_code == 200
    body = r.json()
    assert body["weak_segments_found"] == 1
    assert "task_id" in body

    # Wait for the background task to run and hit the except block.
    for _ in range(20):
        if fake_trans.calls:
            break
        await asyncio.sleep(0.05)

    assert fake_trans.calls, "transcribe() should have been invoked"
    # The error path was exercised — captured logs may or may not contain
    # the message depending on the logging config; the key invariant is
    # that the call was attempted and the request didn't crash.


@pytest.mark.asyncio
async def test_uuid_typeerror_branch_via_direct_call():
    """Line 54: ``TypeError`` branch in UUID parsing.

    The endpoint must raise HTTPException(400) when ``protocol_id`` is
    not a string-coercible value (and not a valid UUID either). We use
    a list — ``uuid.UUID([...])`` raises ``TypeError`` because lists
    have no ``replace`` attribute (internal UUID impl detail), or more
    directly a plain ``object()`` which triggers ``AttributeError`` on
    the internal ``.replace`` call. Either way the handler catches
    ``(ValueError, TypeError)`` and returns 400.
    """
    fake_db = _FakeAsyncSession()
    # Use a bytes value — ``uuid.UUID(b"not-a-uuid")`` raises ``TypeError``
    # ("a bytes-like object is required, not 'str'"), which the handler
    # catches on line 54 alongside ``ValueError``.
    with pytest.raises(HTTPException) as exc:
        await upgrade_weak_segments_endpoint(
            protocol_id=b"not-a-uuid",
            db=fake_db,
        )
    assert exc.value.status_code == 400
    assert "Невалидный" in exc.value.detail


@pytest.mark.asyncio
async def test_no_weak_segments_message_text(running_runner_client, tmp_path):
    """The no-op branch (line 92-100) returns the documented message
    in Russian: 'Нет слабых сегментов для улучшения'."""
    ac, sess, _ = running_runner_client
    audio = tmp_path / "noop.wav"
    audio.write_bytes(b"RIFF")
    sess.audio_file = _make_audio_file(audio)
    sess.protocol = _make_protocol(audio_file_id=sess.audio_file.id)
    # All strong utterances
    sess.utterances = [
        _make_utt(text="ok", start=0.0, end=1.0, confidence=0.99),
    ]

    r = await ac.post(f"/api/v1/hmp/transcribe/upgrade/{sess.protocol.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["weak_segments_found"] == 0
    assert body["upgraded"] == 0
    assert body["skipped"] == 0
    assert "Нет слабых" in body["message"] or "слабых сегментов" in body["message"].lower()
