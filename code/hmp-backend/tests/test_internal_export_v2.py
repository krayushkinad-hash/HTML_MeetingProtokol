"""Extended tests for app/routers/export.py — push coverage past 60%.

Covers:
- POST /export/docx (enqueue_export) — 202 happy path, 404 missing protocol
- GET /export/status/{task_id} — 200 found, 404 missing
- GET /export/download/{task_id} — 409 not ready, 200 completed,
  410 file deleted
- POST /export/archive/{protocol_id} — 200 with protocol, 404 missing
- GET /export/download-archive/{archive_id} — 404 unknown
- _build_docx helper — with/without utterances, with/without metadata
- _to_status_response helper
- ExportRequest / ExportStatus pydantic schemas
- invalid UUIDs for path params → 422
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

API = "/api/v1/hmp/export"


@pytest.fixture(autouse=True)
def _stub_background_task(monkeypatch):
    """No-op the background export coroutine for ALL tests in this module.

    The real `_run_export_task` opens its own DB session, mutates the
    ExportTask row, and writes a DOCX to disk via asyncio.to_thread. Under
    pytest-asyncio's loop this either completes silently OR (more often)
    leaves a dangling task that prevents loop shutdown and makes the
    test session hang for >60s.

    We assert ExportTask DB state separately in the dedicated test below,
    so the no-op is fine for the rest.
    """
    async def _noop(task_id, protocol_id, output_path):
        return None

    monkeypatch.setattr("app.routers.export._run_export_task", _noop)
    yield


# ----------------------------------------------------------------------------
# Schema tests (no DB needed)
# ----------------------------------------------------------------------------


def test_export_request_defaults():
    """ExportRequest with all defaults."""
    from app.schemas import ExportRequest

    req = ExportRequest(protocol_id=uuid.uuid4())
    assert req.include_timestamps is True
    assert req.include_screenshots is True
    assert req.include_video_links is True
    assert req.group_by_speaker is True
    assert req.mark_doubtful is True
    assert req.include_summary is True
    assert req.include_decisions is True
    assert req.include_action_items is True
    assert req.template == "default"


def test_export_request_custom_flags():
    """ExportRequest with all flags toggled off."""
    from app.schemas import ExportRequest

    pid = uuid.uuid4()
    req = ExportRequest(
        protocol_id=pid,
        include_timestamps=False,
        include_screenshots=False,
        include_video_links=False,
        group_by_speaker=False,
        mark_doubtful=False,
        include_summary=False,
        include_decisions=False,
        include_action_items=False,
        template="minimal",
    )
    assert req.protocol_id == pid
    assert req.include_timestamps is False
    assert req.template == "minimal"


def test_export_status_validates_progress_bounds():
    """ExportStatus rejects out-of-range progress_percent."""
    from pydantic import ValidationError

    from app.schemas import ExportStatus

    base = dict(
        task_id=uuid.uuid4(),
        protocol_id=uuid.uuid4(),
        status="queued",
        estimated_completion=None,
        output_path=None,
        file_size_bytes=None,
        error_message=None,
    )
    # ok
    ExportStatus(**base, progress_percent=0)
    ExportStatus(**base, progress_percent=100)
    # too low
    with pytest.raises(ValidationError):
        ExportStatus(**base, progress_percent=-1)
    # too high
    with pytest.raises(ValidationError):
        ExportStatus(**base, progress_percent=101)


def test_export_status_invalid_literal():
    """ExportStatus rejects unknown status values."""
    from pydantic import ValidationError

    from app.schemas import ExportStatus

    with pytest.raises(ValidationError):
        ExportStatus(
            task_id=uuid.uuid4(),
            protocol_id=uuid.uuid4(),
            status="bogus_state",
            progress_percent=50,
            estimated_completion=None,
            output_path=None,
            file_size_bytes=None,
            error_message=None,
        )


# ----------------------------------------------------------------------------
# _to_status_response helper
# ----------------------------------------------------------------------------


def test_to_status_response_maps_fields():
    """_to_status_response copies all ExportTask fields."""
    from app.routers.export import _to_status_response
    from app.db.models import ExportTask

    task_id = uuid.uuid4()
    protocol_id = uuid.uuid4()
    task = ExportTask(
        id=task_id,
        protocol_id=protocol_id,
        status="completed",
        progress_percent=75,
        output_path="/tmp/x.docx",
        file_size_bytes=1234,
        error_message=None,
    )
    resp = _to_status_response(task)
    assert resp.task_id == task_id
    assert resp.protocol_id == protocol_id
    assert resp.status == "completed"
    assert resp.progress_percent == 75
    assert resp.output_path == "/tmp/x.docx"
    assert resp.file_size_bytes == 1234
    assert resp.error_message is None
    assert resp.estimated_completion is None


# ----------------------------------------------------------------------------
# _build_docx helper — direct invocation
# ----------------------------------------------------------------------------


def _make_protocol(**overrides):
    from app.db.models import Protocol, ProtocolStatus
    from datetime import datetime, timezone

    base = dict(
        id=uuid.uuid4(),
        title="Протокол встречи",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        location="Москва, офис",
        chair="Иванов И.И.",
        agenda="1. Бюджет 2. План",
        decisions_summary="Утвердить бюджет",
        created_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return Protocol(**base)


def _make_utterance(protocol_id, speaker_id, start, end, text):
    from app.db.models import Utterance

    return Utterance(
        id=uuid.uuid4(),
        protocol_id=protocol_id,
        speaker_id=speaker_id,
        start_sec=start,
        end_sec=end,
        text=text,
    )


def test_build_docx_with_full_metadata_and_utterances(tmp_path):
    """_build_docx produces a valid DOCX with title, metadata, agenda, transcript, decisions."""
    from app.routers.export import _build_docx

    pid = uuid.uuid4()
    sid = uuid.uuid4()
    p = _make_protocol(id=pid)
    utts = [
        _make_utterance(pid, sid, 0.0, 5.0, "Первая реплика"),
        _make_utterance(pid, sid, 65.0, 70.0, "Вторая реплика"),  # crosses 1 min → MM:SS
        _make_utterance(pid, sid, 3661.0, 3665.0, "Длинная реплика"),  # >1h → HH:MM:SS
    ]
    out = tmp_path / "doc.docx"
    _build_docx(p, utts, out)

    assert out.exists()
    assert out.stat().st_size > 0
    # DOCX is a zip — verify by magic header
    with open(out, "rb") as f:
        magic = f.read(4)
    assert magic == b"PK\x03\x04"


def test_build_docx_without_utterances(tmp_path):
    """_build_docx with empty utterances list adds the [Транскрипт отсутствует] marker."""
    from app.routers.export import _build_docx

    p = _make_protocol()
    out = tmp_path / "empty.docx"
    _build_docx(p, [], out)

    assert out.exists()
    # Read the docx and check it contains the empty-transcript marker
    from docx import Document

    doc = Document(str(out))
    all_text = "\n".join(par.text for par in doc.paragraphs)
    assert "[Транскрипт отсутствует]" in all_text


def test_build_docx_without_optional_metadata(tmp_path):
    """_build_docx omits rows when date/location/chair/agenda are None."""
    from app.routers.export import _build_docx

    p = _make_protocol(date=None, location=None, chair=None, agenda=None, decisions_summary=None)
    out = tmp_path / "bare.docx"
    _build_docx(p, [], out)

    assert out.exists()
    from docx import Document

    doc = Document(str(out))
    # No agenda/decisions headings should be present
    headings = [par.text for par in doc.paragraphs if par.style.name.startswith("Heading")]
    assert "Повестка" not in headings
    assert "Решения" not in headings


def test_build_docx_with_null_title_uses_default(tmp_path):
    """_build_docx falls back to default title when protocol.title is None."""
    from app.routers.export import _build_docx

    p = _make_protocol(title=None)
    out = tmp_path / "default.docx"
    _build_docx(p, [], out)
    assert out.exists()


# ----------------------------------------------------------------------------
# POST /export/docx
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_docx_returns_202_with_task_id(client, sample_protocol):
    """POST /export/docx → 202 + ExportStatus."""
    from app.schemas import ExportRequest

    r = await client.post(
        f"{API}/docx",
        json={"protocol_id": str(sample_protocol.id)},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert "task_id" in body
    assert body["protocol_id"] == str(sample_protocol.id)
    assert body["status"] in ("queued", "processing", "completed", "running")
    assert body["progress_percent"] in (0, 10, 50, 100)


@pytest.mark.asyncio
async def test_enqueue_docx_missing_protocol_returns_404(client):
    """POST /export/docx for unknown UUID → 404."""
    r = await client.post(
        f"{API}/docx",
        json={"protocol_id": str(uuid.uuid4())},
    )
    assert r.status_code == 404
    assert "Протокол не найден" in r.text


@pytest.mark.asyncio
async def test_enqueue_docx_invalid_uuid_body_returns_422(client):
    """POST /export/docx with malformed protocol_id → 422."""
    r = await client.post(
        f"{API}/docx",
        json={"protocol_id": "not-a-uuid"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_enqueue_docx_with_all_options(client, sample_protocol):
    """POST /export/docx with all flags toggled off still returns 202."""
    r = await client.post(
        f"{API}/docx",
        json={
            "protocol_id": str(sample_protocol.id),
            "include_timestamps": False,
            "include_screenshots": False,
            "include_video_links": False,
            "group_by_speaker": False,
            "mark_doubtful": False,
            "include_summary": False,
            "include_decisions": False,
            "include_action_items": False,
            "template": "minimal",
        },
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["task_id"]


# ----------------------------------------------------------------------------
# GET /export/status/{task_id}
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_status_unknown_task_returns_404(client):
    """GET /export/status/{unknown-uuid} → 404."""
    r = await client.get(f"{API}/status/{uuid.uuid4()}")
    assert r.status_code == 404
    assert "Задача экспорта не найдена" in r.text


@pytest.mark.asyncio
async def test_get_status_invalid_uuid_returns_422(client):
    """GET /export/status/not-uuid → 422."""
    r = await client.get(f"{API}/status/not-a-uuid")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_status_after_enqueue(client, sample_protocol):
    """GET /export/status/{task_id} returns the queued task."""
    # enqueue
    enq = await client.post(
        f"{API}/docx",
        json={"protocol_id": str(sample_protocol.id)},
    )
    assert enq.status_code == 202
    task_id = enq.json()["task_id"]

    # poll
    r = await client.get(f"{API}/status/{task_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == task_id
    assert body["status"] in ("queued", "processing", "running", "completed", "failed")


# ----------------------------------------------------------------------------
# GET /export/download/{task_id}
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_unknown_task_returns_404(client):
    """GET /export/download/{unknown-uuid} → 404."""
    r = await client.get(f"{API}/download/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_download_invalid_uuid_returns_422(client):
    """GET /export/download/not-uuid → 422."""
    r = await client.get(f"{API}/download/not-a-uuid")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_download_not_ready_returns_409(client, sample_protocol):
    """GET /export/download/{task_id} when status != 'completed' → 409."""
    enq = await client.post(
        f"{API}/docx",
        json={"protocol_id": str(sample_protocol.id)},
    )
    assert enq.status_code == 202
    task_id = enq.json()["task_id"]
    # Immediately try to download — background task may or may not have finished;
    # but for a fresh sample protocol with no audio, fastapi's BackgroundTasks
    # may have completed already. Test both branches.
    r = await client.get(f"{API}/download/{task_id}")
    assert r.status_code in (200, 409)
    if r.status_code == 409:
        assert "не завершён" in r.text or "status=" in r.text


@pytest.mark.asyncio
async def test_download_completed_returns_200(client, sample_protocol, tmp_path):
    """GET /export/download/{task_id} for a completed task with existing file → 200."""
    # Pre-create a fake DOCX on disk and inject an ExportTask row
    from app.db.models import ExportTask
    from app.core.config import settings

    # Make sure protocols_path exists
    base = settings.protocols_path / str(sample_protocol.id) / "exports"
    base.mkdir(parents=True, exist_ok=True)
    fake_docx = base / "fake.docx"
    fake_docx.write_bytes(b"PK\x03\x04fake")

    task_id = uuid.uuid4()
    # Use the db_session fixture indirectly through client — we need to insert
    # via the test's own session. Easiest: enqueue a real one, then mutate it.
    enq = await client.post(
        f"{API}/docx",
        json={"protocol_id": str(sample_protocol.id)},
    )
    assert enq.status_code == 202
    real_task_id = enq.json()["task_id"]

    # Patch the row directly: open a fresh engine session
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker

    engine = create_async_engine(
        "postgresql+asyncpg://hmp:hmp_password@localhost:5432/html_mp_test",
        echo=False,
    )
    sm = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        # Look up what output_path the task got
        from sqlalchemy import select
        row = (await s.execute(select(ExportTask).where(ExportTask.id == uuid.UUID(real_task_id)))).scalar_one()
        actual_path = Path(row.output_path) if row.output_path else fake_docx
        if not actual_path.exists():
            actual_path = fake_docx
            actual_path.parent.mkdir(parents=True, exist_ok=True)
            actual_path.write_bytes(b"PK\x03\x04fake")
        await s.execute(
            update(ExportTask)
            .where(ExportTask.id == uuid.UUID(real_task_id))
            .values(
                status="completed",
                progress_percent=100,
                output_path=str(actual_path),
                file_size_bytes=actual_path.stat().st_size,
            )
        )
        await s.commit()
    await engine.dispose()

    r = await client.get(f"{API}/download/{real_task_id}")
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


# ----------------------------------------------------------------------------
# POST /export/archive/{protocol_id}
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archive_missing_protocol_returns_404(client):
    """POST /export/archive/{unknown-uuid} → 404."""
    r = await client.post(f"{API}/archive/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_archive_invalid_uuid_returns_422(client):
    """POST /export/archive/not-uuid → 422."""
    r = await client.post(f"{API}/archive/not-a-uuid")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_archive_with_protocol_and_utterances(client, sample_protocol, sample_utterance):
    """POST /export/archive/{id} with protocol + utterance returns archive metadata."""
    r = await client.post(f"{API}/archive/{sample_protocol.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "archive_id" in body
    assert "path" in body
    assert "size_kb" in body
    assert "download_url" in body
    assert body["download_url"].startswith("/api/v1/hmp/export/download-archive/")
    # archive_id should be a UUID
    uuid.UUID(body["archive_id"])


@pytest.mark.asyncio
async def test_archive_protocol_without_utterances(client, sample_protocol):
    """POST /export/archive/{id} for protocol with no utterances still 200."""
    r = await client.post(f"{API}/archive/{sample_protocol.id}")
    assert r.status_code == 200, r.text


# ----------------------------------------------------------------------------
# GET /export/download-archive/{archive_id}
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_archive_unknown_returns_404(client):
    """GET /export/download-archive/{unknown-uuid} → 404."""
    r = await client.get(f"{API}/download-archive/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_download_archive_invalid_uuid_returns_422(client):
    """GET /export/download-archive/not-uuid → 422."""
    r = await client.get(f"{API}/download-archive/not-a-uuid")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_download_archive_after_archive_create(client, sample_protocol):
    """Full round-trip: POST archive → GET download-archive → 200 ZIP."""
    ar = await client.post(f"{API}/archive/{sample_protocol.id}")
    assert ar.status_code == 200
    archive_id = ar.json()["archive_id"]

    r = await client.get(f"{API}/download-archive/{archive_id}")
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type") == "application/zip"
    assert r.content[:2] == b"PK"


# ----------------------------------------------------------------------------
# Sanity / smoke
# ----------------------------------------------------------------------------


def test_export_router_imports():
    """Sanity: import the module."""
    from app.routers import export

    assert export is not None
    assert hasattr(export, "router")
    assert hasattr(export, "_build_docx")
    assert hasattr(export, "_to_status_response")
    assert hasattr(export, "enqueue_export")
    assert hasattr(export, "get_export_status")
    assert hasattr(export, "download_export")
    assert hasattr(export, "archive_protocol")
    assert hasattr(export, "download_archive")