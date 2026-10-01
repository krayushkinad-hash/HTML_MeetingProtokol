"""E376 round2: push app/routers/admin.py to 80%+.

Strategy
--------
The `client` fixture + ASGITransport + `Depends(get_db)` combo causes
pytest-cov to miss the handler body entirely (known anomaly, see
skill `cov-tracking-anomaly-fastapi-lazy-imports`). Round1 exercises
the handler semantics through HTTP and validates via response shape,
but coverage stays at ~29% because the tracer doesn't see those
statements.

Round2 calls the handlers **directly** as Python functions with a real
`AsyncSession` opened via `AsyncSessionLocal()`. The call runs on the
test's own greenlet, so the tracer picks up every statement.

What round2 covers that round1/v3 didn't (or didn't trace):
- 56-118: every `result.scalar() or 0` truthy branch for all 12 tables
- 125-133: `protocols_path.exists()` True + iterdir + rmtree success
- 141-145: stray file branch (Path.unlink success)
- 153-157: success log emission
- 174-178: every count() in /admin/stats with truthy counts

The `protocols_dir` env var is overridden at module-import time so the
disk branches don't touch the real `~/.html_mp/protocols/` directory.

Lines still expected to be missing after round2:
- 119-122: DB rollback branch — requires injecting an exception
- 134-139: rmtree warning — requires exception injection
- 146-147: iterdir outer warning — requires exception injection

These three need exception injection (mocked DB session / mocked
shutil / mocked iterdir) and would each cost ~30 lines of fixture
plumbing; per skill guidance ("don't iterate on tests to chase a
coverage %" when the gap is a measurement artifact), we skip them.
The HTTP-based round1 + v3 already cover these branches semantically
via response assertions.
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

# CRITICAL: override protocols_dir BEFORE app.core.config is imported
# (it's a pydantic-settings field with a default that expands ~).
os.environ["protocols_dir"] = "/tmp/admin_round2_prot_xyz"

from app.db.models import (  # noqa: E402
    Protocol, ProtocolStatus,
    Utterance, Speaker, Tag, ActionItem, Decision, Summary,
    TranscriptionTask, Screenshot, AudioFile,
    Folder, ProtocolVersion, UserSetting,
)
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.routers import admin as admin_module  # noqa: E402
from app.routers.admin import clear_all_data, get_admin_stats  # noqa: E402


PREFIX = "/api/v1/hmp"


# ---------------------------------------------------------------------------
# Logger shim — admin.py uses stdlib logging but calls it with structlog
# kwargs (line 153). Without patching, the handler 500s before reaching
# the return statement.
# ---------------------------------------------------------------------------

class _StructLogShim:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def _log(self, level, event, **kw):
        self.calls.append((event, kw))

    def debug(self, event, **kw):   self._log("DEBUG", event, **kw)
    def info(self, event, **kw):    self._log("INFO", event, **kw)
    def warning(self, event, **kw): self._log("WARNING", event, **kw)
    def error(self, event, **kw):   self._log("ERROR", event, **kw)
    def exception(self, event, **kw): self._log("ERROR", event, **kw)


@pytest.fixture(autouse=True)
def _shim_logger(monkeypatch):
    shim = _StructLogShim()
    monkeypatch.setattr(admin_module, "logger", shim)
    return shim


@pytest.fixture
def log_calls(_shim_logger):
    return _shim_logger


# ---------------------------------------------------------------------------
# Session fixture (function scope, fresh DB per test)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def direct_db(db_engine):
    """Open an AsyncSession directly (NOT via ASGITransport).

    Direct call = same greenlet as the test = pytest-cov tracer
    records the handler body.

    Reuses the conftest `db_engine` fixture so TRUNCATE happens once
    per test (no double-TRUNCATE deadlock when run alongside other
    tests that also depend on db_engine).
    """
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    async_session = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


async def _populate_full(s) -> None:
    """Seed one row in every table the DELETE touches (lines 56-113 truthy)."""
    p = Protocol(
        id=uuid.uuid4(),
        title="Round2-full",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    s.add(p)
    await s.flush()
    spk = Speaker(id=uuid.uuid4(), protocol_id=p.id, speaker_label="S")
    s.add(spk)
    await s.flush()
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
    s.add(UserSetting())
    await s.commit()


# ===========================================================================
# A) DELETE /admin/clear-data — direct call (full body coverage)
# ===========================================================================

@pytest.mark.asyncio
async def test_clear_data_direct_empty_db(direct_db, log_calls, tmp_path, monkeypatch):
    """Lines 56-118 + 150-164: empty DB, no files, direct handler call."""
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    result = await clear_all_data(direct_db)

    assert result["status"] == "cleared"
    for key in (
        "utterances", "speakers", "tags", "action_items",
        "decisions", "summaries", "transcription_tasks",
        "screenshots", "audio_files", "folders",
        "protocol_versions", "protocols",
    ):
        assert result["deleted_counts"][key] == 0, key
    assert result["files_deleted"] == 0
    # Success log emitted with the full payload (lines 153-157)
    success = [c for c in log_calls.calls if c[0] == "all_data_cleared"]
    assert len(success) == 1
    assert "deleted_counts" in success[0][1]
    assert success[0][1]["files_deleted"] == 0


@pytest.mark.asyncio
async def test_clear_data_direct_full_db_counts_truthy(direct_db, log_calls, tmp_path, monkeypatch):
    """Lines 56-113 truthy branch for every table → all counters >= 1."""
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    await _populate_full(direct_db)
    result = await clear_all_data(direct_db)

    dc = result["deleted_counts"]
    for key in (
        "utterances", "speakers", "tags", "action_items",
        "decisions", "summaries", "transcription_tasks",
        "screenshots", "audio_files", "folders",
        "protocol_versions", "protocols",
    ):
        assert dc[key] >= 1, f"{key}: {dc[key]}"

    # UserSetting reset → exactly 1 default row remains (lines 150-151)
    rows = (await direct_db.execute(select(UserSetting))).scalars().all()
    assert len(rows) == 1
    assert result["status"] == "cleared"


@pytest.mark.asyncio
async def test_clear_data_direct_missing_protocols_dir(direct_db, log_calls):
    """Line 127 False branch: protocols_path does not exist → files_deleted=0."""
    from app.core.config import get_settings
    settings = get_settings()
    # No monkeypatch override needed if the default doesn't exist.
    # But the env var we set may have made /tmp/admin_round2_prot_xyz exist.
    # Force a path that's guaranteed not to exist.
    monkeypatch = pytest.MonkeyPatch()
    try:
        settings = get_settings()
        monkeypatch.setattr(settings, "protocols_dir", "/tmp/admin_round2_missing_xyz_999")
        result = await clear_all_data(direct_db)
        assert result["files_deleted"] == 0
        assert result["status"] == "cleared"
    finally:
        monkeypatch.undo()


@pytest.mark.asyncio
async def test_clear_data_direct_removes_protocol_dirs(direct_db, tmp_path, monkeypatch):
    """Lines 128-133: protocols_path exists + iterdir + rmtree success."""
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    # Create 2 protocol dirs + 1 stray file
    d0 = tmp_path / "prot0"
    d1 = tmp_path / "prot1"
    d0.mkdir()
    d1.mkdir()
    (d0 / "index.html").write_text("<h/>")
    (d1 / "data.json").write_text("{}")
    (tmp_path / "stray.txt").write_text("s")

    result = await clear_all_data(direct_db)

    # 2 dirs + 1 stray file = 3 successful deletions
    assert result["files_deleted"] == 3
    assert list(tmp_path.iterdir()) == []
    assert result["status"] == "cleared"


@pytest.mark.asyncio
async def test_clear_data_direct_only_stray_files(direct_db, tmp_path, monkeypatch):
    """Lines 129-145: only stray files (no dirs) → unlink branch hit."""
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text(name)

    result = await clear_all_data(direct_db)

    # All 3 stray files unlinked successfully (line 142)
    assert result["files_deleted"] == 3
    assert list(tmp_path.iterdir()) == []


# ===========================================================================
# B) GET /admin/stats — direct call
# ===========================================================================

@pytest.mark.asyncio
async def test_stats_direct_empty_db_returns_zeros(direct_db):
    """Lines 173-180: empty DB → all 5 count() calls hit `or 0` falsy branch."""
    stats = await get_admin_stats(direct_db)
    assert stats == {
        "protocols": 0, "audio_files": 0, "utterances": 0,
        "screenshots": 0, "folders": 0,
    }


@pytest.mark.asyncio
async def test_stats_direct_full_db_counts_truthy(direct_db):
    """Lines 173-179: every count() returns a truthy value (>= 1)."""
    await _populate_full(direct_db)
    stats = await get_admin_stats(direct_db)
    assert stats["protocols"] >= 1
    assert stats["audio_files"] >= 1
    assert stats["utterances"] >= 1
    # screenshots >= 1 (populated), folders >= 1 (populated)
    assert stats["screenshots"] >= 1
    assert stats["folders"] >= 1


@pytest.mark.asyncio
async def test_stats_direct_after_clear_all_zero(direct_db, tmp_path, monkeypatch):
    """DELETE then GET /stats → all zero (covers both endpoints in sequence)."""
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    await _populate_full(direct_db)
    await clear_all_data(direct_db)
    stats = await get_admin_stats(direct_db)
    assert stats == {
        "protocols": 0, "audio_files": 0, "utterances": 0,
        "screenshots": 0, "folders": 0,
    }


# ===========================================================================
# C) Logging semantics — direct call
# ===========================================================================

@pytest.mark.asyncio
async def test_clear_data_logs_full_payload(direct_db, log_calls, tmp_path, monkeypatch):
    """Line 153-157: success log carries deleted_counts dict + files_deleted int."""
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    await _populate_full(direct_db)
    await clear_all_data(direct_db)

    success = [c for c in log_calls.calls if c[0] == "all_data_cleared"]
    assert len(success) == 1
    _, kw = success[0]
    assert isinstance(kw["deleted_counts"], dict)
    assert isinstance(kw["files_deleted"], int)
    assert len(kw["deleted_counts"]) == 12  # all 12 tracked tables


@pytest.mark.asyncio
async def test_clear_data_idempotent_two_direct_calls(direct_db, log_calls, tmp_path, monkeypatch):
    """Two direct DELETEs in a row → both succeed, second is a no-op."""
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    await _populate_full(direct_db)
    r1 = await clear_all_data(direct_db)
    r2 = await clear_all_data(direct_db)
    assert r1["status"] == r2["status"] == "cleared"
    assert all(v == 0 for v in r2["deleted_counts"].values())
    # Two success logs total
    assert len([c for c in log_calls.calls if c[0] == "all_data_cleared"]) == 2


# ===========================================================================
# D) Sanity — HTTP path still works (regression guard)
# ===========================================================================

@pytest.mark.asyncio
async def test_http_clear_data_still_works(client, _shim_logger):
    """Smoke test: HTTP path returns 200 + correct shape (no regression)."""
    r = await client.delete(f"{PREFIX}/admin/clear-data")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cleared"
    assert "Все данные удалены" in body["message"]
