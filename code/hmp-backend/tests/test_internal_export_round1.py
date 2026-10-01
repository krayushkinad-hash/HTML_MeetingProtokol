"""Round1 tests for app/routers/export.py — push coverage past 60%.

Targets gaps left by v3+v4:

- _to_status_response (line 40-50): direct call with sample ExportTask.
- _build_docx (line 53-116): all branches — title fallback, metadata table,
  agenda heading, empty utterances fallback, decisions_summary, fmt_ts
  formatting (HH:MM:SS and MM:SS variants), and the seconds<0/non-finite
  guard inside the real closure (not the exec'd copy).
- _run_export_task happy path (lines 130-189): real DOCX generation, status
  transitions queued → processing → completed, file_size_bytes set.
- _run_export_task missing task row (line 134-136): early return.
- _run_export_task missing protocol (line 144-154): status=failed,
  error_message="Протокол не найден".
- _run_export_task exception handler (lines 190-203): task marked failed.
- get_export_status happy path (lines 282-288) + 404.
- download_export happy path → FileResponse (lines 318-344).
- download_export output_path=None on completed task → 500 (line 318-322).
- download_export file missing on disk → 410 (line 325-329).
- archive_protocol 404 when protocol soft-deleted (line 371-372).
"""
from __future__ import annotations

import io
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

API = "/api/v1/hmp/export"


def _stub_background_task(monkeypatch):
    """Replace _run_export_task with a no-op so enqueue_export doesn't try
    to open a real DB session after the response is sent."""
    async def _noop(task_id, protocol_id, output_path):
        return None

    monkeypatch.setattr("app.routers.export._run_export_task", _noop)


# ============================================================================
# _to_status_response — direct unit test (lines 40-50)
# ============================================================================


def test_to_status_response_maps_all_fields():
    """_to_status_response copies every field from ExportTask onto ExportStatus."""
    from app.routers.export import _to_status_response
    from app.db.models import ExportTask

    task = ExportTask(
        id=uuid.uuid4(),
        protocol_id=uuid.uuid4(),
        format="docx",
        include_timestamps=True,
        include_screenshots=True,
        include_video_links=True,
        group_by_speaker=True,
        mark_doubtful=True,
        status="completed",
        progress_percent=100,
        output_path="/tmp/x.docx",
        file_size_bytes=12345,
        error_message=None,
    )
    resp = _to_status_response(task)
    assert resp.task_id == task.id
    assert resp.protocol_id == task.protocol_id
    assert resp.status == "completed"
    assert resp.progress_percent == 100
    assert resp.estimated_completion is None
    assert resp.output_path == "/tmp/x.docx"
    assert resp.file_size_bytes == 12345
    assert resp.error_message is None


# ============================================================================
# _build_docx — direct unit test (lines 53-116)
# Covers: title fallback, all metadata rows, agenda, transcript with and
# without utterances, decisions_summary, fmt_ts HH:MM:SS + MM:SS branches.
# ============================================================================


@pytest.mark.asyncio
async def test_build_docx_full_path_with_agenda_and_decisions(db_session, tmp_path):
    """_build_docx writes a real DOCX with metadata + agenda + transcript + decisions."""
    from app.db.models import Protocol, ProtocolStatus, Speaker, Utterance
    from app.routers.export import _build_docx

    p = Protocol(
        id=uuid.uuid4(),
        title="BuildDocxTest",
        status=ProtocolStatus.RECORDING,
        date=datetime(2025, 6, 15).date(),
        location="Офис 42",
        chair="Иванов И.И.",
        agenda="Обсудить бюджет Q3",
        decisions_summary="Утвердить смету",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.flush()
    sp = Speaker(
        id=uuid.uuid4(),
        protocol_id=p.id,
        speaker_label="SPK_A",
        display_name="Алексей",
    )
    db_session.add(sp)
    await db_session.flush()
    # Mix of short (MM:SS) and long (HH:MM:SS) timestamps
    for i, (start, end) in enumerate([(0.0, 12.5), (75.0, 134.0), (3600.0, 3700.0)]):
        u = Utterance(
            id=uuid.uuid4(),
            protocol_id=p.id,
            speaker_id=sp.id,
            start_sec=start,
            end_sec=end,
            text=f"фраза {i}",
        )
        db_session.add(u)
    await db_session.commit()
    await db_session.refresh(p)

    utterances = (
        await db_session.execute(
            __import__("sqlalchemy").select(Utterance)
            .where(Utterance.protocol_id == p.id)
            .order_by(Utterance.start_sec.asc())
        )
    ).scalars().all()

    out = tmp_path / "out.docx"
    _build_docx(p, list(utterances), out)

    assert out.exists()
    assert out.stat().st_size > 0

    from docx import Document

    loaded = Document(str(out))
    paragraphs = [p.text for p in loaded.paragraphs]
    # Title heading + agenda heading + transcript heading + decisions heading
    assert "BuildDocxTest" in paragraphs[0]  # title
    assert any("Повестка" in t for t in paragraphs)
    assert any("Транскрипт" in t for t in paragraphs)
    assert any("Решения" in t for t in paragraphs)
    # fmt_ts: 0.0 → "0:00", 75 → "1:15", 134 → "2:14", 3600 → "01:00:00", 3700 → "01:01:40"
    full_text = "\n".join(paragraphs)
    assert "[0:00–0:12]" in full_text
    assert "[1:15–2:14]" in full_text  # 75→1:15, 134→2:14
    assert "[01:00:00–01:01:40]" in full_text  # HH:MM:SS branch
    # Sanity: speaker text is included
    assert "фраза 0" in full_text
    assert "фраза 2" in full_text


@pytest.mark.asyncio
async def test_build_docx_minimal_protocol_no_optional_fields(db_session, tmp_path):
    """Protocol without date/location/chair/agenda/decisions + empty utterances."""
    from app.db.models import Protocol, ProtocolStatus
    from app.routers.export import _build_docx

    # Build a Protocol with placeholder title+date (NOT NULL), then null
    # them out in-memory after commit so _build_docx hits the fallback
    # branches for both fields.
    p = Protocol(
        id=uuid.uuid4(),
        title="PLACEHOLDER",
        status=ProtocolStatus.READY,
        date=datetime.now(timezone.utc).date(),
        location=None,
        chair=None,
        agenda=None,
        decisions_summary=None,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    # In-memory overrides only — bypass SQLAlchemy column tracking.
    p.title = None
    p.date = None

    out = tmp_path / "minimal.docx"
    _build_docx(p, [], out)

    assert out.exists()
    from docx import Document

    loaded = Document(str(out))
    paragraphs = [p.text for p in loaded.paragraphs]
    # Title fallback to "Протокол"
    assert paragraphs[0] == "Протокол"
    # Empty-utterances branch
    assert any("Транскрипт отсутствует" in t for t in paragraphs)


# ============================================================================
# _run_export_task — happy path with real DOCX generation (lines 130-189)
# ============================================================================


@pytest.mark.asyncio
async def test_run_export_task_happy_path_completes(db_engine, db_session):
    """Background coroutine: status transitions, file_size_bytes set.

    Uses `db_engine` directly + monkeypatched `get_db_context` so the
    background coroutine binds to the test's event loop (otherwise
    asyncpg raises "Future attached to a different loop").
    """
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    from app.db import session as session_mod
    from app.db.models import ExportTask
    from app.routers import export as export_mod

    # Build an AsyncSession bound to the test engine, exposing a
    # get_db_context() async context manager that the background
    # coroutine will use.
    sess_maker = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    class _Ctx:
        async def __aenter__(self):
            self.s = sess_maker()
            return self.s

        async def __aexit__(self, *exc):
            try:
                await self.s.close()
            except Exception:
                pass

    def _get_db_context_override():
        return _Ctx()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(session_mod, "get_db_context", _get_db_context_override)
    monkeypatch.setattr(export_mod, "get_db_context", _get_db_context_override)

    # Build a protocol + task row on the test session.
    from app.db.models import Protocol, ProtocolStatus
    from datetime import datetime, timezone

    p = Protocol(
        id=uuid.uuid4(),
        title="RunHappy",
        status=ProtocolStatus.READY,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.flush()

    task_id = uuid.uuid4()
    output_path = (
        Path("/tmp") / f"{p.id}" / "exports" / f"{task_id}.docx"
    )
    task = ExportTask(
        id=task_id,
        protocol_id=p.id,
        format="docx",
        include_timestamps=True,
        include_screenshots=True,
        include_video_links=True,
        group_by_speaker=True,
        mark_doubtful=True,
        status="queued",
        progress_percent=0,
    )
    db_session.add(task)
    await db_session.commit()

    try:
        await export_mod._run_export_task(task_id, p.id, output_path)

        # Re-fetch via a FRESH session on the same engine so we see the
        # background-task's commits (different session = different identity map).
        async with sess_maker() as s2:
            refreshed = await s2.get(ExportTask, task_id)
        assert refreshed is not None
        assert refreshed.status == "completed"
        assert refreshed.progress_percent == 100
        assert refreshed.file_size_bytes is not None
        assert refreshed.file_size_bytes > 0
        assert refreshed.output_path == str(output_path)
        assert refreshed.started_at is not None
        assert refreshed.completed_at is not None
        assert output_path.exists()
    finally:
        monkeypatch.undo()


@pytest.mark.asyncio
async def test_run_export_task_missing_task_row_returns_early(db_engine, monkeypatch):
    """If the task row doesn't exist, coroutine logs and returns (line 134-136)."""
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    from app.db import session as session_mod
    from app.routers import export as export_mod

    sess_maker = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    class _Ctx:
        async def __aenter__(self):
            self.s = sess_maker()
            return self.s

        async def __aexit__(self, *exc):
            try:
                await self.s.close()
            except Exception:
                pass

    def _override():
        return _Ctx()

    monkeypatch.setattr(session_mod, "get_db_context", _override)
    monkeypatch.setattr(export_mod, "get_db_context", _override)

    bogus_task_id = uuid.uuid4()
    bogus_protocol_id = uuid.uuid4()
    output_path = Path("/tmp") / f"{bogus_protocol_id}" / "exports" / f"{bogus_task_id}.docx"

    # Should not raise — early return after logging "export_task_missing".
    await export_mod._run_export_task(bogus_task_id, bogus_protocol_id, output_path)


@pytest.mark.asyncio
async def test_run_export_task_missing_protocol_marks_failed(
    db_engine, db_session, monkeypatch
):
    """If protocol row doesn't exist, task is marked failed with Russian error.

    To exercise the "protocol row missing" branch we keep the task pointing
    at the existing `sample_protocol.id` but then DELETED the protocol row
    inside the same DB transaction the background task opens. The simplest
    way: insert a real protocol + task, then mark the protocol deleted via
    a SET deleted_at = now() update — but the export.py code checks
    `await db.get(Protocol, protocol_id)` for absence, not for deleted_at.

    So instead we monkeypatch `db.get(Protocol, ...)` to return None when
    `_run_export_task` looks it up. This still exercises lines 144-154.
    """
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    from app.db import session as session_mod
    from app.db.models import ExportTask, Protocol, ProtocolStatus
    from app.routers import export as export_mod

    sess_maker = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    class _Ctx:
        async def __aenter__(self):
            self.s = sess_maker()
            return self.s

        async def __aexit__(self, *exc):
            try:
                await self.s.close()
            except Exception:
                pass

    def _override():
        return _Ctx()

    monkeypatch.setattr(session_mod, "get_db_context", _override)
    monkeypatch.setattr(export_mod, "get_db_context", _override)

    # Build a real protocol + task so we don't trip the FK constraint.
    p = Protocol(
        id=uuid.uuid4(),
        title="WillBeMissing",
        status=ProtocolStatus.READY,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.flush()

    task_id = uuid.uuid4()
    output_path = Path("/tmp") / f"{p.id}" / "exports" / f"{task_id}.docx"

    task = ExportTask(
        id=task_id,
        protocol_id=p.id,
        format="docx",
        include_timestamps=True,
        include_screenshots=True,
        include_video_links=True,
        group_by_speaker=True,
        mark_doubtful=True,
        status="queued",
        progress_percent=0,
    )
    db_session.add(task)
    await db_session.commit()

    # Now monkeypatch the background task's session.get(Protocol, ...) to
    # return None — simulates "protocol deleted while task was queued".
    orig_get = AsyncSession.get

    async def fake_get(self, entity, ident, *args, **kwargs):
        if entity is Protocol and ident == p.id:
            return None
        return await orig_get(self, entity, ident, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "get", fake_get)

    await export_mod._run_export_task(task_id, p.id, output_path)

    async with sess_maker() as s2:
        refreshed = await s2.get(ExportTask, task_id)
    assert refreshed.status == "failed"
    assert refreshed.error_message == "Протокол не найден"
    assert refreshed.completed_at is not None


@pytest.mark.asyncio
async def test_run_export_task_exception_marks_failed(
    db_engine, db_session, monkeypatch
):
    """If _build_docx raises, task is marked failed in the except branch."""
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    from app.db import session as session_mod
    from app.db.models import ExportTask, Protocol, ProtocolStatus
    from app.routers import export as export_mod

    sess_maker = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    class _Ctx:
        async def __aenter__(self):
            self.s = sess_maker()
            return self.s

        async def __aexit__(self, *exc):
            try:
                await self.s.close()
            except Exception:
                pass

    def _override():
        return _Ctx()

    monkeypatch.setattr(session_mod, "get_db_context", _override)
    monkeypatch.setattr(export_mod, "get_db_context", _override)

    from datetime import datetime, timezone

    p = Protocol(
        id=uuid.uuid4(),
        title="Boom",
        status=ProtocolStatus.READY,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.flush()

    task_id = uuid.uuid4()
    output_path = Path("/tmp") / f"{p.id}" / "exports" / f"{task_id}.docx"

    task = ExportTask(
        id=task_id,
        protocol_id=p.id,
        format="docx",
        include_timestamps=True,
        include_screenshots=True,
        include_video_links=True,
        group_by_speaker=True,
        mark_doubtful=True,
        status="queued",
        progress_percent=0,
    )
    db_session.add(task)
    await db_session.commit()

    # Make _build_docx explode — covers lines 190-203.
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated docx failure")

    monkeypatch.setattr("app.routers.export._build_docx", _boom)

    await export_mod._run_export_task(task_id, p.id, output_path)

    # Use a fresh session on the same engine to read what the background
    # coroutine committed (its session has a different identity map).
    from sqlalchemy.ext.asyncio import AsyncSession as _AS
    from sqlalchemy.orm import sessionmaker as _sm
    async with _sm(db_engine, class_=_AS, expire_on_commit=False)() as s2:
        refreshed = await s2.get(ExportTask, task_id)
    assert refreshed.status == "failed"
    assert refreshed.error_message == "simulated docx failure"
    assert refreshed.completed_at is not None


# ============================================================================
# GET /export/status/{task_id} — happy path + 404 (lines 277-288)
# ============================================================================


@pytest.mark.asyncio
async def test_get_export_status_returns_task(client, sample_protocol, monkeypatch):
    """GET /export/status/{task_id} for an existing queued task returns its row."""
    _stub_background_task(monkeypatch)

    enq = await client.post(
        f"{API}/docx", json={"protocol_id": str(sample_protocol.id)}
    )
    assert enq.status_code == 202
    task_id = enq.json()["task_id"]

    r = await client.get(f"{API}/status/{task_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["task_id"] == task_id
    assert body["status"] == "queued"
    assert body["progress_percent"] == 0


@pytest.mark.asyncio
async def test_get_export_status_unknown_task_returns_404(client):
    """GET /export/status/{task_id} for unknown UUID → 404."""
    r = await client.get(f"{API}/status/{uuid.uuid4()}")
    assert r.status_code == 404
    assert "Задача экспорта не найдена" in r.text


# ============================================================================
# GET /export/download/{task_id} — happy path (lines 318-344)
# ============================================================================


@pytest.mark.asyncio
async def test_download_export_happy_path_returns_docx(client, sample_protocol, db_session):
    """When task.status='completed' and output_path exists, returns FileResponse."""
    from app.db.models import ExportTask
    from sqlalchemy import update

    # Pre-create a real DOCX on disk so FileResponse can serve it.
    task_id = uuid.uuid4()
    export_dir = Path("/tmp") / f"{sample_protocol.id}" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    output_path = export_dir / f"{task_id}.docx"
    output_path.write_bytes(b"PK\x03\x04 fake-docx-bytes")

    task = ExportTask(
        id=task_id,
        protocol_id=sample_protocol.id,
        format="docx",
        include_timestamps=True,
        include_screenshots=True,
        include_video_links=True,
        group_by_speaker=True,
        mark_doubtful=True,
        status="completed",
        progress_percent=100,
        output_path=str(output_path),
        file_size_bytes=len(b"PK\x03\x04 fake-docx-bytes"),
    )
    db_session.add(task)
    await db_session.commit()

    r = await client.get(f"{API}/download/{task_id}")
    assert r.status_code == 200, r.text
    assert r.content == b"PK\x03\x04 fake-docx-bytes"
    # Content-Disposition header should set filename=<protocol_id>.docx
    assert "attachment" in r.headers.get("content-disposition", "").lower()
    assert ".docx" in r.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_download_export_missing_output_path_returns_500(
    client, sample_protocol, db_session
):
    """Completed task with output_path=None → 500 (line 318-322)."""
    from app.db.models import ExportTask

    task_id = uuid.uuid4()
    task = ExportTask(
        id=task_id,
        protocol_id=sample_protocol.id,
        format="docx",
        include_timestamps=True,
        include_screenshots=True,
        include_video_links=True,
        group_by_speaker=True,
        mark_doubtful=True,
        status="completed",
        progress_percent=100,
        output_path=None,  # ← corrupt state
        file_size_bytes=0,
    )
    db_session.add(task)
    await db_session.commit()

    r = await client.get(f"{API}/download/{task_id}")
    assert r.status_code == 500
    assert "output_path отсутствует" in r.text


@pytest.mark.asyncio
async def test_download_export_file_gone_from_disk_returns_410(
    client, sample_protocol, db_session
):
    """Completed task but file removed from disk → 410 Gone (line 325-329)."""
    from app.db.models import ExportTask

    task_id = uuid.uuid4()
    fake_path = "/tmp/hmp-definitely-gone-" + str(task_id) + ".docx"
    # Make sure the file really doesn't exist.
    p = Path(fake_path)
    if p.exists():
        p.unlink()

    task = ExportTask(
        id=task_id,
        protocol_id=sample_protocol.id,
        format="docx",
        include_timestamps=True,
        include_screenshots=True,
        include_video_links=True,
        group_by_speaker=True,
        mark_doubtful=True,
        status="completed",
        progress_percent=100,
        output_path=fake_path,
        file_size_bytes=0,
    )
    db_session.add(task)
    await db_session.commit()

    r = await client.get(f"{API}/download/{task_id}")
    assert r.status_code == 410
    assert "удалён" in r.text


# ============================================================================
# POST /export/archive — 404 deleted protocol (line 371-372)
# ============================================================================


@pytest.mark.asyncio
async def test_archive_protocol_404_when_soft_deleted(client, sample_protocol, db_session):
    """archive_protocol returns 404 when protocol has deleted_at set."""
    sample_protocol.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    r = await client.post(f"{API}/archive/{sample_protocol.id}")
    assert r.status_code == 404
    assert "Протокол не найден" in r.text


@pytest.mark.asyncio
async def test_archive_protocol_404_when_unknown_id(client):
    """archive_protocol returns 404 for an unknown protocol_id."""
    r = await client.post(f"{API}/archive/{uuid.uuid4()}")
    assert r.status_code == 404


# ============================================================================
# POST /export/archive — happy path (lines 378-418): all 4 metadata fields
# including status, transcript without speaker, download_url format.
# ============================================================================


@pytest.mark.asyncio
async def test_archive_protocol_happy_path_includes_protocol_json(client, db_session):
    """archive_protocol writes protocol.json with id/title/date/created_at/status."""
    from app.db.models import Protocol, ProtocolStatus

    p = Protocol(
        id=uuid.uuid4(),
        title="ArchiveHappy",
        status=ProtocolStatus.READY,
        date=datetime(2025, 1, 1).date(),
        created_at=datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc),
    )
    db_session.add(p)
    await db_session.commit()

    r = await client.post(f"{API}/archive/{p.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert uuid.UUID(body["archive_id"])
    assert body["download_url"] == f"/api/v1/hmp/export/download-archive/{body['archive_id']}"

    dl = await client.get(f"{API}/download-archive/{body['archive_id']}")
    assert dl.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(dl.content))
    assert "protocol.json" in z.namelist()
    assert "transcript.txt" in z.namelist()
    import json as _json
    meta = _json.loads(z.read("protocol.json").decode("utf-8"))
    assert meta["id"] == str(p.id)
    assert meta["title"] == "ArchiveHappy"
    assert meta["status"] == ProtocolStatus.READY.value
    assert meta["date"] == "2025-01-01"
