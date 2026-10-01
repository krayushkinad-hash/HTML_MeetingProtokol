"""Tests for app/routers/actions.py — Action Items CRUD (US-023, US-024).

Coverage targets:
- GET  /api/v1/protocols/{protocol_id}/action-items  (list, filters, 404, 422)
- POST /api/v1/action-items                          (create, 404, 422 validation)
- PATCH /api/v1/action-items/{action_item_id}        (status, owner, 404, 422 empty body)
- DELETE /api/v1/action-items/{action_item_id}       (delete, 404)
- POST /api/v1/ai/extract-actions                    (stub happy path + 404)

Router is mounted under api_prefix (default `/api/v1`) per app/main.py.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest


API_PREFIX = "/api/v1/hmp"


# ===========================================================================
# Helpers — small factories built on top of fixtures
# ===========================================================================
async def _create_action_item(db_session, protocol, **overrides):
    """Insert an ActionItem row directly so we don't go through the router."""
    from app.db.models import ActionItem
    from datetime import datetime, timezone

    item = ActionItem(
        id=overrides.get("id", uuid.uuid4()),
        protocol_id=protocol.id,
        owner=overrides.get("owner", "Alice"),
        task=overrides.get("task", "Send weekly report"),
        deadline=overrides.get("deadline"),
        status=overrides.get("status", "open"),
        source=overrides.get("source", "manual"),
        source_utterance_id=overrides.get("source_utterance_id"),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item


# ===========================================================================
# GET /protocols/{protocol_id}/action-items — list
# ===========================================================================
@pytest.mark.asyncio
async def test_list_action_items_empty(client, sample_protocol):
    """GET with no items → empty list, total=0, but successful."""
    r = await client.get(f"{API_PREFIX}/protocols/{sample_protocol.id}/action-items")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 0
    assert body["items"] == []
    assert body["skip"] == 0
    assert body["limit"] == 100


@pytest.mark.asyncio
async def test_list_action_items_with_data(client, sample_protocol, db_session):
    """GET returns multiple items, respects skip/limit, default ordering."""
    from datetime import timedelta

    base = date(2026, 6, 1)
    await _create_action_item(db_session, sample_protocol, task="Task A", deadline=base + timedelta(days=3))
    await _create_action_item(db_session, sample_protocol, task="Task B", deadline=base + timedelta(days=1))
    await _create_action_item(db_session, sample_protocol, task="Task C", deadline=None)

    r = await client.get(f"{API_PREFIX}/protocols/{sample_protocol.id}/action-items")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3
    # Earlier deadline (Task B) first
    assert body["items"][0]["task"] == "Task B"


@pytest.mark.asyncio
async def test_list_action_items_status_filter(client, sample_protocol, db_session):
    """GET ?status=open filters by status."""
    await _create_action_item(db_session, sample_protocol, task="Open task", status="open")
    await _create_action_item(db_session, sample_protocol, task="Done task", status="done")
    await _create_action_item(db_session, sample_protocol, task="In-prog task", status="in_progress")

    r = await client.get(
        f"{API_PREFIX}/protocols/{sample_protocol.id}/action-items",
        params={"status": "open"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["task"] == "Open task"
    assert body["items"][0]["status"] == "open"


@pytest.mark.asyncio
async def test_list_action_items_owner_filter(client, sample_protocol, db_session):
    """GET ?owner=Bob filters by owner."""
    await _create_action_item(db_session, sample_protocol, task="Alice owns it", owner="Alice")
    await _create_action_item(db_session, sample_protocol, task="Bob owns it", owner="Bob")

    r = await client.get(
        f"{API_PREFIX}/protocols/{sample_protocol.id}/action-items",
        params={"owner": "Bob"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["owner"] == "Bob"


@pytest.mark.asyncio
async def test_list_action_items_invalid_status_returns_422(client, sample_protocol):
    """Invalid status value → 422."""
    r = await client.get(
        f"{API_PREFIX}/protocols/{sample_protocol.id}/action-items",
        params={"status": "not_a_real_status"},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_list_action_items_protocol_not_found_returns_404(client):
    """Unknown protocol_id → 404."""
    r = await client.get(f"{API_PREFIX}/protocols/{uuid.uuid4()}/action-items")
    assert r.status_code == 404
    assert "Протокол" in r.json()["detail"]


@pytest.mark.asyncio
async def test_list_action_items_pagination(client, sample_protocol, db_session):
    """skip/limit honoured."""
    for i in range(5):
        await _create_action_item(db_session, sample_protocol, task=f"Task {i}")

    r = await client.get(
        f"{API_PREFIX}/protocols/{sample_protocol.id}/action-items",
        params={"skip": 2, "limit": 2},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["skip"] == 2
    assert body["limit"] == 2


# ===========================================================================
# POST /action-items — create
# ===========================================================================
@pytest.mark.asyncio
async def test_create_action_item_success(client, sample_protocol):
    """Happy path: 201 + body returned with status='open', source='manual'."""
    payload = {
        "protocol_id": str(sample_protocol.id),
        "owner": "Carol",
        "task": "Prepare sprint demo for stakeholders",
        "deadline": "2026-12-01",
    }
    r = await client.post(f"{API_PREFIX}/action-items", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["task"] == payload["task"]
    assert body["owner"] == "Carol"
    assert body["status"] == "open"
    assert body["source"] == "manual"
    assert body["protocol_id"] == str(sample_protocol.id)
    assert body["deadline"] == "2026-12-01"
    assert "id" in body


@pytest.mark.asyncio
async def test_create_action_item_without_optional_fields(client, sample_protocol):
    """owner/utterance/deadline are all optional."""
    payload = {
        "protocol_id": str(sample_protocol.id),
        "task": "Minimal action item with only required fields",
    }
    r = await client.post(f"{API_PREFIX}/action-items", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["owner"] is None
    assert body["deadline"] is None


@pytest.mark.asyncio
async def test_create_action_item_protocol_not_found_returns_404(client):
    """POST referencing a non-existent protocol → 404."""
    payload = {
        "protocol_id": str(uuid.uuid4()),
        "task": "This should fail because protocol is missing",
    }
    r = await client.post(f"{API_PREFIX}/action-items", json=payload)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_action_item_validation_error_returns_422(client, sample_protocol):
    """Short task (min_length=5) → 422 from Pydantic."""
    payload = {
        "protocol_id": str(sample_protocol.id),
        "task": "no",  # too short
    }
    r = await client.post(f"{API_PREFIX}/action-items", json=payload)
    assert r.status_code == 422


# ===========================================================================
# PATCH /action-items/{action_item_id} — update
# ===========================================================================
@pytest.mark.asyncio
async def test_update_action_item_status_to_done_sets_completed_at(client, sample_protocol, db_session):
    """Transition to 'done' auto-stamps completed_at."""
    item = await _create_action_item(db_session, sample_protocol, task="Ship MVP")
    assert item.completed_at is None

    r = await client.patch(
        f"{API_PREFIX}/action-items/{item.id}",
        json={"status": "done"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "done"
    assert body["completed_at"] is not None


@pytest.mark.asyncio
async def test_update_action_item_owner(client, sample_protocol, db_session):
    """PATCH owner only."""
    item = await _create_action_item(db_session, sample_protocol, owner="Alice")

    r = await client.patch(
        f"{API_PREFIX}/action-items/{item.id}",
        json={"owner": "Diana"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["owner"] == "Diana"
    assert body["status"] == "open"  # unchanged


@pytest.mark.asyncio
async def test_update_action_item_reopen_clears_completed_at(client, sample_protocol, db_session):
    """Reopening a 'done' item clears completed_at."""
    item = await _create_action_item(db_session, sample_protocol, task="Ship MVP")
    # Pre-seed via direct write so we don't double-PATCH (which can race the SAVEPOINT)
    from datetime import datetime, timezone
    item.completed_at = datetime.now(timezone.utc)
    item.status = "done"
    await db_session.commit()
    await db_session.refresh(item)

    r = await client.patch(
        f"{API_PREFIX}/action-items/{item.id}",
        json={"status": "in_progress"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "in_progress"
    assert body["completed_at"] is None


@pytest.mark.asyncio
async def test_update_action_item_not_found_returns_404(client):
    """PATCH on unknown id → 404."""
    r = await client.patch(
        f"{API_PREFIX}/action-items/{uuid.uuid4()}",
        json={"status": "done"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_action_item_empty_body_returns_422(client, sample_protocol, db_session):
    """Empty PATCH body (no fields to update) → 422."""
    item = await _create_action_item(db_session, sample_protocol, task="No-op patch")

    r = await client.patch(
        f"{API_PREFIX}/action-items/{item.id}",
        json={},
    )
    assert r.status_code == 422
    assert "Нет полей" in r.json()["detail"]


@pytest.mark.asyncio
async def test_update_action_item_invalid_status_returns_422(client, sample_protocol, db_session):
    """Invalid status literal → 422 from Pydantic."""
    item = await _create_action_item(db_session, sample_protocol, task="Bad status")

    r = await client.patch(
        f"{API_PREFIX}/action-items/{item.id}",
        json={"status": "not_a_valid_state"},
    )
    assert r.status_code == 422


# ===========================================================================
# DELETE /action-items/{action_item_id}
# ===========================================================================
@pytest.mark.asyncio
async def test_delete_action_item_success(client, sample_protocol, db_session):
    """DELETE removes the row and returns 200."""
    item = await _create_action_item(db_session, sample_protocol, task="Throwaway")

    r = await client.delete(f"{API_PREFIX}/action-items/{item.id}")
    assert r.status_code == 200, r.text

    # Confirm it's gone — subsequent GET on list should not contain it
    r2 = await client.get(f"{API_PREFIX}/protocols/{sample_protocol.id}/action-items")
    assert r2.status_code == 200
    ids = [i["id"] for i in r2.json()["items"]]
    assert str(item.id) not in ids


@pytest.mark.asyncio
async def test_delete_action_item_not_found_returns_404(client):
    """DELETE on unknown id → 404."""
    r = await client.delete(f"{API_PREFIX}/action-items/{uuid.uuid4()}")
    assert r.status_code == 404


# ===========================================================================
# POST /ai/extract-actions — stub
# ===========================================================================
@pytest.mark.asyncio
async def test_extract_actions_stub_success(client, sample_protocol):
    """Stub endpoint returns empty result for an existing protocol."""
    payload = {
        "protocol_id": str(sample_protocol.id),
        "provider": "hermes",
        "min_confidence": 0.6,
        "add_to_existing": False,
    }
    r = await client.post(f"{API_PREFIX}/ai/extract-actions", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["extracted_count"] == 0
    assert body["average_confidence"] is None
    assert body["action_items"] == []


@pytest.mark.asyncio
async def test_extract_actions_protocol_not_found_returns_404(client):
    """Stub endpoint on missing protocol → 404."""
    payload = {
        "protocol_id": str(uuid.uuid4()),
        "provider": "hermes",
        "min_confidence": 0.6,
        "add_to_existing": True,
    }
    r = await client.post(f"{API_PREFIX}/ai/extract-actions", json=payload)
    assert r.status_code == 404