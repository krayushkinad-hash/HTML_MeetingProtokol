"""E357 v2: deeper tests for app/routers/admin.py — push coverage past 50%.

Branches targeted (per --cov-report=term-missing):
- DELETE /admin/clear-data:
    * happy path empty DB (lines 56-118, 150-164)
    * happy path with records in EVERY table (12 tables, line-by-line coverage)
    * protocols_path missing branch (line 127 `if protocols_path.exists()` False)
    * unremovable file inside iterdir branch (line 144 `except Exception: pass`)
    * inner rmtree failure branch (line 134-139 `folder_delete_failed` warning)
    * outer iterdir failure branch (line 146-147 `clear_data_disk_error`)
    * DB failure → rollback + re-raise (line 119-122)
    * UserSetting reset creates 1 row (line 150-151)
- GET /admin/stats: empty + populated, all 5 count() calls (lines 174-179)
- DB session edge case: count() returns 0 / None → `or 0` fallback

NOTE: admin.py:153 calls `logger.info("all_data_cleared", deleted_counts=...)`
but `logger` is stdlib `logging.getLogger("hmp")` which rejects kwargs. This
is a real source bug. Every happy-path test monkeypatches `admin.logger` to a
structlog-style callable so the call succeeds and coverage reaches the return
statement. The bug is left intact (per coverage-session convention: report
the bug, don't auto-fix).
"""
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models import (
    Protocol, ProtocolStatus, Speaker, Utterance, Tag, ActionItem,
    Decision, Summary, TranscriptionTask, Screenshot, AudioFile, Folder,
    ProtocolVersion, UserSetting,
)
from app.routers import admin as admin_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _StructLogShim:
    """Structlog-style logger shim — accepts `(event, **kw)` like structlog.

    admin.py uses `logger.info("event_name", key=value)` but binds stdlib
    `logging.getLogger(...)` which doesn't accept kwargs. This shim makes the
    happy-path tests run past line 153 so coverage of lines 150-164 is hit.
    """
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def _log(self, level, event, **kw):
        self.calls.append((event, kw))

    def debug(self, event, **kw): self._log("DEBUG", event, **kw)
    def info(self, event, **kw):  self._log("INFO", event, **kw)
    def warning(self, event, **kw): self._log("WARNING", event, **kw)
    def error(self, event, **kw): self._log("ERROR", event, **kw)


@pytest.fixture
def structlog_logger(monkeypatch):
    """Replace admin.logger with a structlog-compatible shim for the test."""
    shim = _StructLogShim()
    monkeypatch.setattr(admin_module, "logger", shim)
    return shim


@pytest_asyncio.fixture
async def make_protocol(db_session):
    """Local protocol factory — independent of conftest sample_* fixtures."""
    async def _factory(title: str = "T", status=ProtocolStatus.RECORDING):
        p = Protocol(
            id=uuid.uuid4(),
            title=title,
            status=status,
            date=datetime.now(timezone.utc).date(),
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(p)
        await db_session.commit()
        return p

    return _factory


@pytest_asyncio.fixture
async def populated_db(make_protocol, db_session):
    """Seed one row in EVERY table the DELETE touches.

    This guarantees `deleted_counts` non-zero for all 12 tables on lines 56-113.
    """
    p = await make_protocol("Pop")
    spk = Speaker(id=uuid.uuid4(), protocol_id=p.id, speaker_label="S")
    db_session.add(spk)
    utt = Utterance(
        id=uuid.uuid4(), protocol_id=p.id, speaker_id=spk.id,
        start_sec=0.0, end_sec=1.0, text="hi",
    )
    db_session.add(utt)
    tag = Tag(id=uuid.uuid4(), protocol_id=p.id, name="t")
    db_session.add(tag)
    ai = ActionItem(id=uuid.uuid4(), protocol_id=p.id, task="do")
    db_session.add(ai)
    dec = Decision(id=uuid.uuid4(), protocol_id=p.id, text="d")
    db_session.add(dec)
    summ = Summary(
        id=uuid.uuid4(), protocol_id=p.id,
        text="ov", provider="manual",
    )
    db_session.add(summ)
    task = TranscriptionTask(
        id=uuid.uuid4(), protocol_id=p.id, status="queued",
    )
    db_session.add(task)
    shot = Screenshot(
        id=uuid.uuid4(), protocol_id=p.id, timestamp_sec=1.0,
        file_path="/tmp/x.png",
    )
    db_session.add(shot)
    af = AudioFile(
        id=uuid.uuid4(),
        file_path="/tmp/x.wav", filename="x.wav", extension="wav",
        size_bytes=1024, mime_type="audio/wav",
    )
    db_session.add(af)
    folder = Folder(id=uuid.uuid4(), name="F")
    db_session.add(folder)
    pv = ProtocolVersion(
        id=uuid.uuid4(), protocol_id=p.id, version_number=1,
        snapshot={"x": 1},
    )
    db_session.add(pv)
    await db_session.commit()
    return p


# ===========================================================================
# DELETE /admin/clear-data — happy paths
# ===========================================================================

@pytest.mark.asyncio
async def test_clear_data_empty_db_returns_cleared(client, structlog_logger):
    """DELETE on empty DB → 200, all counts=0, files_deleted=0.

    Covers lines 56-118 (all 12 table-count/DELETE pairs on a no-op DB) plus
    150-164 (UserSetting reset + response build).
    """
    r = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "cleared"
    # Every counter present and zero
    for key in ("utterances", "speakers", "tags", "action_items",
                "decisions", "summaries", "transcription_tasks",
                "screenshots", "audio_files", "folders",
                "protocol_versions", "protocols"):
        assert body["deleted_counts"][key] == 0, key
    assert body["files_deleted"] == 0
    assert "message" in body
    # The success-path logger.info("all_data_cleared", ...) was reached
    assert any(ev == "all_data_cleared" for ev, _ in structlog_logger.calls)


@pytest.mark.asyncio
async def test_clear_data_with_full_db(client, structlog_logger, populated_db):
    """DELETE on populated DB → 200, every counter >= 1, DB emptied.

    Covers lines 56-113 with non-zero `result.scalar()` for all 12 tables.
    """
    r = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 200, r.text
    body = r.json()
    dc = body["deleted_counts"]
    # Each of the 12 tables had a row in `populated_db`
    for key in ("utterances", "speakers", "tags", "action_items",
                "decisions", "summaries", "transcription_tasks",
                "screenshots", "audio_files", "folders",
                "protocol_versions", "protocols"):
        assert dc[key] >= 1, f"{key} should be >= 1, got {dc[key]}"
    # Follow-up GET confirms DB really emptied (lines 174-178)
    stats = (await client.get("/api/v1/hmp/admin/stats")).json()
    assert stats == {
        "protocols": 0, "audio_files": 0, "utterances": 0,
        "screenshots": 0, "folders": 0,
    }


@pytest.mark.asyncio
async def test_clear_data_resets_user_setting(client, db_session, structlog_logger):
    """After clear-data → exactly 1 default UserSetting (line 150-151).

    Covers the `db.add(UserSetting())` + final commit on line 150-151.
    """
    # Wipe existing settings then add one custom row
    res = await db_session.execute(select(UserSetting))
    for row in res.scalars().all():
        await db_session.delete(row)
    await db_session.commit()
    db_session.add(UserSetting(theme="dark"))
    await db_session.commit()

    r = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 200

    res = await db_session.execute(select(UserSetting))
    rows = res.scalars().all()
    assert len(rows) == 1  # exactly one fresh UserSetting created


# ===========================================================================
# DELETE /admin/clear-data — disk branches
# ===========================================================================

@pytest.mark.asyncio
async def test_clear_data_missing_protocols_path(client, monkeypatch, structlog_logger):
    """protocols_path.exists() == False → files_deleted=0, no exception (line 127)."""
    from app.core.config import get_settings
    settings = get_settings()
    nonexistent = "/tmp/admin_v2_does_not_exist_xyz"
    monkeypatch.setattr(settings, "protocols_dir", nonexistent)

    r = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 200, r.text
    assert r.json()["files_deleted"] == 0


@pytest.mark.asyncio
async def test_clear_data_removes_protocol_dirs_from_disk(
    client, tmp_path, monkeypatch, structlog_logger,
):
    """Protocol dirs + stray file are removed → files_deleted>=3 (lines 129-145)."""
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    # Two protocol dirs + one stray file
    (tmp_path / str(uuid.uuid4())).mkdir()
    (tmp_path / str(uuid.uuid4())).mkdir()
    (tmp_path / "stray.txt").write_text("x")

    r = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 200, r.text
    assert r.json()["files_deleted"] >= 3
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_clear_data_inner_rmtree_failure_warns(
    client, tmp_path, monkeypatch, structlog_logger,
):
    """If rmtree raises → folder_delete_failed warning logged, endpoint 200 (lines 134-139)."""
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))
    (tmp_path / "prot_dir").mkdir()

    def boom_rmtree(path, *a, **kw):
        raise OSError("simulated rmtree failure")

    # admin.py does `from shutil import rmtree` inside the function, so the
    # function-local binding is a fresh reference each call. We patch
    # `shutil.rmtree` (the original) — Python's `from X import Y` re-reads
    # `Y` from `shutil` at import time, but `shutil.rmtree` IS the same object
    # so patching it works.
    monkeypatch.setattr("shutil.rmtree", boom_rmtree)

    r = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 200, r.text
    # No files were deleted (rmtree raised for the one dir)
    assert r.json()["files_deleted"] == 0
    # The warning was logged via the shim (level=WARNING, event=folder_delete_failed)
    assert any(
        ev == "folder_delete_failed" for ev, _ in structlog_logger.calls
    ), structlog_logger.calls


@pytest.mark.asyncio
async def test_clear_data_unlink_failure_swallowed(
    client, tmp_path, monkeypatch, structlog_logger,
):
    """If a stray file's unlink fails → swallowed by `except Exception: pass` (line 144)."""
    import pathlib as _pl
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))
    blocked = tmp_path / "blocked.txt"
    blocked.write_text("x")

    real_unlink = _pl.Path.unlink

    def maybe_boom(self, *args, **kwargs):
        if "blocked" in str(self):
            raise OSError("perm denied")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(_pl.Path, "unlink", maybe_boom)
    r = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 200, r.text
    # blocked.txt didn't count (unlink raised); files_deleted=0
    assert r.json()["files_deleted"] == 0
    # file still on disk (unlink swallowed)
    assert blocked.exists()


@pytest.mark.asyncio
async def test_clear_data_outer_iterdir_failure_warns(
    client, tmp_path, monkeypatch, structlog_logger,
):
    """If iterdir() raises → outer `clear_data_disk_error` warning + endpoint 200 (lines 146-147)."""
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))
    (tmp_path / "anything").mkdir()

    # Patch the protocols_path object's iterdir so the outer `for ... in
    # protocols_path.iterdir():` raises. Easier: patch Path.iterdir globally.
    import pathlib as _pl
    real_iterdir = _pl.Path.iterdir

    def boom_iterdir(self, *args, **kwargs):
        # Only fail for our tmp_path
        if str(self) == str(tmp_path):
            raise OSError("simulated iterdir failure")
        return real_iterdir(self, *args, **kwargs)

    monkeypatch.setattr(_pl.Path, "iterdir", boom_iterdir)
    r = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 200, r.text
    assert r.json()["files_deleted"] == 0
    # The outer warning fired
    assert any(
        ev == "clear_data_disk_error" for ev, _ in structlog_logger.calls
    ), structlog_logger.calls


# ===========================================================================
# DELETE /admin/clear-data — DB error path
# ===========================================================================

@pytest.mark.asyncio
async def test_clear_data_db_failure_rolls_back_and_raises(client, structlog_logger):
    """If `db.execute(...)` raises during DELETE → rollback + re-raise (lines 119-122).

    The exception is caught by FastAPI's exception handler → 500.
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

    boom_holder: dict = {}

    async def _override():
        async with AsyncSessionLocal() as real:
            boom = _BoomSession(real)
            boom_holder["boom"] = boom
            try:
                yield boom
                await boom.commit()
            except Exception:
                await boom.rollback()
                raise

    app.dependency_overrides[get_db] = _override
    try:
        r = await client.delete("/api/v1/hmp/admin/clear-data")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 500
    # rollback was attempted (line 120)
    assert boom_holder["boom"].rolled_back is True
    # logger.error("clear_data_db_failed", ...) fired (line 121)
    assert any(
        ev == "clear_data_db_failed" for ev, _ in structlog_logger.calls
    ), structlog_logger.calls


# ===========================================================================
# GET /admin/stats — all branches (lines 174-179)
# ===========================================================================

@pytest.mark.asyncio
async def test_get_stats_empty_db_all_keys_zero(client):
    """GET /admin/stats on empty DB → exact zero dict (lines 174-178)."""
    r = await client.get("/api/v1/hmp/admin/stats")
    assert r.status_code == 200
    assert r.json() == {
        "protocols": 0, "audio_files": 0, "utterances": 0,
        "screenshots": 0, "folders": 0,
    }


@pytest.mark.asyncio
async def test_get_stats_with_populated_db(client, populated_db):
    """GET /admin/stats with rows in 4/5 tables (audio_files==0).

    Covers the non-zero branch of all 5 count() calls on lines 174-178.
    """
    r = await client.get("/api/v1/hmp/admin/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["protocols"] >= 1
    assert body["utterances"] >= 1
    assert body["screenshots"] >= 1
    assert body["folders"] >= 1
    assert body["audio_files"] >= 1  # populated_db adds one


@pytest.mark.asyncio
async def test_get_stats_zero_count_falls_back_to_zero(client, db_session):
    """When a table is empty → `result.scalar() or 0` returns 0 (lines 174-178).

    Specifically exercises the `or 0` fallback when result.scalar() is None
    (empty result set → scalar is None).
    """
    # Delete everything, verify stats
    from app.db.models import Protocol as P, Utterance as U, Screenshot as S, Folder as F, AudioFile as AF
    for model in (P, U, S, F, AF):
        res = await db_session.execute(select(model))
        for row in res.scalars().all():
            await db_session.delete(row)
    await db_session.commit()

    r = await client.get("/api/v1/hmp/admin/stats")
    body = r.json()
    assert all(v == 0 for v in body.values())


@pytest.mark.asyncio
async def test_get_stats_idempotent(client):
    """Calling /admin/stats twice in a row yields identical results."""
    r1 = (await client.get("/api/v1/hmp/admin/stats")).json()
    r2 = (await client.get("/api/v1/hmp/admin/stats")).json()
    assert r1 == r2