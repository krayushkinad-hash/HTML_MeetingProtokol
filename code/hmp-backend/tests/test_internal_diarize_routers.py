"""Tests for app/routers/diarize.py — target 50%+ coverage (US-007).

Endpoints:
  POST /api/v1/hmp/diarize/run            -> 202 + DiarizeTaskAccepted
  GET  /api/v1/hmp/diarize/result/{id}    -> 200 / 404 (protocol) / 404 (no result)

Strategy
--------
``POST /api/v1/hmp/diarize/run`` launches an ``asyncio.create_task`` that calls
``diarization_service.diarize_protocol`` in a brand-new DB session.
We patch the module-level ``diarization_service`` with a stub to avoid
loading any heavy ML pipeline and to control success/failure.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


# ============================================================================
# Helpers
# ============================================================================

async def _make_protocol(db, title="Diarize Router Test"):
    from app.db.models import Protocol, ProtocolStatus

    p = Protocol(
        id=uuid.uuid4(),
        title=title,
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


def _make_fake_result(protocol_id: uuid.UUID):
    """Build an object that quacks like ``DiarizationResult`` for the runner."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        protocol_id=protocol_id,
        num_speakers_detected=3,
        num_speakers_expected=3,
        der_score=None,
        pipeline_version="heuristic-v1",
        confidence_avg=None,
        segments_json=[{"speaker": "SPK_0", "start": 0.0, "end": 1.0}],
        created_at=datetime.now(timezone.utc),
    )


class FakeDiarizationService:
    """Drop-in replacement for ``app.services.diarization.diarization_service``."""

    def __init__(self, raise_exc: Exception | None = None, result=None):
        self._raise = raise_exc
        self._result = result
        self.calls: list[dict] = []

    async def diarize_protocol(self, *, db, protocol_id, min_speakers=None, max_speakers=None):
        self.calls.append(
            {
                "protocol_id": protocol_id,
                "min_speakers": min_speakers,
                "max_speakers": max_speakers,
            }
        )
        if self._raise is not None:
            raise self._raise
        if self._result is not None:
            return self._result
        return _make_fake_result(protocol_id)


@pytest.fixture
def patch_diarization_service(monkeypatch):
    """Patch the module-level singleton referenced from inside the runner.

    The runner imports ``from app.services.diarization import diarization_service``
    at call time, so we patch the *module attribute*, not the router import.
    """
    from app.services import diarization as diarization_module

    fake = FakeDiarizationService()
    monkeypatch.setattr(diarization_module, "diarization_service", fake)
    return fake


@pytest.fixture
def diarize_tasks_cleanup():
    """Ensure module-level task registries don't leak between tests."""
    from app.routers import diarize

    diarize._diarize_tasks.clear()
    diarize._active_diarize_tasks.clear()
    yield
    diarize._diarize_tasks.clear()
    # cancel anything still alive
    for task in list(diarize._active_diarize_tasks.values()):
        if not task.done():
            task.cancel()
    diarize._active_diarize_tasks.clear()


async def _wait_for_task_completion(task_id: uuid.UUID, timeout: float = 2.0):
    """Spin until the in-memory task reaches a terminal status."""
    from app.routers import diarize

    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        record = diarize._diarize_tasks.get(task_id)
        if record and record.get("status") in {"completed", "failed"}:
            return record
        await asyncio.sleep(0.02)
    return diarize._diarize_tasks.get(task_id)


# ============================================================================
# POST /api/v1/hmp/diarize/run — happy paths
# ============================================================================

@pytest.mark.asyncio
async def test_run_returns_202_with_task_id(
    client, db_session, patch_diarization_service, diarize_tasks_cleanup
):
    proto = await _make_protocol(db_session, title="happy-202")

    resp = await client.post(
        "/api/v1/hmp/diarize/run",
        json={"protocol_id": str(proto.id)},
    )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert "task_id" in body
    # estimated_completion — just verify presence + parseable
    assert "estimated_completion" in body
    assert body["message"] == "Диаризация поставлена в очередь"

    task_id = uuid.UUID(body["task_id"])
    await _wait_for_task_completion(task_id)
    record = patch_diarization_service.calls[0]
    assert record["protocol_id"] == proto.id


@pytest.mark.asyncio
async def test_run_passes_speaker_hints_to_service(
    client, db_session, patch_diarization_service, diarize_tasks_cleanup
):
    proto = await _make_protocol(db_session, title="hints")

    resp = await client.post(
        "/api/v1/hmp/diarize/run",
        json={
            "protocol_id": str(proto.id),
            "min_speakers": 2,
            "max_speakers": 5,
            "pipeline_version": "v-test",
        },
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    task_id = uuid.UUID(body["task_id"])
    await _wait_for_task_completion(task_id)

    # Service received the speaker-hint fields
    assert patch_diarization_service.calls[0]["min_speakers"] == 2
    assert patch_diarization_service.calls[0]["max_speakers"] == 5


@pytest.mark.asyncio
async def test_run_completed_status_persists_result_id(
    client, db_session, patch_diarization_service, diarize_tasks_cleanup
):
    proto = await _make_protocol(db_session, title="completed")

    resp = await client.post(
        "/api/v1/hmp/diarize/run",
        json={"protocol_id": str(proto.id)},
    )
    assert resp.status_code == 202
    task_id = uuid.UUID(resp.json()["task_id"])

    record = await _wait_for_task_completion(task_id)
    assert record is not None
    assert record["status"] == "completed"
    assert "result_id" in record
    # stored id is a stringified UUID
    uuid.UUID(record["result_id"])  # raises if malformed


@pytest.mark.asyncio
async def test_run_marks_failed_when_service_raises(
    client, db_session, monkeypatch, diarize_tasks_cleanup
):
    from app.services import diarization as diarization_module

    fake = FakeDiarizationService(raise_exc=RuntimeError("boom"))
    monkeypatch.setattr(diarization_module, "diarization_service", fake)

    proto = await _make_protocol(db_session, title="failed")

    resp = await client.post(
        "/api/v1/hmp/diarize/run",
        json={"protocol_id": str(proto.id)},
    )
    assert resp.status_code == 202
    task_id = uuid.UUID(resp.json()["task_id"])

    record = await _wait_for_task_completion(task_id)
    assert record is not None
    assert record["status"] == "failed"
    # Error string is truncated to 500 chars but must contain the original message
    assert "boom" in record["error"]


# ============================================================================
# POST /api/v1/hmp/diarize/run — error paths
# ============================================================================

@pytest.mark.asyncio
async def test_run_unknown_protocol_returns_404(
    client, patch_diarization_service, diarize_tasks_cleanup
):
    """Non-existent protocol → 404, no background task spawned."""
    from app.routers import diarize as diarize_module

    resp = await client.post(
        "/api/v1/hmp/diarize/run",
        json={"protocol_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
    assert "не найден" in resp.json()["detail"]
    # No task should have been registered
    assert diarize_module._diarize_tasks == {}
    assert diarize_module._active_diarize_tasks == {}


@pytest.mark.asyncio
async def test_run_invalid_payload_returns_422(client, patch_diarization_service):
    """Missing protocol_id → Pydantic validation 422."""
    resp = await client.post("/api/v1/hmp/diarize/run", json={})
    assert resp.status_code == 422
    body = resp.json()
    # FastAPI's standard validation error envelope
    assert "detail" in body


@pytest.mark.asyncio
async def test_run_num_speakers_above_max_returns_422(
    client, patch_diarization_service
):
    """Field constraint ge=1/le=20 → 422 when violated."""
    resp = await client.post(
        "/api/v1/hmp/diarize/run",
        json={"protocol_id": str(uuid.uuid4()), "num_speakers": 999},
    )
    assert resp.status_code == 422


# ============================================================================
# GET /api/v1/hmp/diarize/result/{protocol_id}
# ============================================================================

@pytest.mark.asyncio
async def test_get_result_unknown_protocol_returns_404(client):
    resp = await client.get(f"/api/v1/hmp/diarize/result/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert "не найден" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_result_no_diarization_yet_returns_404(
    client, db_session
):
    proto = await _make_protocol(db_session, title="no-result")

    resp = await client.get(f"/api/v1/hmp/diarize/result/{proto.id}")
    assert resp.status_code == 404
    assert "ещё не готов" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_result_returns_full_payload(client, db_session):
    """When a DiarizationResult row exists, GET returns its serialised form."""
    from app.db.models import DiarizationResult

    proto = await _make_protocol(db_session, title="with-result")
    result = DiarizationResult(
        id=uuid.uuid4(),
        protocol_id=proto.id,
        der_score=12.5,
        num_speakers_detected=4,
        num_speakers_expected=3,
        pipeline_version="heuristic-v1",
        confidence_avg=0.87,
        segments_json=[{"speaker": "SPK_0", "start": 0.0, "end": 1.5}],
    )
    db_session.add(result)
    await db_session.commit()

    resp = await client.get(f"/api/v1/hmp/diarize/result/{proto.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["protocol_id"] == str(proto.id)
    assert body["der_score"] == 12.5
    assert body["num_speakers_detected"] == 4
    assert body["num_speakers_expected"] == 3
    assert body["pipeline_version"] == "heuristic-v1"
    assert body["confidence_avg"] == 0.87
    assert isinstance(body["segments"], list)
    assert body["segments"][0]["speaker"] == "SPK_0"
    assert "created_at" in body


@pytest.mark.asyncio
async def test_get_result_handles_null_metric_fields(client, db_session):
    """``der_score`` and ``confidence_avg`` are nullable → returned as ``null``."""
    from app.db.models import DiarizationResult

    proto = await _make_protocol(db_session, title="null-fields")
    result = DiarizationResult(
        id=uuid.uuid4(),
        protocol_id=proto.id,
        der_score=None,
        num_speakers_detected=None,
        confidence_avg=None,
        segments_json=None,
    )
    db_session.add(result)
    await db_session.commit()

    resp = await client.get(f"/api/v1/hmp/diarize/result/{proto.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["der_score"] is None
    assert body["confidence_avg"] is None
    assert body["num_speakers_detected"] is None
    # segments_json=None → []
    assert body["segments"] == []


@pytest.mark.asyncio
async def test_get_result_invalid_uuid_returns_422(client):
    """Non-UUID path parameter → Pydantic 422."""
    resp = await client.get("/api/v1/hmp/diarize/result/not-a-uuid")
    assert resp.status_code == 422
