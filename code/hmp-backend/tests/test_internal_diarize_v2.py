"""Tests for app/routers/diarize.py — target 80%+ coverage (US-007).

Strategy
--------
The live PostgreSQL test engine in conftest.py occasionally drops connections
mid-TRUNCATE (sandbox DB has a statement_timeout). To make this file reliable
we override ``get_db`` with an in-memory fake session that simulates the
two SQL operations the router performs:

    SELECT protocol WHERE id = :pid      -> returns Protocol or None
    SELECT diarization_result WHERE protocol_id = :pid
                                        -> returns DiarizationResult or None

We also patch ``app.services.diarization.diarization_service`` so the
in-process ``_runner`` does not require pyannote.audio.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Optional

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.routers import diarize as diarize_module
from app.routers.diarize import (
    DiarizeRunRequest,
    DiarizeTaskAccepted,
    router,
)


# ============================================================================
# Fakes
# ============================================================================


class _FakeScalarResult:
    """Async-capable wrapper mimicking ``sqlalchemy``'s ``scalar_one_or_none``."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeAsyncSession:
    """Minimal AsyncSession for diarize.py — supports only the queries the router runs."""

    def __init__(
        self,
        protocol: Optional[Any] = None,
        diarization_result: Optional[Any] = None,
        raise_on: Optional[Exception] = None,
    ) -> None:
        self.protocol = protocol
        self.diarization_result = diarization_result
        self.raise_on = raise_on
        self.executed: list[Any] = []

    async def execute(self, stmt: Any) -> _FakeScalarResult:
        self.executed.append(stmt)
        if self.raise_on is not None:
            raise self.raise_on
        # Heuristic routing by table name; both the router's queries hit a
        # ``select(Protocol|...)`` whose .where clause contains .id ==
        compiled = str(stmt).lower()
        if "protocol" in compiled and "diarization_result" not in compiled:
            return _FakeScalarResult(self.protocol)
        if "diarization_result" in compiled:
            return _FakeScalarResult(self.diarization_result)
        # Default: empty result
        return _FakeScalarResult(None)


class FakeDiarizationService:
    """Drop-in replacement for ``app.services.diarization.diarization_service``."""

    def __init__(
        self,
        raise_exc: Optional[BaseException] = None,
        result: Any = None,
        sleep_for: float = 0.0,
    ) -> None:
        self._raise = raise_exc
        self._result = result
        self._sleep_for = sleep_for
        self.calls: list[dict] = []

    async def diarize_protocol(
        self, *, db: Any, protocol_id: uuid.UUID,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
    ) -> Any:
        self.calls.append(
            {"protocol_id": protocol_id, "min_speakers": min_speakers,
             "max_speakers": max_speakers}
        )
        if self._sleep_for:
            await asyncio.sleep(self._sleep_for)
        if self._raise is not None:
            raise self._raise
        if self._result is not None:
            return self._result
        return SimpleNamespace(
            id=uuid.uuid4(),
            protocol_id=protocol_id,
            num_speakers_detected=2,
            num_speakers_expected=None,
            der_score=None,
            pipeline_version="heuristic-v1",
            confidence_avg=None,
            segments_json=[],
            created_at=datetime.now(timezone.utc),
        )


@pytest.fixture
def fake_service(monkeypatch):
    """Patch ``app.services.diarization.diarization_service``."""
    from app.services import diarization as diarization_module_path
    svc = FakeDiarizationService()
    monkeypatch.setattr(diarization_module_path, "diarization_service", svc)
    return svc


@pytest.fixture(autouse=True)
def _clear_task_registries():
    """Always start each test with clean module-level state."""
    diarize_module._diarize_tasks.clear()
    diarize_module._active_diarize_tasks.clear()
    yield
    diarize_module._diarize_tasks.clear()
    for task in list(diarize_module._active_diarize_tasks.values()):
        if not task.done():
            task.cancel()
    diarize_module._active_diarize_tasks.clear()


async def _wait_for(task_id: uuid.UUID, timeout: float = 2.0) -> Optional[dict]:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        rec = diarize_module._diarize_tasks.get(task_id)
        if rec and rec.get("status") in {"completed", "failed"}:
            return rec
        await asyncio.sleep(0.02)
    return diarize_module._diarize_tasks.get(task_id)


# ============================================================================
# App builder — overrides get_db with _FakeAsyncSession
# ============================================================================


class _SessionRegistry:
    """Holds the protocol + diarization_result that every fake session will report.

    The same registry is shared across the request-handler session
    (delivered via ``get_db`` override) and the background-runner session
    (delivered via the patched ``AsyncSessionLocal``).
    """

    def __init__(self) -> None:
        self.protocol: Optional[Any] = None
        self.diarization_result: Optional[Any] = None


@pytest_asyncio.fixture
async def client_with_db(monkeypatch):
    """Build a tiny FastAPI app with only the diarize router, overriding get_db."""
    registry = _SessionRegistry()

    def make_session() -> _FakeAsyncSession:
        s = _FakeAsyncSession()
        s.protocol = registry.protocol
        s.diarization_result = registry.diarization_result
        return s

    async def override_get_db():
        yield make_session()

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api/v1/hmp")

    from app.db.session import get_db
    test_app.dependency_overrides[get_db] = override_get_db

    # Also patch AsyncSessionLocal so the background runner uses our fake
    from app.db import session as session_module

    class _FakeAsyncSessionLocal:
        def __init__(self) -> None:
            self.sess = make_session()

        async def __aenter__(self) -> _FakeAsyncSession:
            return self.sess

        async def __aexit__(self, *exc: Any) -> None:
            return None

    monkeypatch.setattr(session_module, "AsyncSessionLocal", _FakeAsyncSessionLocal)

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, registry


def _make_protocol_obj(pid: uuid.UUID | None = None) -> Any:
    return SimpleNamespace(
        id=pid or uuid.uuid4(),
        title="v2-test",
        status="recording",
    )


# ============================================================================
# POST /api/v1/hmp/diarize/run
# ============================================================================


@pytest.mark.asyncio
async def test_run_returns_202_and_registers_task(client_with_db, fake_service):
    ac, registry = client_with_db
    proto = _make_protocol_obj()
    registry.protocol = proto

    resp = await ac.post("/api/v1/hmp/diarize/run", json={"protocol_id": str(proto.id)})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["message"] == "Диаризация поставлена в очередь"
    assert "task_id" in body

    task_id = uuid.UUID(body["task_id"])
    rec = await _wait_for(task_id)
    assert rec is not None
    assert rec["status"] == "completed"
    assert "result_id" in rec


@pytest.mark.asyncio
async def test_run_passes_all_optional_fields(client_with_db, fake_service):
    ac, registry = client_with_db
    proto = _make_protocol_obj()
    registry.protocol = proto

    resp = await ac.post(
        "/api/v1/hmp/diarize/run",
        json={
            "protocol_id": str(proto.id),
            "num_speakers": 4,
            "min_speakers": 2,
            "max_speakers": 6,
            "pipeline_version": "pyannote-v3",
        },
    )
    assert resp.status_code == 202
    task_id = uuid.UUID(resp.json()["task_id"])
    await _wait_for(task_id)

    call = fake_service.calls[0]
    assert call["min_speakers"] == 2
    assert call["max_speakers"] == 6
    # num_speakers is stored on the task record, not forwarded
    rec = diarize_module._diarize_tasks[task_id]
    assert rec["num_speakers"] == 4
    assert rec["pipeline_version"] == "pyannote-v3"


@pytest.mark.asyncio
async def test_run_unknown_protocol_returns_404(client_with_db, fake_service):
    ac, _ = client_with_db
    # registry.protocol stays None → all sessions report "no protocol"
    resp = await ac.post(
        "/api/v1/hmp/diarize/run",
        json={"protocol_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
    assert "не найден" in resp.json()["detail"]
    # No tasks or active background tasks were spawned
    assert diarize_module._diarize_tasks == {}
    assert diarize_module._active_diarize_tasks == {}


@pytest.mark.asyncio
async def test_run_runner_marks_failed_on_service_exception(client_with_db):
    """When ``diarize_protocol`` raises, the runner sets status='failed' + error string."""
    from app.services import diarization as diarization_module_path

    fake = FakeDiarizationService(raise_exc=RuntimeError("nope"))
    import pytest as _pytest
    monkeypatch = _pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(diarization_module_path, "diarization_service", fake)
        ac, registry = client_with_db
        proto = _make_protocol_obj()
        registry.protocol = proto

        resp = await ac.post("/api/v1/hmp/diarize/run", json={"protocol_id": str(proto.id)})
        assert resp.status_code == 202
        task_id = uuid.UUID(resp.json()["task_id"])
        rec = await _wait_for(task_id)
        assert rec is not None
        assert rec["status"] == "failed"
        assert "nope" in rec["error"]
    finally:
        monkeypatch.undo()


@pytest.mark.asyncio
async def test_run_rejects_missing_protocol_id(client_with_db):
    ac, _ = client_with_db
    resp = await ac.post("/api/v1/hmp/diarize/run", json={})
    assert resp.status_code == 422
    assert "detail" in resp.json()


@pytest.mark.asyncio
async def test_run_rejects_num_speakers_out_of_range(client_with_db):
    ac, _ = client_with_db
    resp = await ac.post(
        "/api/v1/hmp/diarize/run",
        json={"protocol_id": str(uuid.uuid4()), "num_speakers": 999},
    )
    assert resp.status_code == 422

    resp = await ac.post(
        "/api/v1/hmp/diarize/run",
        json={"protocol_id": str(uuid.uuid4()), "min_speakers": 0},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_run_rejects_malformed_protocol_id(client_with_db):
    ac, _ = client_with_db
    resp = await ac.post(
        "/api/v1/hmp/diarize/run",
        json={"protocol_id": "not-a-uuid"},
    )
    assert resp.status_code == 422


# ============================================================================
# GET /api/v1/hmp/diarize/result/{protocol_id}
# ============================================================================


@pytest.mark.asyncio
async def test_get_result_returns_404_for_unknown_protocol(client_with_db):
    ac, _ = client_with_db
    resp = await ac.get(f"/api/v1/hmp/diarize/result/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert "не найден" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_result_returns_404_when_no_diarization_row(client_with_db):
    ac, registry = client_with_db
    proto = _make_protocol_obj()
    registry.protocol = proto
    # registry.diarization_result stays None

    resp = await ac.get(f"/api/v1/hmp/diarize/result/{proto.id}")
    assert resp.status_code == 404
    assert "ещё не готов" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_result_returns_full_payload(client_with_db):
    ac, registry = client_with_db
    proto = _make_protocol_obj()
    diar_row = SimpleNamespace(
        id=uuid.uuid4(),
        protocol_id=proto.id,
        der_score=12.5,
        num_speakers_detected=3,
        num_speakers_expected=4,
        pipeline_version="heuristic-v1",
        confidence_avg=0.91,
        segments_json=[{"speaker": "SPK_0", "start": 0.0, "end": 1.0}],
        created_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )
    registry.protocol = proto
    registry.diarization_result = diar_row

    resp = await ac.get(f"/api/v1/hmp/diarize/result/{proto.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(diar_row.id)
    assert body["protocol_id"] == str(proto.id)
    assert body["der_score"] == 12.5
    assert body["num_speakers_detected"] == 3
    assert body["num_speakers_expected"] == 4
    assert body["pipeline_version"] == "heuristic-v1"
    assert body["confidence_avg"] == 0.91
    assert isinstance(body["segments"], list)
    assert body["segments"][0]["speaker"] == "SPK_0"
    assert "created_at" in body


@pytest.mark.asyncio
async def test_get_result_handles_nullable_fields(client_with_db):
    ac, registry = client_with_db
    proto = _make_protocol_obj()
    diar_row = SimpleNamespace(
        id=uuid.uuid4(),
        protocol_id=proto.id,
        der_score=None,
        num_speakers_detected=None,
        num_speakers_expected=None,
        pipeline_version=None,
        confidence_avg=None,
        segments_json=None,
        created_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )
    registry.protocol = proto
    registry.diarization_result = diar_row

    resp = await ac.get(f"/api/v1/hmp/diarize/result/{proto.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["der_score"] is None
    assert body["confidence_avg"] is None
    assert body["num_speakers_detected"] is None
    assert body["num_speakers_expected"] is None
    assert body["pipeline_version"] is None
    assert body["segments"] == []  # segments_json=None -> []


@pytest.mark.asyncio
async def test_get_result_invalid_uuid_returns_422(client_with_db):
    ac, _ = client_with_db
    resp = await ac.get("/api/v1/hmp/diarize/result/not-a-uuid")
    assert resp.status_code == 422


# ============================================================================
# Schema unit-tests (covers model fields & defaults)
# ============================================================================


def test_diarize_run_request_defaults():
    req = DiarizeRunRequest(protocol_id=uuid.uuid4())
    assert req.num_speakers is None
    assert req.min_speakers is None
    assert req.max_speakers is None
    assert req.pipeline_version is None


def test_diarize_task_accepted_literal_status():
    ta = DiarizeTaskAccepted(
        task_id=uuid.uuid4(),
        protocol_id=uuid.uuid4(),
        status="queued",
        estimated_completion=datetime.now(timezone.utc),
    )
    assert ta.message == "Диаризация поставлена в очередь"
    assert ta.status == "queued"