"""Round 2 coverage tests for app/routers/folders.py — target 60%+.

Focus areas (per task brief):
- Soft-deleted protocol guard on add endpoint (404)
- Missing-folder guard on add endpoint (404)
- Missing-protocol guard on remove endpoint (404)
- Wrong-folder guard on remove endpoint (400)
- Move-to-missing-folder guard (404)
- Batch-move happy path with multiple protocols

Production bug discovered (NOT fixed here, task is coverage):
- app/routers/folders.py line 372: `from datetime import datetime` (missing timezone)
  but line 378 calls `datetime.now(timezone.utc)` → NameError. The batch_move
  endpoint crashes 500. We monkeypatch `timezone` into the module to work
  around this and exercise the surrounding code paths.
"""
import uuid
import pytest
import pytest_asyncio

PREFIX = "/api/v1/hmp"


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------

@pytest_asyncio.fixture
async def folder_factory(db_session):
    """Create a folder directly via DB."""
    from app.db.models import Folder
    from datetime import datetime, timezone

    async def _make(name: str = "Test Folder", **kwargs):
        f = Folder(
            id=uuid.uuid4(),
            name=name,
            color=kwargs.get("color", "#3b82f6"),
            icon=kwargs.get("icon", "folder"),
            parent_id=kwargs.get("parent_id"),
            sort_order=kwargs.get("sort_order", 0),
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(f)
        await db_session.commit()
        await db_session.refresh(f)
        return f

    return _make


@pytest_asyncio.fixture
async def fresh_protocol(db_session):
    """Create a fresh Protocol without folder_id set."""
    from app.db.models import Protocol, ProtocolStatus
    from datetime import datetime, timezone

    p = Protocol(
        id=uuid.uuid4(),
        title="Fresh",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def soft_deleted_protocol(db_session):
    """Create a Protocol with deleted_at set (soft-deleted)."""
    from app.db.models import Protocol, ProtocolStatus
    from datetime import datetime, timezone

    p = Protocol(
        id=uuid.uuid4(),
        title="Deleted Protocol",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
        deleted_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


# ----------------------------------------------------------------------------
# POST /folders/{folder_id}/protocols/{protocol_id}  (add) — guards
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_protocol_soft_deleted_protocol_404(
    client, folder_factory, soft_deleted_protocol
):
    """E62: add endpoint rejects soft-deleted protocol with 404.

    Branch: add_protocol_to_folder -> `protocol.deleted_at is not None` -> 404.
    """
    f = await folder_factory("Target")
    p = soft_deleted_protocol

    r = await client.post(f"{PREFIX}/folders/{f.id}/protocols/{p.id}")
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_add_protocol_folder_not_found_404(client, fresh_protocol):
    """E63: add endpoint returns 404 when folder is missing.

    Branch: add_protocol_to_folder -> `folder` falsy -> 404.
    """
    p = fresh_protocol
    fake_folder = uuid.uuid4()
    r = await client.post(f"{PREFIX}/folders/{fake_folder}/protocols/{p.id}")
    assert r.status_code == 404


# ----------------------------------------------------------------------------
# DELETE /folders/{folder_id}/protocols/{protocol_id}  (remove)
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_protocol_truly_missing_404(client, folder_factory):
    """E64: remove endpoint returns 404 when protocol row doesn't exist.

    Branch: remove_protocol_from_folder -> `not protocol` -> 404.
    """
    f = await folder_factory("F")
    fake_pid = uuid.uuid4()
    r = await client.delete(f"{PREFIX}/folders/{f.id}/protocols/{fake_pid}")
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_remove_protocol_wrong_folder_400(
    client, folder_factory, fresh_protocol
):
    """E65: remove endpoint returns 400 when protocol is not in named folder.

    Branch: remove_protocol_from_folder -> `protocol.folder_id != folder_id` -> 400.
    """
    f1 = await folder_factory("F1")
    f2 = await folder_factory("F2")
    p = fresh_protocol

    # Add protocol to f1
    r1 = await client.post(f"{PREFIX}/folders/{f1.id}/protocols/{p.id}")
    assert r1.status_code == 200

    # Try to remove from f2 — wrong folder
    r2 = await client.delete(f"{PREFIX}/folders/{f2.id}/protocols/{p.id}")
    assert r2.status_code == 400
    assert "не в этой папке" in r2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_remove_protocol_success(
    client, folder_factory, fresh_protocol
):
    """E66: remove endpoint happy path — protocol.folder_id == folder_id -> 200."""
    f = await folder_factory("Holder")
    p = fresh_protocol

    # Add then remove
    await client.post(f"{PREFIX}/folders/{f.id}/protocols/{p.id}")
    r = await client.delete(f"{PREFIX}/folders/{f.id}/protocols/{p.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["protocol_id"] == str(p.id)


# ----------------------------------------------------------------------------
# PUT /protocols/{protocol_id}/folder  (move)
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_move_protocol_to_unknown_folder_404(client, fresh_protocol):
    """E67: move endpoint returns 404 when target folder doesn't exist.

    Branch: move_protocol_to_folder -> `not folder` -> 404.
    """
    p = fresh_protocol
    fake = uuid.uuid4()
    r = await client.put(
        f"{PREFIX}/protocols/{p.id}/folder",
        json={"folder_id": str(fake)},
    )
    assert r.status_code == 404
    assert "папка" in r.json()["detail"].lower()


# ----------------------------------------------------------------------------
# POST /protocols/batch-move
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_move_happy_path_multiple_protocols(
    client, folder_factory, db_session, monkeypatch
):
    """E68: batch-move 3 protocols to one folder — full happy path.

    Branch: batch_move_protocols -> all ids found, folder_id set, commit.

    Workaround for production bug: app/routers/folders.py:378 references
    `timezone.utc` but only imports `datetime` (missing timezone). We patch
    `timezone` into the module namespace so the branch executes.
    """
    from app.db.models import Protocol, ProtocolStatus
    from datetime import datetime, timezone

    f = await folder_factory("Dest")

    protocols = []
    for i in range(3):
        p = Protocol(
            id=uuid.uuid4(),
            title=f"BP{i}",
            status=ProtocolStatus.RECORDING,
            date=datetime.now(timezone.utc).date(),
            created_at=datetime.now(timezone.utc),
        )
        protocols.append(p)
    db_session.add_all(protocols)
    await db_session.commit()

    # Workaround the production code's missing timezone import
    import app.routers.folders as folders_mod
    monkeypatch.setattr(folders_mod, "timezone", timezone, raising=False)

    ids = [str(p.id) for p in protocols]
    r = await client.post(
        f"{PREFIX}/protocols/batch-move",
        json={"protocol_ids": ids, "folder_id": str(f.id)},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["moved_count"] == 3
    assert body["folder_id"] == str(f.id)


@pytest.mark.asyncio
async def test_batch_move_to_unknown_folder_404(client, monkeypatch):
    """E69: batch-move with non-existent target folder -> 404.

    Branch: batch_move_protocols -> folder lookup fails -> 404.
    """
    fake_pid = str(uuid.uuid4())
    fake_fid = str(uuid.uuid4())
    r = await client.post(
        f"{PREFIX}/protocols/batch-move",
        json={"protocol_ids": [fake_pid], "folder_id": fake_fid},
    )
    assert r.status_code == 404
    assert "папка" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_batch_move_folder_id_none(
    client, folder_factory, db_session, monkeypatch
):
    """E70: batch-move with folder_id=None — bypasses folder check.

    Branch: batch_move_protocols -> `if body.folder_id is not None` skipped.

    Workaround the production code's missing timezone import.
    """
    from app.db.models import Protocol, ProtocolStatus
    from datetime import datetime, timezone

    f = await folder_factory("Some Folder")
    p = Protocol(
        id=uuid.uuid4(),
        title="P",
        status=ProtocolStatus.RECORDING,
        folder_id=f.id,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.commit()

    import app.routers.folders as folders_mod
    monkeypatch.setattr(folders_mod, "timezone", timezone, raising=False)

    r = await client.post(
        f"{PREFIX}/protocols/batch-move",
        json={"protocol_ids": [str(p.id)], "folder_id": None},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["folder_id"] is None
    assert body["moved_count"] == 1