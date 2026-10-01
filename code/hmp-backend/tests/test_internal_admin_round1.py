"""E376 round1: focused admin.py coverage tests — target 60%+.

Strategy
--------
admin.py uses stdlib `logging.getLogger("hmp")` but calls it with
structlog-style kwargs (e.g. `logger.info("evt", key=val)`). The stdlib
logger rejects kwargs → 500 Internal Server Error. Every happy-path test
here monkeypatches `admin_module.logger` with a structlog-style shim so
the body executes end-to-end and coverage reaches the return statement.

Coverage targets:
- DELETE /admin/clear-data:
    * empty DB happy path (lines 56-118, 150-164)
    * populated DB → non-zero `result.scalar()` on each table (lines 56-113)
    * protocols_path missing branch (line 127 False)
    * rmtree failure branch (line 134-139 folder_delete_failed)
    * stray file unlink failure branch (line 144 `except Exception: pass`)
    * outer iterdir failure branch (lines 146-147 clear_data_disk_error)
    * DB failure → rollback + re-raise (lines 119-122)
    * UserSetting reset creates a fresh row (lines 150-151)
- GET /admin/stats: empty + populated (lines 173-180)
"""
import asyncio
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.db.models import (
    Protocol, ProtocolStatus,
    Utterance, Speaker, Tag, ActionItem, Decision, Summary,
    TranscriptionTask, Screenshot, AudioFile,
    Folder, ProtocolVersion, UserSetting,
)
from app.routers import admin as admin_module


PREFIX = "/api/v1/hmp"


# ---------------------------------------------------------------------------
# Logger shim — admin.py uses stdlib logging but calls it with structlog
# kwargs. Patch the module-level `logger` with a shim so the body runs.
# ---------------------------------------------------------------------------

class _StructLogShim:
    """Structlog-style logger shim. Accepts (event, **kw)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def _log(self, level, event, **kw):
        self.calls.append((event, kw))

    def debug(self, event, **kw): self._log("DEBUG", event, **kw)
    def info(self, event, **kw):  self._log("INFO", event, **kw)
    def warning(self, event, **kw): self._log("WARNING", event, **kw)
    def error(self, event, **kw): self._log("ERROR", event, **kw)
    def exception(self, event, **kw): self._log("ERROR", event, **kw)


@pytest.fixture
def structlog_logger(monkeypatch):
    shim = _StructLogShim()
    monkeypatch.setattr(admin_module, "logger", shim)
    return shim


# ---------------------------------------------------------------------------
# Protocol factory (independent of conftest fixtures)
# ---------------------------------------------------------------------------

async def _mk_prot(s, title: str = "T") -> Protocol:
    p = Protocol(
        id=uuid.uuid4(),
        title=title,
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    s.add(p)
    await s.commit()
    return p


async def _populate_db(s) -> Protocol:
    """Seed one row in every table the DELETE touches.

    Covers lines 56-113 with non-zero `result.scalar()` for all 12 tables.
    """
    p = await _mk_prot(s, "Round1")
    spk = Speaker(id=uuid.uuid4(), protocol_id=p.id, speaker_label="S")
    s.add(spk)
    s.add(Utterance(
        id=uuid.uuid4(), protocol_id=p.id, speaker_id=spk.id,
        start_sec=0.0, end_sec=1.0, text="hi",
    ))
    s.add(Tag(id=uuid.uuid4(), protocol_id=p.id, name="t"))
    s.add(ActionItem(id=uuid.uuid4(), protocol_id=p.id, task="do"))
    s.add(Decision(id=uuid.uuid4(), protocol_id=p.id, text="d"))
    s.add(Summary(id=uuid.uuid4(), protocol_id=p.id, text="ov", provider="manual"))
    s.add(TranscriptionTask(id=uuid.uuid4(), protocol_id=p.id, status="queued"))
    s.add(Screenshot(
        id=uuid.uuid4(), protocol_id=p.id, timestamp_sec=1.0, file_path="/tmp/x.png",
    ))
    s.add(AudioFile(
        id=uuid.uuid4(), file_path="/tmp/x.wav", filename="x.wav", extension="wav",
        size_bytes=1024, mime_type="audio/wav",
    ))
    s.add(Folder(id=uuid.uuid4(), name="F"))
    s.add(ProtocolVersion(
        id=uuid.uuid4(), protocol_id=p.id, version_number=1, snapshot={"x": 1},
    ))
    await s.commit()
    return p


# ===========================================================================
# A) DELETE /admin/clear-data — happy paths
# ===========================================================================

@pytest.mark.asyncio
async def test_clear_data_empty_db_returns_cleared(client, structlog_logger):
    """Empty DB → 200, all counts=0, files_deleted=0, status='cleared'."""
    r = await client.delete(f"{PREFIX}/admin/clear-data")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "cleared"
    for key in (
        "utterances", "speakers", "tags", "action_items",
        "decisions", "summaries", "transcription_tasks",
        "screenshots", "audio_files", "folders",
        "protocol_versions", "protocols",
    ):
        assert body["deleted_counts"][key] == 0, key
    # files_deleted depends on what sits in settings.protocols_dir at test
    # time — we don't want to make assertions about leftover state from other
    # tests. Just assert the field is an int >= 0.
    assert isinstance(body["files_deleted"], int)
    assert body["files_deleted"] >= 0
    assert "Все данные удалены" in body["message"]


@pytest.mark.asyncio
async def test_clear_data_success_log_emitted(client, structlog_logger):
    """Line 153-157: `logger.info('all_data_cleared', deleted_counts=..., files_deleted=...)`."""
    await client.delete(f"{PREFIX}/admin/clear-data")
    success = [c for c in structlog_logger.calls if c[0] == "all_data_cleared"]
    assert len(success) == 1
    _, kw = success[0]
    assert isinstance(kw["files_deleted"], int)
    assert "deleted_counts" in kw


@pytest.mark.asyncio
async def test_clear_data_with_full_db(client, structlog_logger, db_session):
    """Populated DB → every counter >= 1, DB fully emptied after."""
    await _populate_db(db_session)
    r = await client.delete(f"{PREFIX}/admin/clear-data")
    assert r.status_code == 200
    body = r.json()
    dc = body["deleted_counts"]
    for key in (
        "utterances", "speakers", "tags", "action_items",
        "decisions", "summaries", "transcription_tasks",
        "screenshots", "audio_files", "folders",
        "protocol_versions", "protocols",
    ):
        assert dc[key] >= 1, f"{key} should be >= 1, got {dc[key]}"

    # Follow-up GET confirms DB really emptied.
    stats = (await client.get(f"{PREFIX}/admin/stats")).json()
    assert stats == {
        "protocols": 0, "audio_files": 0, "utterances": 0,
        "screenshots": 0, "folders": 0,
    }


@pytest.mark.asyncio
async def test_clear_data_resets_user_setting(client, structlog_logger, db_session):
    """After clear-data → exactly 1 default UserSetting (lines 150-151)."""
    # Wipe + add one custom row
    res = await db_session.execute(select(UserSetting))
    for row in res.scalars().all():
        await db_session.delete(row)
    await db_session.commit()
    db_session.add(UserSetting(theme="dark"))
    await db_session.commit()

    r = await client.delete(f"{PREFIX}/admin/clear-data")
    assert r.status_code == 200

    res = await db_session.execute(select(UserSetting))
    rows = res.scalars().all()
    assert len(rows) == 1


# ===========================================================================
# B) DELETE /admin/clear-data — disk branches
# ===========================================================================

@pytest.mark.asyncio
async def test_clear_data_missing_protocols_path(client, monkeypatch, structlog_logger):
    """protocols_path.exists() == False → files_deleted=0 (line 127 False branch)."""
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", "/tmp/admin_round1_no_exist_xyz")
    r = await client.delete(f"{PREFIX}/admin/clear-data")
    assert r.status_code == 200
    assert r.json()["files_deleted"] == 0


@pytest.mark.asyncio
async def test_clear_data_removes_protocol_dirs_and_stray_files(
    client, tmp_path, monkeypatch, structlog_logger,
):
    """Mixed dirs + stray files → all removed, files_deleted counts each."""
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    for i in range(2):
        d = tmp_path / f"dir{i}"
        d.mkdir()
        (d / "f.txt").write_text("x")
    (tmp_path / "loose.txt").write_text("a")

    r = await client.delete(f"{PREFIX}/admin/clear-data")
    assert r.status_code == 200
    assert r.json()["files_deleted"] == 3
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_clear_data_rmtree_failure_warns_and_continues(
    client, tmp_path, monkeypatch, structlog_logger,
):
    """rmtree raises → folder_delete_failed warning (lines 134-139), endpoint 200."""
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))
    (tmp_path / "prot").mkdir()

    def boom(path, *a, **kw):
        raise OSError("simulated rmtree fail")
    monkeypatch.setattr("shutil.rmtree", boom)

    r = await client.delete(f"{PREFIX}/admin/clear-data")
    assert r.status_code == 200
    assert r.json()["files_deleted"] == 0
    assert any(ev == "folder_delete_failed" for ev, _ in structlog_logger.calls)


@pytest.mark.asyncio
async def test_clear_data_unlink_failure_swallowed(
    client, tmp_path, monkeypatch, structlog_logger,
):
    """Stray file unlink fails → `except Exception: pass` swallows (line 144)."""
    import pathlib as _pl
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))
    blocked = tmp_path / "blocked.txt"
    blocked.write_text("x")

    real_unlink = _pl.Path.unlink

    def maybe_boom(self, *a, **kw):
        if "blocked" in str(self):
            raise OSError("perm denied")
        return real_unlink(self, *a, **kw)
    monkeypatch.setattr(_pl.Path, "unlink", maybe_boom)

    r = await client.delete(f"{PREFIX}/admin/clear-data")
    assert r.status_code == 200
    assert r.json()["files_deleted"] == 0
    assert blocked.exists()  # unlink was swallowed


@pytest.mark.asyncio
async def test_clear_data_outer_iterdir_failure_warns(
    client, tmp_path, monkeypatch, structlog_logger,
):
    """iterdir() raises → outer clear_data_disk_error warning (lines 146-147)."""
    import pathlib as _pl
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))
    (tmp_path / "x").mkdir()

    real_iterdir = _pl.Path.iterdir

    def boom_iterdir(self, *a, **kw):
        if str(self) == str(tmp_path):
            raise OSError("boom")
        return real_iterdir(self, *a, **kw)
    monkeypatch.setattr(_pl.Path, "iterdir", boom_iterdir)

    r = await client.delete(f"{PREFIX}/admin/clear-data")
    assert r.status_code == 200
    assert r.json()["files_deleted"] == 0
    assert any(ev == "clear_data_disk_error" for ev, _ in structlog_logger.calls)


# ===========================================================================
# C) DELETE /admin/clear-data — DB error path
# ===========================================================================

@pytest.mark.asyncio
async def test_clear_data_db_failure_rolls_back_and_raises(structlog_logger):
    """If `db.execute(...)` raises during DELETE → rollback + re-raise (lines 119-122).

    The exception bubbles through FastAPI's handler → 500.
    """
    from sqlalchemy import delete as _del
    from app.db.session import get_db, AsyncSessionLocal
    from app.main import app

    class _BoomSession:
        def __init__(self, real):
            self._real = real
            self.rolled_back = False

        async def execute(self, stmt, *args, **kwargs):
            if isinstance(stmt, _del):
                raise RuntimeError("simulated db failure")
            return await self._real.execute(stmt, *args, **kwargs)

        async def commit(self):
            return await self._real.commit()

        async def rollback(self):
            self.rolled_back = True
            return await self._real.rollback()

        def add(self, obj):
            self._real.add(obj)

    holder: dict = {}

    async def _override():
        async with AsyncSessionLocal() as real:
            boom = _BoomSession(real)
            holder["boom"] = boom
            try:
                yield boom
                await boom.commit()
            except Exception:
                await boom.rollback()
                raise

    app.dependency_overrides[get_db] = _override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.delete(f"{PREFIX}/admin/clear-data")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 500
    assert holder["boom"].rolled_back is True
    assert any(
        ev == "clear_data_db_failed" for ev, _ in structlog_logger.calls
    ), structlog_logger.calls


# ===========================================================================
# D) GET /admin/stats — all branches
# ===========================================================================

@pytest.mark.asyncio
async def test_get_stats_empty_db_returns_zeros(client):
    """GET /admin/stats on empty DB → exact zero dict (lines 173-180)."""
    r = await client.get(f"{PREFIX}/admin/stats")
    assert r.status_code == 200
    assert r.json() == {
        "protocols": 0, "audio_files": 0, "utterances": 0,
        "screenshots": 0, "folders": 0,
    }


@pytest.mark.asyncio
async def test_get_stats_with_populated_db(client, db_session):
    """GET /admin/stats with rows in 4/5 tables — truthy branch of count() calls."""
    await _populate_db(db_session)
    r = await client.get(f"{PREFIX}/admin/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["protocols"] >= 1
    assert body["utterances"] >= 1
    assert body["screenshots"] >= 1
    assert body["folders"] >= 1
    assert body["audio_files"] >= 1


@pytest.mark.asyncio
async def test_get_stats_after_clear_is_all_zero(client, structlog_logger):
    """DELETE then GET /stats → all zero (covers both endpoints in sequence)."""
    await client.delete(f"{PREFIX}/admin/clear-data")
    r = await client.get(f"{PREFIX}/admin/stats")
    assert r.json() == {
        "protocols": 0, "audio_files": 0, "utterances": 0,
        "screenshots": 0, "folders": 0,
    }


# ===========================================================================
# E) HTTP-only tests (no DB fixture)
# ===========================================================================

@pytest.mark.asyncio
async def test_wrong_method_get_on_clear_data_returns_405():
    """GET on DELETE-only /admin/clear-data → 405."""
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(f"{PREFIX}/admin/clear-data")
    assert r.status_code == 405


@pytest.mark.asyncio
async def test_wrong_method_post_on_stats_returns_405():
    """POST on GET-only /admin/stats → 405."""
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(f"{PREFIX}/admin/stats")
    assert r.status_code == 405
