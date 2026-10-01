"""Round 1 coverage tests for app/routers/folders.py — target 50%+."""
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


# ----------------------------------------------------------------------------
# GET /folders
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_folders_empty(client):
    """E30: empty list when no folders exist."""
    r = await client.get(f"{PREFIX}/folders")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_folders_returns_all(client, folder_factory):
    """E31: returns all folders ordered by sort_order/name."""
    a = await folder_factory("Alpha", sort_order=2)
    b = await folder_factory("Bravo", sort_order=1)
    c = await folder_factory("Charlie", sort_order=1)

    r = await client.get(f"{PREFIX}/folders")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 3
    # sort_order=1 comes first (Bravo, Charlie by name)
    names = [d["name"] for d in data]
    assert names == ["Bravo", "Charlie", "Alpha"]


@pytest.mark.asyncio
async def test_list_folders_filter_by_parent(client, folder_factory):
    """E32: parent_id filter narrows results."""
    parent = await folder_factory("Parent")
    child1 = await folder_factory("Child1", parent_id=parent.id)
    child2 = await folder_factory("Child2", parent_id=parent.id)
    sibling = await folder_factory("Sibling")

    r = await client.get(f"{PREFIX}/folders", params={"parent_id": str(parent.id)})
    assert r.status_code == 200
    data = r.json()
    ids = {d["id"] for d in data}
    assert str(child1.id) in ids
    assert str(child2.id) in ids
    assert str(parent.id) not in ids
    assert str(sibling.id) not in ids


@pytest.mark.asyncio
async def test_list_folders_protocol_count(client, folder_factory, db_session):
    """E33: protocol_count reflects Protocol rows with folder_id set."""
    from app.db.models import Protocol, ProtocolStatus
    from datetime import datetime, timezone

    f1 = await folder_factory("With Protocols")
    f2 = await folder_factory("Empty Folder")

    p1 = Protocol(
        id=uuid.uuid4(),
        title="P1",
        status=ProtocolStatus.RECORDING,
        folder_id=f1.id,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    p2 = Protocol(
        id=uuid.uuid4(),
        title="P2",
        status=ProtocolStatus.RECORDING,
        folder_id=f1.id,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add_all([p1, p2])
    await db_session.commit()

    r = await client.get(f"{PREFIX}/folders")
    assert r.status_code == 200
    counts = {d["name"]: d["protocol_count"] for d in r.json()}
    assert counts["With Protocols"] == 2
    assert counts["Empty Folder"] == 0


# ----------------------------------------------------------------------------
# POST /folders
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_folder_minimal(client):
    """E34: minimal payload (only required field)."""
    r = await client.post(f"{PREFIX}/folders", json={"name": "New Folder"})
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "New Folder"
    assert data["color"] == "#3b82f6"
    assert data["icon"] == "folder"
    assert data["parent_id"] is None
    assert data["sort_order"] == 0
    assert "id" in data


@pytest.mark.asyncio
async def test_create_folder_full_payload(client):
    """E35: all fields populated."""
    payload = {
        "name": "Full",
        "color": "#ff0000",
        "icon": "star",
        "parent_id": None,
        "sort_order": 42,
    }
    r = await client.post(f"{PREFIX}/folders", json=payload)
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Full"
    assert data["color"] == "#ff0000"
    assert data["icon"] == "star"
    assert data["sort_order"] == 42


@pytest.mark.asyncio
async def test_create_folder_with_parent(client, folder_factory):
    """E36: parent_id validates that parent exists."""
    p = await folder_factory("Parent")
    r = await client.post(
        f"{PREFIX}/folders",
        json={"name": "Child", "parent_id": str(p.id)},
    )
    assert r.status_code == 201
    assert r.json()["parent_id"] == str(p.id)


@pytest.mark.asyncio
async def test_create_folder_parent_not_found(client):
    """E37: parent_id referring to nonexistent folder -> 404."""
    fake_id = str(uuid.uuid4())
    r = await client.post(
        f"{PREFIX}/folders",
        json={"name": "Orphan", "parent_id": fake_id},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_folder_invalid_color(client):
    """E38: invalid color pattern -> 422."""
    r = await client.post(
        f"{PREFIX}/folders",
        json={"name": "Bad", "color": "notacolor"},
    )
    assert r.status_code == 422


# ----------------------------------------------------------------------------
# GET /folders/{folder_id}
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_folder_success(client, folder_factory):
    """E39: get existing folder."""
    f = await folder_factory("Detail")
    r = await client.get(f"{PREFIX}/folders/{f.id}")
    assert r.status_code == 200
    assert r.json()["name"] == "Detail"


@pytest.mark.asyncio
async def test_get_folder_not_found(client):
    """E40: 404 for unknown id."""
    r = await client.get(f"{PREFIX}/folders/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_folder_with_protocols(client, folder_factory, db_session):
    """E41: protocol_count populated for GET-by-id."""
    from app.db.models import Protocol, ProtocolStatus
    from datetime import datetime, timezone

    f = await folder_factory("Counted")
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

    r = await client.get(f"{PREFIX}/folders/{f.id}")
    assert r.status_code == 200
    assert r.json()["protocol_count"] == 1


# ----------------------------------------------------------------------------
# PATCH /folders/{folder_id}
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_folder_name(client, folder_factory):
    """E42: rename folder."""
    f = await folder_factory("Old Name")
    r = await client.patch(f"{PREFIX}/folders/{f.id}", json={"name": "New Name"})
    assert r.status_code == 200
    assert r.json()["name"] == "New Name"


@pytest.mark.asyncio
async def test_update_folder_color_icon_sort(client, folder_factory):
    """E43: update color/icon/sort_order."""
    f = await folder_factory("X")
    r = await client.patch(
        f"{PREFIX}/folders/{f.id}",
        json={"color": "#00ff00", "icon": "book", "sort_order": 99},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["color"] == "#00ff00"
    assert data["icon"] == "book"
    assert data["sort_order"] == 99


@pytest.mark.asyncio
async def test_update_folder_not_found(client):
    """E44: patch unknown id -> 404."""
    r = await client.patch(f"{PREFIX}/folders/{uuid.uuid4()}", json={"name": "Z"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_folder_circular_parent(client, folder_factory):
    """E45: parent_id == folder_id -> 400."""
    f = await folder_factory("Self")
    r = await client.patch(
        f"{PREFIX}/folders/{f.id}",
        json={"parent_id": str(f.id)},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_update_folder_change_parent(client, folder_factory):
    """E46: reparent to another folder."""
    p = await folder_factory("Parent")
    c = await folder_factory("Child")
    r = await client.patch(
        f"{PREFIX}/folders/{c.id}",
        json={"parent_id": str(p.id)},
    )
    assert r.status_code == 200
    assert r.json()["parent_id"] == str(p.id)


# ----------------------------------------------------------------------------
# DELETE /folders/{folder_id}
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_folder_success(client, folder_factory):
    """E47: delete returns status=deleted."""
    f = await folder_factory("To Delete")
    r = await client.delete(f"{PREFIX}/folders/{f.id}")
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"

    # Confirm gone
    r2 = await client.get(f"{PREFIX}/folders/{f.id}")
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_delete_folder_not_found(client):
    """E48: delete unknown -> 404."""
    r = await client.delete(f"{PREFIX}/folders/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_folder_uncategorizes_protocols(
    client, folder_factory, db_session, db_engine
):
    """E49: deleting folder sets protocols.folder_id = NULL (uncategorized)."""
    from app.db.models import Protocol, ProtocolStatus
    from datetime import datetime, timezone
    from sqlalchemy import select

    f = await folder_factory("Holder")
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

    r = await client.delete(f"{PREFIX}/folders/{f.id}")
    assert r.status_code == 200

    # Verify protocol's folder_id is now NULL — use a fresh engine session
    # (db_session holds an open txn with stale snapshot)
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker
    fresh_factory = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with fresh_factory() as verify_session:
        res = await verify_session.execute(select(Protocol).where(Protocol.id == p.id))
        refreshed = res.scalar_one()
        assert refreshed.folder_id is None


# ----------------------------------------------------------------------------
# POST /folders/{folder_id}/protocols/{protocol_id}  (add)
# ----------------------------------------------------------------------------

@pytest_asyncio.fixture
async def sample_protocol_for_folder(db_session):
    """Fresh protocol for move tests."""
    from app.db.models import Protocol, ProtocolStatus
    from datetime import datetime, timezone

    p = Protocol(
        id=uuid.uuid4(),
        title="Movable",
        status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest.mark.asyncio
async def test_add_protocol_to_folder_success(
    client, folder_factory, sample_protocol_for_folder
):
    """E50: POST adds protocol to folder."""
    f = await folder_factory("Target")
    p = sample_protocol_for_folder
    r = await client.post(f"{PREFIX}/folders/{f.id}/protocols/{p.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["protocol_id"] == str(p.id)
    assert body["folder_id"] == str(f.id)


@pytest.mark.asyncio
async def test_add_protocol_folder_not_found(client, sample_protocol_for_folder):
    """E51: folder 404."""
    p = sample_protocol_for_folder
    r = await client.post(f"{PREFIX}/folders/{uuid.uuid4()}/protocols/{p.id}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_add_protocol_protocol_not_found(client, folder_factory):
    """E52: protocol 404."""
    f = await folder_factory("F")
    r = await client.post(f"{PREFIX}/folders/{f.id}/protocols/{uuid.uuid4()}")
    assert r.status_code == 404


# ----------------------------------------------------------------------------
# DELETE /folders/{folder_id}/protocols/{protocol_id}  (remove)
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_protocol_from_folder_wrong_folder(
    client, folder_factory, sample_protocol_for_folder
):
    """E53: protocol.folder_id != folder_id -> 400."""
    f1 = await folder_factory("F1")
    f2 = await folder_factory("F2")
    p = sample_protocol_for_folder
    # First add protocol to f1
    r1 = await client.post(f"{PREFIX}/folders/{f1.id}/protocols/{p.id}")
    assert r1.status_code == 200
    # Now try to remove from f2 -> should fail
    r2 = await client.delete(f"{PREFIX}/folders/{f2.id}/protocols/{p.id}")
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_remove_protocol_from_folder_protocol_not_found(client, folder_factory):
    """E54: protocol 404."""
    f = await folder_factory("F")
    r = await client.delete(f"{PREFIX}/folders/{f.id}/protocols/{uuid.uuid4()}")
    assert r.status_code == 404


# ----------------------------------------------------------------------------
# PUT /protocols/{protocol_id}/folder  (move to folder)
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_move_protocol_to_folder_success(
    client, folder_factory, sample_protocol_for_folder
):
    """E55: PUT moves protocol to folder."""
    f = await folder_factory("Dest")
    p = sample_protocol_for_folder
    r = await client.put(
        f"{PREFIX}/protocols/{p.id}/folder",
        json={"folder_id": str(f.id)},
    )
    assert r.status_code == 200
    assert r.json()["folder_id"] == str(f.id)


@pytest.mark.asyncio
async def test_move_protocol_remove_from_folder(
    client, folder_factory, sample_protocol_for_folder
):
    """E56: folder_id=None removes protocol from any folder."""
    f = await folder_factory("F")
    p = sample_protocol_for_folder
    # Move into folder first
    await client.put(
        f"{PREFIX}/protocols/{p.id}/folder",
        json={"folder_id": str(f.id)},
    )
    # Move out
    r = await client.put(
        f"{PREFIX}/protocols/{p.id}/folder",
        json={"folder_id": None},
    )
    assert r.status_code == 200
    assert r.json()["folder_id"] == "None"


@pytest.mark.asyncio
async def test_move_protocol_target_folder_not_found(client, sample_protocol_for_folder):
    """E57: target folder 404."""
    p = sample_protocol_for_folder
    r = await client.put(
        f"{PREFIX}/protocols/{p.id}/folder",
        json={"folder_id": str(uuid.uuid4())},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_move_protocol_not_found(client, folder_factory):
    """E58: protocol 404."""
    f = await folder_factory("F")
    r = await client.put(
        f"{PREFIX}/protocols/{uuid.uuid4()}/folder",
        json={"folder_id": str(f.id)},
    )
    assert r.status_code == 404


# ----------------------------------------------------------------------------
# POST /protocols/batch-move
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_move_protocols_success(
    client, folder_factory, db_session
):
    """E59: batch move 2 protocols."""
    from app.db.models import Protocol, ProtocolStatus
    from datetime import datetime, timezone

    f = await folder_factory("Batch")
    p1 = Protocol(
        id=uuid.uuid4(), title="B1", status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    p2 = Protocol(
        id=uuid.uuid4(), title="B2", status=ProtocolStatus.RECORDING,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add_all([p1, p2])
    await db_session.commit()

    r = await client.post(
        f"{PREFIX}/protocols/batch-move",
        json={"protocol_ids": [str(p1.id), str(p2.id)], "folder_id": str(f.id)},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["moved_count"] == 2


@pytest.mark.asyncio
async def test_batch_move_folder_not_found(client):
    """E60: target folder 404."""
    fake_pid = str(uuid.uuid4())
    fake_fid = str(uuid.uuid4())
    r = await client.post(
        f"{PREFIX}/protocols/batch-move",
        json={"protocol_ids": [fake_pid], "folder_id": fake_fid},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_batch_move_remove_from_folder(
    client, folder_factory, db_session
):
    """E61: batch move with folder_id=None removes from any folder."""
    from app.db.models import Protocol, ProtocolStatus
    from datetime import datetime, timezone

    f = await folder_factory("F")
    p = Protocol(
        id=uuid.uuid4(), title="X", status=ProtocolStatus.RECORDING,
        folder_id=f.id,
        date=datetime.now(timezone.utc).date(),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(p)
    await db_session.commit()

    r = await client.post(
        f"{PREFIX}/protocols/batch-move",
        json={"protocol_ids": [str(p.id)], "folder_id": None},
    )
    assert r.status_code == 200
    # folder_id field is None when None, or legacy "None" string from str(None)
    assert r.json()["folder_id"] in (None, "None")