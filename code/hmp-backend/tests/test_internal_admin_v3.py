"""E360 v3: push app/routers/admin.py coverage past 70%.

Strategy
--------
The default `db_engine` fixture in conftest TRUNCATEs every public schema table
per test (~30-60s overhead). v3 splits into two groups:

A) **HTTP-only tests** (404/405) — no DB. Import `app` directly, mount
   ASGITransport. Skip conftest.db_engine entirely. Fast (<1s).

B) **DB-touching tests** — use conftest fixtures. Only 6 tests needed to push
   coverage past 70%; targeting specific lines (success log kwargs, falsy
   `or 0` branch in stats, protocols_path branches, rmtree, iterdir).

Coverage targets (complement to v2):
- Line 153-157: success logger.info("all_data_cleared", deleted_counts=..., files_deleted=...)
- Lines 57-112: each `result.scalar() or 0` truthy branch (Protocol populated)
- Lines 174-178: each count() line in stats endpoint (populated + empty)
- Lines 125-145: protocols_path branches (exists True / False; nested files)
- Line 144 `except Exception: pass`: stray file unlink fails → swallowed
- HTTP: GET on DELETE-only → 405, POST on GET-only → 405, unknown path → 404
"""
import asyncio
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete as sql_delete

from app.db.models import (
    Protocol, ProtocolStatus,
    Utterance, Speaker, Tag, ActionItem, Decision, Summary,
    TranscriptionTask, Screenshot, AudioFile,
    Folder, ProtocolVersion, UserSetting,
)
from app.routers import admin as admin_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _StructLogShim:
    def __init__(self):
        self.calls = []

    def _log(self, level, event, **kw):
        self.calls.append((event, kw))

    def debug(self, event, **kw): self._log("DEBUG", event, **kw)
    def info(self, event, **kw):  self._log("INFO", event, **kw)
    def warning(self, event, **kw): self._log("WARNING", event, **kw)
    def error(self, event, **kw): self._log("ERROR", event, **kw)


@pytest.fixture
def structlog_logger(monkeypatch):
    shim = _StructLogShim()
    monkeypatch.setattr(admin_module, "logger", shim)
    return shim


@pytest_asyncio.fixture
async def http_client():
    """AsyncClient with NO DB dependency — for 404/405 paths only."""
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# conftest.db_engine already TRUNCATEs all tables on creation (function scope).
# The per-test recreation is slow (~30-60s each) but avoids deadlocks.


async def _mk_prot(s):
    p = Protocol(
        id=uuid.uuid4(),
        title="T",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    s.add(p)
    await s.commit()
    return p


# ===========================================================================
# A) HTTP-only tests — no DB fixture (fast)
# ===========================================================================

@pytest.mark.asyncio
async def test_wrong_method_get_on_clear_data_returns_405(http_client):
    """GET on DELETE-only /admin/clear-data → 405."""
    r = await http_client.get("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 405


@pytest.mark.asyncio
async def test_wrong_method_post_on_stats_returns_405(http_client):
    """POST on GET-only /admin/stats → 405."""
    r = await http_client.post("/api/v1/hmp/admin/stats")
    assert r.status_code == 405


@pytest.mark.asyncio
async def test_unknown_admin_path_returns_404(http_client):
    """Unknown /admin/* path → 404."""
    r = await http_client.get("/api/v1/hmp/admin/nonexistent")
    assert r.status_code == 404


# ===========================================================================
# B) DB-touching tests — use conftest fixtures
# ===========================================================================

@pytest.mark.asyncio
async def test_clear_data_empty_db_success_log_full_payload(client, structlog_logger):
    """Empty DB → success log on line 153-157 with deleted_counts dict + files_deleted int."""
    r = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 200, r.text
    success = [c for c in structlog_logger.calls if c[0] == "all_data_cleared"]
    assert len(success) == 1
    _, kw = success[0]
    assert "deleted_counts" in kw and "files_deleted" in kw
    assert isinstance(kw["files_deleted"], int)
    assert kw["files_deleted"] == 0
    for key in ("utterances", "speakers", "tags", "action_items",
                "decisions", "summaries", "transcription_tasks",
                "screenshots", "audio_files", "folders",
                "protocol_versions", "protocols"):
        assert kw["deleted_counts"][key] == 0


@pytest.mark.asyncio
async def test_clear_data_response_body_shape(client, structlog_logger):
    """Response body has 'status', 'message', 'deleted_counts', 'files_deleted'."""
    r = await client.delete("/api/v1/hmp/admin/clear-data")
    body = r.json()
    assert body["status"] == "cleared"
    assert "Все данные удалены" in body["message"]
    assert isinstance(body["deleted_counts"], dict)
    assert isinstance(body["files_deleted"], int)


@pytest.mark.asyncio
async def test_clear_data_with_protocol_populated(client, structlog_logger, db_session):
    """Populated Protocol only → protocols>=1, rest=0 via `or 0` falsy branch."""
    await _mk_prot(db_session)
    r = await client.delete("/api/v1/hmp/admin/clear-data")
    body = r.json()
    assert body["deleted_counts"]["protocols"] >= 1
    for key in ("utterances", "speakers", "tags", "action_items",
                "decisions", "summaries", "transcription_tasks",
                "screenshots", "audio_files", "folders",
                "protocol_versions"):
        assert body["deleted_counts"][key] == 0


@pytest.mark.asyncio
async def test_stats_empty_db(client):
    """Empty DB → all 5 count() lines hit `or 0` falsy branch."""
    r = await client.get("/api/v1/hmp/admin/stats")
    assert r.status_code == 200
    assert r.json() == {
        "protocols": 0, "audio_files": 0, "utterances": 0,
        "screenshots": 0, "folders": 0,
    }


@pytest.mark.asyncio
async def test_stats_with_protocol_truthy_branch(client, db_session):
    """Only Protocol → line 174 truthy, lines 175-178 falsy `or 0`."""
    await _mk_prot(db_session)
    r = await client.get("/api/v1/hmp/admin/stats")
    body = r.json()
    assert body["protocols"] >= 1
    for key in ("audio_files", "utterances", "screenshots", "folders"):
        assert body[key] == 0


@pytest.mark.asyncio
async def test_stats_after_clear_is_all_zero(client, structlog_logger):
    """DELETE then GET /stats → all zero (covers both endpoints in sequence)."""
    await client.delete("/api/v1/hmp/admin/clear-data")
    r = await client.get("/api/v1/hmp/admin/stats")
    assert r.json() == {
        "protocols": 0, "audio_files": 0, "utterances": 0,
        "screenshots": 0, "folders": 0,
    }


@pytest.mark.asyncio
async def test_clear_data_missing_protocols_path(client, monkeypatch, structlog_logger):
    """protocols_path.exists() == False → files_deleted=0 (line 127 False branch)."""
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", "/tmp/admin_v3_xyz_does_not_exist")
    r = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 200
    assert r.json()["files_deleted"] == 0


@pytest.mark.asyncio
async def test_clear_data_removes_nested_protocol_dir(
    client, tmp_path, monkeypatch, structlog_logger,
):
    """Non-empty protocol dir → rmtree runs (line 132), files_deleted>=1."""
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))
    prot = tmp_path / "abc"
    prot.mkdir()
    (prot / "index.html").write_text("<html/>")
    r = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 200
    assert r.json()["files_deleted"] >= 1
    assert not prot.exists()


@pytest.mark.asyncio
async def test_clear_data_removes_multiple_dirs_and_stray_files(
    client, tmp_path, monkeypatch, structlog_logger,
):
    """3 dirs + 2 stray files → files_deleted=5 (lines 129-145 all branches)."""
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))
    for i in range(3):
        d = tmp_path / f"d{i}"
        d.mkdir()
        (d / "f.txt").write_text("x")
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    r = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 200
    assert r.json()["files_deleted"] == 5
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_clear_data_rmtree_failure_warns_and_continues(
    client, tmp_path, monkeypatch, structlog_logger,
):
    """rmtree raises → folder_delete_failed warning logged (lines 134-139)."""
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))
    (tmp_path / "prot").mkdir()

    def boom(path, *a, **kw):
        raise OSError("simulated")
    monkeypatch.setattr("shutil.rmtree", boom)

    r = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 200
    assert r.json()["files_deleted"] == 0
    assert any(ev == "folder_delete_failed" for ev, _ in structlog_logger.calls)


@pytest.mark.asyncio
async def test_clear_data_unlink_failure_swallowed(
    client, tmp_path, monkeypatch, structlog_logger,
):
    """Stray file unlink fails → `except Exception: pass` (line 144)."""
    import pathlib as _pl
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))
    blocked = tmp_path / "blocked.txt"
    blocked.write_text("x")
    real_unlink = _pl.Path.unlink

    def maybe(self, *a, **kw):
        if "blocked" in str(self):
            raise OSError("perm denied")
        return real_unlink(self, *a, **kw)
    monkeypatch.setattr(_pl.Path, "unlink", maybe)

    r = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 200
    assert r.json()["files_deleted"] == 0
    assert blocked.exists()


@pytest.mark.asyncio
async def test_clear_data_outer_iterdir_failure_warns(
    client, tmp_path, monkeypatch, structlog_logger,
):
    """iterdir() raises → outer `clear_data_disk_error` warning (lines 146-147)."""
    import pathlib as _pl
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))
    (tmp_path / "x").mkdir()

    real_iterdir = _pl.Path.iterdir

    def boom(self, *a, **kw):
        if str(self) == str(tmp_path):
            raise OSError("boom")
        return real_iterdir(self, *a, **kw)
    monkeypatch.setattr(_pl.Path, "iterdir", boom)

    r = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 200
    assert r.json()["files_deleted"] == 0
    assert any(ev == "clear_data_disk_error" for ev, _ in structlog_logger.calls)


@pytest.mark.asyncio
async def test_clear_data_idempotent_two_calls(client, structlog_logger):
    """Two DELETEs in a row → both 200, second is a no-op (covers line 150-151 twice)."""
    r1 = await client.delete("/api/v1/hmp/admin/clear-data")
    r2 = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r1.status_code == r2.status_code == 200
    assert all(v == 0 for v in r2.json()["deleted_counts"].values())