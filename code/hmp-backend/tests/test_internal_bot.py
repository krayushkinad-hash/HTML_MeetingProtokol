"""E_test_bot: tests for app/routers/bot.py.

Endpoints covered (target ≥50% coverage of 193 statements):
- GET    /bot/settings
- PATCH  /bot/settings
- POST   /bot/test
- POST   /bot/restart
- GET    /bot/users
- POST   /bot/users
- PATCH  /bot/users/{user_id}
- DELETE /bot/users/{user_id}
- GET    /bot/commands-log
- POST   /bot/test-connection (validation only — no real network)

Includes:
- happy paths for each endpoint
- 404 / 409 / 422 error branches
- BotUserUpdate pydantic boundary (max_length=100) → 422
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db.models import ApiUser, CommandLog, UserSetting


API = "/api/v1/hmp/bot"


# ---------------------------------------------------------------------------
# Local fixtures / factories
# ---------------------------------------------------------------------------

@pytest.fixture
def make_user_setting(db_session):
    """Factory: create a bare UserSetting row (no api_user attached)."""
    async def _factory():
        s = UserSetting(
            id=uuid.uuid4(),
            llm_provider="hermes",
            whisper_model="large-v3",
            theme="auto",
        )
        db_session.add(s)
        await db_session.commit()
        await db_session.refresh(s)
        return s

    return _factory


@pytest.fixture
def make_api_user(db_session, make_user_setting):
    """Factory: create an ApiUser + its UserSetting."""
    async def _factory(telegram_id: int | None = None, is_active: bool = True):
        us = await make_user_setting()
        u = ApiUser(
            id=uuid.uuid4(),
            telegram_id=telegram_id if telegram_id is not None else 100_000_000 + abs(hash(str(uuid.uuid4()))) % 1_000_000,
            username="test_user",
            display_name="Test User",
            is_active=is_active,
            user_setting_id=us.id,
        )
        db_session.add(u)
        await db_session.commit()
        await db_session.refresh(u)
        return u

    return _factory


@pytest.fixture
def make_command_log(db_session, make_api_user):
    """Factory: create a CommandLog entry."""
    async def _factory(command: str = "/start", status: str = "success"):
        user = await make_api_user()
        cl = CommandLog(
            id=uuid.uuid4(),
            api_user_id=user.id,
            command=command,
            args=None,
            status=status,
            error_message=None,
            execution_ms=42,
            tokens_used=10,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(cl)
        await db_session.commit()
        await db_session.refresh(cl)
        return cl

    return _factory


# ===========================================================================
# /bot/settings
# ===========================================================================

@pytest.mark.asyncio
async def test_get_bot_settings_creates_singleton(client, db_session):
    """GET /bot/settings — first call auto-creates the singleton UserSetting."""
    r = await client.get(f"{API}/settings")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_active"] is True
    assert body["default_provider"] in ("hermes", "gigachat", "local_ollama")
    assert body["fallback_provider"] == "gigachat"
    assert "updated_at" in body

    # Side effect: a UserSetting row must exist now
    rows = (await db_session.execute(select(UserSetting))).scalars().all()
    assert len(rows) >= 1


@pytest.mark.asyncio
async def test_patch_bot_settings(client, db_session, make_user_setting):
    """PATCH /bot/settings — change default_provider + notifications_enabled."""
    await make_user_setting()  # ensure singleton exists

    r = await client.patch(
        f"{API}/settings",
        json={"default_provider": "gigachat", "notifications_enabled": False},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["default_provider"] == "gigachat"
    assert body["notifications_enabled"] is False


@pytest.mark.asyncio
async def test_patch_bot_settings_no_fields(client):
    """PATCH /bot/settings with empty body — no-op, still 200."""
    r = await client.patch(f"{API}/settings", json={})
    assert r.status_code == 200, r.text


# ===========================================================================
# /bot/test & /bot/restart — stubs
# ===========================================================================

@pytest.mark.asyncio
async def test_bot_test_stub(client):
    """POST /bot/test — stub returns sent=True."""
    r = await client.post(f"{API}/test")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sent"] is True
    assert body["provider"] == "mock"


@pytest.mark.asyncio
async def test_bot_restart_stub(client):
    """POST /bot/restart — stub returns restarted=True."""
    r = await client.post(f"{API}/restart")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["restarted"] is True
    assert body["provider"] == "mock"


# ===========================================================================
# /bot/users — list / create
# ===========================================================================

@pytest.mark.asyncio
async def test_list_bot_users_empty(client):
    """GET /bot/users on empty DB → []."""
    r = await client.get(f"{API}/users")
    assert r.status_code == 200, r.text
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_bot_users_with_data(client, make_api_user):
    """GET /bot/users returns created users."""
    u1 = await make_api_user()
    u2 = await make_api_user(is_active=False)

    r = await client.get(f"{API}/users")
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {x["id"] for x in body}
    assert str(u1.id) in ids and str(u2.id) in ids


@pytest.mark.asyncio
async def test_list_bot_users_filter_by_active(client, make_api_user):
    """GET /bot/users?is_active=true — only active users."""
    a = await make_api_user(is_active=True)
    _ = await make_api_user(is_active=False)

    r = await client.get(f"{API}/users", params={"is_active": "true"})
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {x["id"] for x in body}
    assert str(a.id) in ids
    assert all(x["is_active"] is True for x in body)


@pytest.mark.asyncio
async def test_add_bot_user_success(client, db_session):
    """POST /bot/users — creates a new ApiUser + UserSetting row."""
    payload = {
        "telegram_id": 555_000_111,
        "username": "alice",
        "display_name": "Alice",
    }
    r = await client.post(f"{API}/users", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["telegram_id"] == 555_000_111
    assert body["username"] == "alice"
    assert body["display_name"] == "Alice"
    assert body["is_active"] is True

    # Side effect: a row in api_user + user_setting
    n_users = len((await db_session.execute(select(ApiUser))).scalars().all())
    n_settings = len((await db_session.execute(select(UserSetting))).scalars().all())
    assert n_users == 1
    assert n_settings == 1


@pytest.mark.asyncio
async def test_add_bot_user_duplicate_telegram_id(client, make_api_user):
    """POST /bot/users with duplicate telegram_id → 409 Conflict."""
    await make_api_user(telegram_id=777_000_222)

    r = await client.post(
        f"{API}/users",
        json={"telegram_id": 777_000_222, "username": "other"},
    )
    assert r.status_code == 409, r.text
    assert "telegram_id" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_add_bot_user_invalid_payload(client):
    """POST /bot/users with missing telegram_id → 422."""
    r = await client.post(f"{API}/users", json={"username": "x"})
    assert r.status_code == 422


# ===========================================================================
# /bot/users/{user_id} — patch / delete
# ===========================================================================

@pytest.mark.asyncio
async def test_update_bot_user_success(client, make_api_user):
    """PATCH /bot/users/{id} — update username + display_name + is_active."""
    u = await make_api_user()

    r = await client.patch(
        f"{API}/users/{u.id}",
        json={"username": "new_name", "display_name": "New Name", "is_active": False},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["username"] == "new_name"
    assert body["display_name"] == "New Name"
    assert body["is_active"] is False


@pytest.mark.asyncio
async def test_update_bot_user_partial(client, make_api_user):
    """PATCH /bot/users/{id} with only one field — only that field changes."""
    u = await make_api_user()

    r = await client.patch(f"{API}/users/{u.id}", json={"is_active": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_active"] is False
    assert body["username"] == "test_user"  # unchanged


@pytest.mark.asyncio
async def test_update_bot_user_404(client):
    """PATCH /bot/users/{nonexistent} → 404."""
    fake_id = uuid.uuid4()
    r = await client.patch(
        f"{API}/users/{fake_id}", json={"username": "x"}
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_update_bot_user_422_long_username(client, make_api_user):
    """PATCH /bot/users/{id} with username >100 chars → 422 (Field max_length)."""
    u = await make_api_user()
    too_long = "x" * 101

    r = await client.patch(
        f"{API}/users/{u.id}", json={"username": too_long}
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_delete_bot_user_success(client, db_session, make_api_user):
    """DELETE /bot/users/{id} — removes ApiUser and cleans up its UserSetting."""
    u = await make_api_user()
    user_setting_id = u.user_setting_id

    r = await client.delete(f"{API}/users/{u.id}")
    assert r.status_code == 200, r.text

    # Side effect: api_user gone, user_setting gone (defensive cleanup)
    n_users = len((await db_session.execute(select(ApiUser))).scalars().all())
    assert n_users == 0
    leftover = await db_session.get(UserSetting, user_setting_id)
    assert leftover is None


@pytest.mark.asyncio
async def test_delete_bot_user_404(client):
    """DELETE /bot/users/{nonexistent} → 404."""
    fake_id = uuid.uuid4()
    r = await client.delete(f"{API}/users/{fake_id}")
    assert r.status_code == 404, r.text


# ===========================================================================
# /bot/commands-log
# ===========================================================================

@pytest.mark.asyncio
async def test_commands_log_empty(client):
    """GET /bot/commands-log on empty DB → total=0."""
    r = await client.get(f"{API}/commands-log")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 0
    assert body["items"] == []
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.asyncio
async def test_commands_log_with_entries(client, make_command_log):
    """GET /bot/commands-log returns inserted entries."""
    cl1 = await make_command_log(command="/start")
    cl2 = await make_command_log(command="/help")

    r = await client.get(f"{API}/commands-log")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    commands = {item["command"] for item in body["items"]}
    assert commands == {"/start", "/help"}
    assert any(item["id"] == str(cl1.id) for item in body["items"])


@pytest.mark.asyncio
async def test_commands_log_filter_by_command(client, make_command_log):
    """GET /bot/commands-log?command=/help — filter branch."""
    await make_command_log(command="/start")
    cl_help = await make_command_log(command="/help")

    r = await client.get(f"{API}/commands-log", params={"command": "/help"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(cl_help.id)


@pytest.mark.asyncio
async def test_commands_log_pagination(client, make_command_log):
    """GET /bot/commands-log?limit=1&offset=0 — pagination branch."""
    for i in range(3):
        await make_command_log(command=f"/cmd{i}")

    r = await client.get(f"{API}/commands-log", params={"limit": 1, "offset": 0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 1
    assert body["limit"] == 1


# ===========================================================================
# /bot/test-connection — validation only (no live httpx call)
# ===========================================================================

@pytest.mark.asyncio
async def test_test_connection_short_token_422(client):
    """POST /bot/test-connection with token too short → 422 (Field min_length)."""
    r = await client.post(f"{API}/test-connection", json={"bot_token": "short"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_test_connection_request_schema_validation(client):
    """POST /bot/test-connection with missing bot_token → 422."""
    r = await client.post(f"{API}/test-connection", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_test_connection_returns_structured_response(client, monkeypatch):
    """POST /bot/test-connection — mock httpx to avoid real network, assert schema."""
    # Provide a token ≥10 chars to pass validation
    token = "1234567890:ABC-DEF_valid_token_mock"

    # Patch the global httpx.AsyncClient — the router does `import httpx` inside
    # the handler, which resolves to the same global httpx module.
    import httpx

    class FakeResponse:
        status_code = 401
        def json(self):
            return {"ok": False, "description": "Unauthorized"}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            return False
        async def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    r = await client.post(f"{API}/test-connection", json={"bot_token": token})
    assert r.status_code == 200, r.text
    body = r.json()
    # 401 branch → ok=False, error mentions token
    assert body["ok"] is False
    assert "hint" in body
    assert isinstance(body["latency_ms"], int)


@pytest.mark.asyncio
async def test_test_connection_network_error(client, monkeypatch):
    """POST /bot/test-connection — generic exception branch (timeout/connect)."""
    token = "1234567890:ABC-DEF_valid_token_mock"

    import httpx

    class ExplodingClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            return False
        async def get(self, url):
            raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(httpx, "AsyncClient", ExplodingClient)

    r = await client.post(f"{API}/test-connection", json={"bot_token": token})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert "Превышено время ожидания" in body["error"] or "Ошибка" in body["error"]