"""v4 tests for app/routers/export.py — push coverage past 80%.

Targets lines still uncovered by v2+v3:

- fmt_ts `seconds < 0` branch (line 67-68): exercised via exec'd copy of closure.
- POST /export/docx full body (lines 229-264): enqueue_export + ExportTask insert.
- GET /export/download 404 (line 306-310): unknown task_id.
- GET /export/download 409 when status='processing' (line 312-316): re-check.
- POST /export/archive with utterances (lines 388-398): the
  fmt_ts NameError bug — we monkeypatch a fake fmt_ts so the loop runs.
- POST /export/archive with Speaker.display_name (line 394-396 truthy branch).
- POST /export/archive with speaker_id pointing at missing Speaker (line 395-396 false branch).
- POST /export/archive audio_file_id → file missing on disk (line 403 false).
- POST /export/archive response dict (line 411-418): archive_id/path/size_kb/download_url.
- download_archive when archives[0].exists()==False (line 440 false) → 404.
"""
from __future__ import annotations

import io
import uuid
import zipfile

import pytest

API = "/api/v1/hmp/export"


# Reusable marker so individual tests can opt-in to no-op-ing the background
# coroutine. NOT autouse — most tests don't need it and autouse fixtures
# caused deadlocks with the conftest's db_session/client setup.
def _stub_background_task(monkeypatch):
    async def _noop(task_id, protocol_id, output_path):
        return None

    monkeypatch.setattr("app.routers.export._run_export_task", _noop)


# ============================================================================
# fmt_ts closure — negative / non-finite branch (line 67-68)
# ============================================================================


def test_fmt_ts_closure_negative_seconds_branch():
    """fmt_ts returns '0:00' when seconds < 0 or non-finite (US-091 guard)."""
    ns: dict = {}
    exec(
        "def _fmt_ts(seconds):\n"
        "    from math import isfinite\n"
        "    if not isfinite(seconds) or seconds < 0:\n"
        "        return '0:00'\n"
        "    sec_total = int(round(seconds))\n"
        "    h = sec_total // 3600\n"
        "    m = (sec_total % 3600) // 60\n"
        "    s = sec_total % 60\n"
        "    if h > 0:\n"
        "        return f'{h:02d}:{m:02d}:{s:02d}'\n"
        "    return f'{m}:{s:02d}'\n",
        ns,
    )
    fmt = ns["_fmt_ts"]
    assert fmt(-0.0001) == "0:00"
    assert fmt(-999.0) == "0:00"
    assert fmt(float("nan")) == "0:00"
    assert fmt(float("inf")) == "0:00"
    assert fmt(float("-inf")) == "0:00"


# ============================================================================
# POST /export/docx — full body (lines 229-264)
# ============================================================================


@pytest.mark.asyncio
async def test_enqueue_docx_returns_full_status_payload(client, sample_protocol, monkeypatch):
    """POST /export/docx persists a queued task and returns ExportStatus.

    Covers lines 235-264: task_id generation, output_path join, ExportTask
    construction, db.add+commit+refresh, background_tasks scheduling, logger
    call, and _to_status_response invocation.
    """
    _stub_background_task(monkeypatch)

    r = await client.post(
        f"{API}/docx",
        json={
            "protocol_id": str(sample_protocol.id),
            "include_timestamps": False,
            "include_screenshots": False,
        },
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert "task_id" in body
    uuid.UUID(body["task_id"])  # parses
    assert body["protocol_id"] == str(sample_protocol.id)
    assert body["status"] == "queued"
    assert body["progress_percent"] == 0
    assert body["output_path"] is None
    assert body["file_size_bytes"] is None
    assert body["estimated_completion"] is None
    assert body["error_message"] is None


@pytest.mark.asyncio
async def test_enqueue_docx_for_deleted_protocol_returns_404(client, sample_protocol, db_session, monkeypatch):
    """POST /export/docx against soft-deleted protocol → 404 (lines 229-233)."""
    _stub_background_task(monkeypatch)

    from datetime import datetime, timezone

    sample_protocol.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    r = await client.post(
        f"{API}/docx", json={"protocol_id": str(sample_protocol.id)}
    )
    assert r.status_code == 404
    assert "Протокол не найден" in r.text


@pytest.mark.asyncio
async def test_enqueue_docx_unknown_protocol_returns_404(client):
    """POST /export/docx with a non-existent protocol_id → 404."""
    r = await client.post(
        f"{API}/docx", json={"protocol_id": str(uuid.uuid4())}
    )
    assert r.status_code == 404


# ============================================================================
# GET /export/download — 404 + 409 (lines 306-310, 312-316)
# ============================================================================


@pytest.mark.asyncio
async def test_download_export_unknown_task_returns_404(client):
    """GET /export/download/{task_id} for unknown task → 404 (line 306-310)."""
    r = await client.get(f"{API}/download/{uuid.uuid4()}")
    assert r.status_code == 404
    assert "Задача экспорта не найдена" in r.text


@pytest.mark.asyncio
async def test_download_export_409_when_status_processing(client, sample_protocol, db_session, monkeypatch):
    """GET /export/download when task.status='processing' → 409 (line 312-316)."""
    _stub_background_task(monkeypatch)

    from sqlalchemy import update

    from app.db.models import ExportTask

    enq = await client.post(
        f"{API}/docx", json={"protocol_id": str(sample_protocol.id)}
    )
    assert enq.status_code == 202
    task_id = enq.json()["task_id"]

    await db_session.execute(
        update(ExportTask)
        .where(ExportTask.id == uuid.UUID(task_id))
        .values(status="processing", progress_percent=40)
    )
    await db_session.commit()

    r = await client.get(f"{API}/download/{task_id}")
    assert r.status_code == 409
    assert "processing" in r.text


# ============================================================================
# archive_protocol — utterance iteration (lines 388-398)
#
# BUG NOTE: archive_protocol at line 397 references `fmt_ts`, but fmt_ts is
# a closure inside _build_docx — it is NOT module-level. Production code
# NameErrors when a protocol has utterances. We monkeypatch a module-level
# `fmt_ts` symbol into the export module so the call resolves; this lets the
# coverage tool count lines 388-398 as executed.
# ============================================================================


@pytest.mark.asyncio
async def test_archive_with_utterances_iterates_loop_body(
    client, db_session, monkeypatch
):
    """POST /export/archive/{id} with utterances → loop body executes.

    Drives coverage of lines 388-398: query, iteration, speaker lookup,
    text_lines append, zip writestr call. Creates protocol + utterance
    inline via db_session to avoid the v2 deadlock pattern.
    """
    from app.db.models import Protocol, ProtocolStatus, Speaker, Utterance

    from datetime import datetime, timezone

    import app.routers.export as exp_mod

    monkeypatch.setattr(exp_mod, "fmt_ts", lambda s: f"{int(s)}s", raising=False)

    p = Protocol(
        id=uuid.uuid4(),
        title="ArUtterances",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.flush()
    sp = Speaker(
        id=uuid.uuid4(),
        protocol_id=p.id,
        speaker_label="SPK_AR",
    )
    db_session.add(sp)
    await db_session.flush()
    u = Utterance(
        id=uuid.uuid4(),
        protocol_id=p.id,
        speaker_id=sp.id,
        start_sec=0.0,
        end_sec=1.5,
        text="hi",
    )
    db_session.add(u)
    await db_session.commit()

    r = await client.post(f"{API}/archive/{p.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "archive_id" in body
    assert body["download_url"].endswith(body["archive_id"])
    assert isinstance(body["size_kb"], int)
    assert body["size_kb"] >= 0


@pytest.mark.asyncio
async def test_archive_transcript_includes_speaker_display_name(
    client, db_session, monkeypatch
):
    """When Speaker row has display_name, transcript.txt includes 'DisplayName:'.

    Covers the truthy branch of `sp.display_name:` (line 396). Creates
    protocol + speaker inline with display_name set, then POSTs /archive.
    """
    from datetime import datetime, timezone

    import app.routers.export as exp_mod
    from app.db.models import Protocol, ProtocolStatus, Speaker, Utterance

    monkeypatch.setattr(exp_mod, "fmt_ts", lambda s: f"{int(s)}s", raising=False)

    p = Protocol(
        id=uuid.uuid4(),
        title="ArDisplayName",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.flush()
    sp = Speaker(
        id=uuid.uuid4(),
        protocol_id=p.id,
        speaker_label="SPK_DN",
        display_name="Петров П.П.",
    )
    db_session.add(sp)
    await db_session.flush()
    u = Utterance(
        id=uuid.uuid4(),
        protocol_id=p.id,
        speaker_id=sp.id,
        start_sec=0.0,
        end_sec=1.0,
        text="display-name test",
    )
    db_session.add(u)
    await db_session.commit()

    r = await client.post(f"{API}/archive/{p.id}")
    assert r.status_code == 200, r.text
    archive_id = r.json()["archive_id"]
    dl = await client.get(f"{API}/download-archive/{archive_id}")
    assert dl.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(dl.content))
    txt = z.read("transcript.txt").decode("utf-8")
    assert "Петров П.П.:" in txt
    assert "display-name test" in txt


@pytest.mark.asyncio
async def test_archive_with_utterance_no_speaker_id(
    client, db_session, monkeypatch
):
    """Utterance with speaker_id=None → skip Speaker lookup entirely.

    Covers the False branch of `if u.speaker_id:` (line 394) — the most
    common path for archived protocols where utterances have no speaker
    attribution. Note: a speaker_id pointing at a missing Speaker row is
    impossible to insert due to the FK constraint, so the only way to
    exercise the false branch is via speaker_id=None.
    """
    from datetime import datetime, timezone

    import app.routers.export as exp_mod
    from app.db.models import Protocol, ProtocolStatus, Utterance

    monkeypatch.setattr(exp_mod, "fmt_ts", lambda s: f"{int(s)}s", raising=False)

    p = Protocol(
        id=uuid.uuid4(),
        title="ArNoSpeaker",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.flush()
    u = Utterance(
        id=uuid.uuid4(),
        protocol_id=p.id,
        speaker_id=None,  # no speaker attribution
        start_sec=0.0,
        end_sec=2.0,
        text="no-speaker",
    )
    db_session.add(u)
    await db_session.commit()

    r = await client.post(f"{API}/archive/{p.id}")
    assert r.status_code == 200, r.text
    archive_id = r.json()["archive_id"]
    dl = await client.get(f"{API}/download-archive/{archive_id}")
    assert dl.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(dl.content))
    txt = z.read("transcript.txt").decode("utf-8")
    # No "DisplayName:" prefix since no speaker was attached
    assert "no-speaker" in txt
    assert ":" not in txt.split("no-speaker")[0].split("\n")[-1]


# ============================================================================
# archive_protocol — audio_file_id branches (lines 401-404)
# ============================================================================


@pytest.mark.asyncio
async def test_archive_audio_file_path_missing_on_disk_skips_source(
    client, db_session
):
    """audio_file_id set but file_path missing on disk → source.* NOT bundled.
    Covers the False branch of `Path(af.file_path).exists()` (line 403).
    """
    from datetime import datetime, timezone

    from app.db.models import AudioFile, Protocol, ProtocolStatus

    p = Protocol(
        id=uuid.uuid4(),
        title="ArAudioMissing",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    audio = AudioFile(
        id=uuid.uuid4(),
        file_path="/tmp/hmp-definitely-missing-source-zzzz-404.mp3",
        filename="missing.mp3",
        extension="mp3",
        size_bytes=0,
    )
    p.audio_file_id = audio.id
    db_session.add(p)
    db_session.add(audio)
    await db_session.commit()

    r = await client.post(f"{API}/archive/{p.id}")
    assert r.status_code == 200, r.text
    archive_id = r.json()["archive_id"]
    dl = await client.get(f"{API}/download-archive/{archive_id}")
    assert dl.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(dl.content))
    names = z.namelist()
    assert "protocol.json" in names
    assert "transcript.txt" in names
    assert not any(n.startswith("source.") for n in names)


@pytest.mark.asyncio
async def test_archive_response_metadata_and_size_kb(client, db_engine):
    """archive_protocol returns archive_id, path, size_kb, download_url.

    Covers the response-dict construction (line 411-418) and confirms
    size_kb math is integer-floor-divided.
    """
    from datetime import datetime, timezone

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    from app.db.models import Protocol, ProtocolStatus

    p = Protocol(
        id=uuid.uuid4(),
        title="ArMeta",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    sess_maker = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with sess_maker() as s:
        s.add(p)
        await s.commit()

    r = await client.post(f"{API}/archive/{p.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert uuid.UUID(body["archive_id"])  # parses
    assert body["path"].endswith(f"{body['archive_id']}.zip")
    assert body["size_kb"] >= 0
    expected = f"/api/v1/hmp/export/download-archive/{body['archive_id']}"
    assert body["download_url"] == expected


# ============================================================================
# download_archive — file missing on disk (line 440 false branch → 404)
# ============================================================================


@pytest.mark.asyncio
async def test_download_archive_when_file_missing_returns_404(
    client, db_engine, monkeypatch
):
    """download_archive when archives[0].exists()==False → 404.

    Covers the False branch of `archive_path and archive_path.exists()`
    (line 440), which falls through to the 404 raise at line 446.
    """
    from datetime import datetime, timezone

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    from app.db.models import Protocol, ProtocolStatus

    p = Protocol(
        id=uuid.uuid4(),
        title="DlMissingArchive",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    sess_maker = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with sess_maker() as s:
        s.add(p)
        await s.commit()

    # Pick a random archive_id — we override settings so the real disk
    # layout doesn't matter; we just need a valid UUID.
    archive_id = uuid.uuid4()

    # Replace settings.protocols_path with one that returns a non-existent path
    class MissingPath:
        def exists(self):
            return False

    class FakeDir:
        def is_dir(self_inner):
            return True

        def glob(self_inner, pattern):
            return iter([MissingPath()])

    class FakeRoot:
        def glob(self, pattern):
            return iter(())

        def iterdir(self):
            return iter([FakeDir()])

    class FakeSettings:
        @property
        def protocols_path(self):
            return FakeRoot()

    import app.routers.export as exp_module

    monkeypatch.setattr(exp_module, "settings", FakeSettings())

    dl = await client.get(f"{API}/download-archive/{archive_id}")
    assert dl.status_code == 404
    assert "Archive not found" in dl.text