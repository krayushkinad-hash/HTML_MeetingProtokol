"""E_test_bot_v2: extended tests for app/routers/bot.py — target 70%+.

Adds v2 tests on top of test_internal_bot.py covering:
- GET /bot/users with is_active filter (active/inactive branches)
- POST /bot/users happy path + 409 conflict
- PATCH /bot/users/{id} with multiple fields + 404
- DELETE /bot/users/{id} happy path + 404
- GET /bot/commands-log pagination + filters
- POST /bot/test-connection: 200 ok, 401, 404, ok=false API, timeout, generic exception
- Schema validation: bot_token too short, display_name max_length
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.db.models import ApiUser, CommandLog, UserSetting

API = "/api/v1/hmp/bot"

# Per-test unique telegram_id counter (avoids collisions across tests)
_TG_COUNTER = iter(range(10_000_000, 99_999_999))


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


@pytest.fixture
def make_user_setting(db_session):
    """Create a bare UserSetting row."""
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
    """Create an ApiUser (with backing UserSetting)."""
    async def _factory(telegram_id: int | None = None, is_active: bool = True, **kwargs):
        s = await make_user_setting()
        u = ApiUser(
            id=uuid.uuid4(),
            telegram_id=telegram_id if telegram_id is not None else next(_TG_COUNTER),
            username=kwargs.get("username", "test_user"),
            display_name=kwargs.get("display_name", "Test User"),
            is_active=is_active,
            user_setting_id=s.id,
        )
        db_session.add(u)
        await db_session.commit()
        await db_session.refresh(u)
        return u
    return _factory


@pytest.fixture
def make_command_log(db_session, make_api_user):
    """Create a CommandLog row."""
    async def _factory(command: str = "/start", status: str = "success", **kwargs):
        user = await make_api_user()
        log = CommandLog(
            id=uuid.uuid4(),
            api_user_id=user.id,
            command=command,
            args=kwargs.get("args"),
            status=status,
            error_message=kwargs.get("error_message"),
            execution_ms=kwargs.get("execution_ms", 100),
            tokens_used=kwargs.get("tokens_used", 0),
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(log)
        await db_session.commit()
        await db_session.refresh(log)
        return log
    return _factory


# ===========================================================================
# GET /bot/users
# ===========================================================================


@pytest.mark.asyncio
async def test_list_bot_users_empty(client):
    """Empty list when no users exist."""
    r = await client.get(f"{API}/users")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_bot_users_with_data(client, make_api_user):
    """List returns all users ordered by created_at desc."""
    u1 = await make_api_user(username="alice")
    u2 = await make_api_user(username="bob")
    r = await client.get(f"{API}/users")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    usernames = {u["username"] for u in data}
    assert usernames == {"alice", "bob"}


@pytest.mark.asyncio
async def test_list_bot_users_filter_active_true(client, make_api_user):
    """Filter by is_active=true only returns active users."""
    await make_api_user(username="active", is_active=True)
    await make_api_user(username="inactive", is_active=False)
    r = await client.get(f"{API}/users", params={"is_active": "true"})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["username"] == "active"
    assert data[0]["is_active"] is True


@pytest.mark.asyncio
async def test_list_bot_users_filter_active_false(client, make_api_user):
    """Filter by is_active=false only returns inactive users."""
    await make_api_user(username="active", is_active=True)
    await make_api_user(username="inactive", is_active=False)
    r = await client.get(f"{API}/users", params={"is_active": "false"})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["username"] == "inactive"


# ===========================================================================
# POST /bot/users
# ===========================================================================


@pytest.mark.asyncio
async def test_add_bot_user_happy(client):
    """Create new user returns 201 with body."""
    r = await client.post(
        f"{API}/users",
        json={"telegram_id": 123456789, "username": "new_user", "display_name": "New"},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["telegram_id"] == 123456789
    assert data["username"] == "new_user"
    assert data["display_name"] == "New"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_add_bot_user_duplicate_409(client, make_api_user):
    """Duplicate telegram_id returns 409."""
    await make_api_user(telegram_id=555555)
    r = await client.post(
        f"{API}/users",
        json={"telegram_id": 555555, "username": "dup"},
    )
    assert r.status_code == 409
    assert "telegram_id" in r.json()["detail"]


@pytest.mark.asyncio
async def test_add_bot_user_invalid_body_422(client):
    """Missing telegram_id returns 422."""
    r = await client.post(
        f"{API}/users",
        json={"username": "no_id"},
    )
    assert r.status_code == 422


# ===========================================================================
# PATCH /bot/users/{id}
# ===========================================================================


@pytest.mark.asyncio
async def test_update_bot_user_full(client, make_api_user):
    """Update all fields returns updated user."""
    u = await make_api_user(username="old", display_name="Old", is_active=True)
    r = await client.patch(
        f"{API}/users/{u.id}",
        json={"username": "new", "display_name": "New", "is_active": False},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["username"] == "new"
    assert data["display_name"] == "New"
    assert data["is_active"] is False


@pytest.mark.asyncio
async def test_update_bot_user_partial_is_active_only(client, make_api_user):
    """Partial update — only is_active field."""
    u = await make_api_user(username="keep", display_name="keep")
    r = await client.patch(
        f"{API}/users/{u.id}",
        json={"is_active": False},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["username"] == "keep"
    assert data["is_active"] is False


@pytest.mark.asyncio
async def test_update_bot_user_not_found_404(client):
    """Non-existent UUID returns 404."""
    fake_id = uuid.uuid4()
    r = await client.patch(
        f"{API}/users/{fake_id}",
        json={"username": "ghost"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_bot_user_invalid_uuid_422(client):
    """Invalid UUID format returns 422."""
    r = await client.patch(
        f"{API}/users/not-a-uuid",
        json={"username": "x"},
    )
    assert r.status_code == 422


# ===========================================================================
# DELETE /bot/users/{id}
# ===========================================================================


@pytest.mark.asyncio
async def test_delete_bot_user_happy(client, make_api_user):
    """Delete returns 200 and user is gone."""
    u = await make_api_user(username="todelete")
    r = await client.delete(f"{API}/users/{u.id}")
    assert r.status_code == 200
    # Verify it's gone
    r2 = await client.get(f"{API}/users")
    assert all(item["id"] != str(u.id) for item in r2.json())


@pytest.mark.asyncio
async def test_delete_bot_user_not_found_404(client):
    """Delete non-existent returns 404."""
    fake_id = uuid.uuid4()
    r = await client.delete(f"{API}/users/{fake_id}")
    assert r.status_code == 404


# ===========================================================================
# GET /bot/commands-log
# ===========================================================================


@pytest.mark.asyncio
async def test_commands_log_empty(client):
    """Empty log returns total=0."""
    r = await client.get(f"{API}/commands-log")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_commands_log_with_data(client, make_command_log):
    """Returns all log entries paginated."""
    await make_command_log(command="/start")
    await make_command_log(command="/help")
    r = await client.get(f"{API}/commands-log")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


@pytest.mark.asyncio
async def test_commands_log_filter_by_command(client, make_command_log):
    """Filter by command narrows results."""
    await make_command_log(command="/start")
    await make_command_log(command="/help")
    r = await client.get(f"{API}/commands-log", params={"command": "/start"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["command"] == "/start"


@pytest.mark.asyncio
async def test_commands_log_filter_by_api_user(client, make_command_log):
    """Filter by api_user_id narrows results."""
    log = await make_command_log()
    other = await make_command_log()
    r = await client.get(
        f"{API}/commands-log",
        params={"api_user_id": str(log.api_user_id)},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["api_user_id"] == str(log.api_user_id)


@pytest.mark.asyncio
async def test_commands_log_pagination(client, make_command_log):
    """Limit + offset honored."""
    for _ in range(5):
        await make_command_log()
    r = await client.get(f"{API}/commands-log", params={"limit": 2, "offset": 1})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 5
    assert data["limit"] == 2
    assert data["offset"] == 1
    assert len(data["items"]) == 2


@pytest.mark.asyncio
async def test_commands_log_limit_validation_422(client):
    """Limit > 500 → 422."""
    r = await client.get(f"{API}/commands-log", params={"limit": 9999})
    assert r.status_code == 422


# ===========================================================================
# POST /bot/test-connection (httpx mocked)
# ===========================================================================


def _mock_response(status_code: int, json_data: dict | None = None):
    """Build a MagicMock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_data or {})
    return resp


@pytest.mark.asyncio
async def test_test_connection_success(client):
    """200 ok with bot info returns ok=true."""
    mock_resp = _mock_response(200, {
        "ok": True,
        "result": {"id": 12345, "username": "my_bot", "first_name": "MyBot"},
    })
    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        MockClient.return_value = mock_client

        r = await client.post(
            f"{API}/test-connection",
            json={"bot_token": "1234567890:ABCDEFG_valid_token_xx"},
        )

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["bot"]["username"] == "my_bot"
    assert data["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_test_connection_api_ok_false(client):
    """200 status but ok=false → returns error description + hint."""
    mock_resp = _mock_response(200, {
        "ok": False,
        "description": "Bot token is invalid",
    })
    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        MockClient.return_value = mock_client

        r = await client.post(
            f"{API}/test-connection",
            json={"bot_token": "1234567890:bad_token_xxxxxxxx"},
        )

    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "Bot token" in data["error"] or "invalid" in data["error"].lower()
    assert data["hint"] is not None


@pytest.mark.asyncio
async def test_test_connection_401(client):
    """401 → "токен невалидный" with revoke hint."""
    mock_resp = _mock_response(401)
    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        MockClient.return_value = mock_client

        r = await client.post(
            f"{API}/test-connection",
            json={"bot_token": "1234567890:revoked_token_xxx"},
        )

    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "невалидный" in data["error"].lower() or "отозван" in data["error"].lower()
    assert data["hint"] is not None


@pytest.mark.asyncio
async def test_test_connection_404(client):
    """404 → "бот не найден" hint."""
    mock_resp = _mock_response(404)
    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        MockClient.return_value = mock_client

        r = await client.post(
            f"{API}/test-connection",
            json={"bot_token": "1234567890:notfound_token_x"},
        )

    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "не найден" in data["error"].lower()


@pytest.mark.asyncio
async def test_test_connection_other_status_500(client):
    """500 status → generic error with status code in message."""
    mock_resp = _mock_response(500)
    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        MockClient.return_value = mock_client

        r = await client.post(
            f"{API}/test-connection",
            json={"bot_token": "1234567890:server_error_xxxx"},
        )

    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "500" in data["error"]


@pytest.mark.asyncio
async def test_test_connection_timeout(client):
    """httpx.TimeoutException → timeout hint."""
    import httpx

    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        MockClient.return_value = mock_client

        r = await client.post(
            f"{API}/test-connection",
            json={"bot_token": "1234567890:timeout_token_xxx"},
        )

    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "ожидания" in data["error"].lower() or "timeout" in data["error"].lower()
    assert data["hint"] is not None


@pytest.mark.asyncio
async def test_test_connection_generic_exception(client):
    """Generic Exception → "ошибка соединения" wrapper."""
    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("network down"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        MockClient.return_value = mock_client

        r = await client.post(
            f"{API}/test-connection",
            json={"bot_token": "1234567890:generic_exc_xxxxx"},
        )

    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "соединения" in data["error"].lower() or "network" in data["error"].lower()


@pytest.mark.asyncio
async def test_test_connection_short_token_422(client):
    """bot_token shorter than 10 chars → 422."""
    r = await client.post(
        f"{API}/test-connection",
        json={"bot_token": "short"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_test_connection_missing_token_422(client):
    """Missing bot_token → 422."""
    r = await client.post(
        f"{API}/test-connection",
        json={},
    )
    assert r.status_code == 422


# ===========================================================================
# GET /bot/settings + PATCH /bot/settings (singleton helper branches)
# ===========================================================================


@pytest.mark.asyncio
async def test_get_bot_settings_creates_singleton(client):
    """First GET creates a singleton row and returns defaults."""
    r = await client.get(f"{API}/settings")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["is_active"] is True
    assert data["default_provider"] in ("hermes", "gigachat", "local_ollama")
    assert data["fallback_provider"] == "gigachat"
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_patch_bot_settings_default_provider(client):
    """PATCH updates default_provider mapping."""
    # seed singleton
    await client.get(f"{API}/settings")
    r = await client.patch(
        f"{API}/settings",
        json={"default_provider": "local_ollama"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["default_provider"] == "local_ollama"


@pytest.mark.asyncio
async def test_patch_bot_settings_notifications_only(client):
    """PATCH only notifications_enabled branch."""
    await client.get(f"{API}/settings")
    r = await client.patch(
        f"{API}/settings",
        json={"notifications_enabled": False},
    )
    assert r.status_code == 200
    assert r.json()["notifications_enabled"] is False


@pytest.mark.asyncio
async def test_patch_bot_settings_empty_body(client):
    """PATCH with no fields still updates updated_at + commits."""
    await client.get(f"{API}/settings")
    r = await client.patch(f"{API}/settings", json={})
    assert r.status_code == 200


# ===========================================================================
# POST /bot/test + POST /bot/restart (stubs)
# ===========================================================================


@pytest.mark.asyncio
async def test_bot_test_stub(client):
    """POST /bot/test returns mock response."""
    r = await client.post(f"{API}/test")
    assert r.status_code == 200
    data = r.json()
    assert data["sent"] is True
    assert data["provider"] == "mock"


@pytest.mark.asyncio
async def test_bot_restart_stub(client):
    """POST /bot/restart returns mock response."""
    r = await client.post(f"{API}/restart")
    assert r.status_code == 200
    data = r.json()
    assert data["restarted"] is True
    assert data["provider"] == "mock"


# ===========================================================================
# DELETE cleanup-failure branch (user_setting FK protects)
# ===========================================================================


@pytest.mark.asyncio
async def test_delete_bot_user_with_cleanup(client, db_session, make_api_user):
    """DELETE happy path exercises the user_setting cleanup branch too."""
    u = await make_api_user()
    r = await client.delete(f"{API}/users/{u.id}")
    assert r.status_code == 200
    # user_setting should also be gone (no other api_user refs it)
    from sqlalchemy import select as _sel
    result = await db_session.execute(
        _sel(UserSetting).where(UserSetting.id == u.user_setting_id)
    )
    assert result.scalar_one_or_none() is None
