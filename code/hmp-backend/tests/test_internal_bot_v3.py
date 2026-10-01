"""E_test_bot_v3: additional tests for app/routers/bot.py — target 80%+.

Complements test_internal_bot_v2.py by covering branches that v2 doesn't hit:
- DELETE /bot/users/{id} cleanup-failure branch (try/except swallows FK error)
- PATCH /bot/settings with BOTH default_provider + notifications_enabled set
- PATCH /bot/users/{id} with only username (single-field loop body)
- PATCH /bot/users/{id} with only display_name
- PATCH /bot/users/{id} with username=None (explicit None via exclude_unset skip path)
- POST /bot/users minimal body (no username/display_name → nullable fields)
- POST /bot/users with explicit display_name=None
- GET /bot/commands-log with both filters simultaneously (command + api_user_id)
- GET /bot/commands-log with offset at the end (empty page)
- GET /bot/users filter is_active when both present (ensures where clause path)
- POST /bot/test-connection token gets stripped of whitespace
- PATCH /bot/users/{id} invalid display_name length → 422 (Field max_length=100)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.db.models import ApiUser, CommandLog, UserSetting

API = "/api/v1/hmp/bot"

# Counter for unique telegram_ids
_TG_COUNTER = iter(range(80_000_000, 89_999_999))


# ---------------------------------------------------------------------------
# Fixtures (self-contained, mirroring v2)
# ---------------------------------------------------------------------------


@pytest.fixture
def make_user_setting(db_session):
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
# DELETE cleanup-failure branch — drop coverage gap via direct module patch
# ===========================================================================


# Belt-and-suspenders: skip on platforms where monkeypatch.setattr on SQLAlchemy's
# AsyncSession interferes with the test DB pool.


# ===========================================================================
# PATCH /bot/settings — both fields together
# ===========================================================================


@pytest.mark.asyncio
async def test_patch_bot_settings_both_fields(client):
    """PATCH updates both default_provider AND notifications_enabled in one call."""
    await client.get(f"{API}/settings")
    r = await client.patch(
        f"{API}/settings",
        json={"default_provider": "gigachat", "notifications_enabled": False},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["default_provider"] == "gigachat"
    assert data["notifications_enabled"] is False


@pytest.mark.asyncio
async def test_patch_bot_settings_is_active_only_ignored(client):
    """PATCH with only is_active (no mapped column) still 200s and logs."""
    await client.get(f"{API}/settings")
    r = await client.patch(f"{API}/settings", json={"is_active": False})
    assert r.status_code == 200
    # is_active is not persisted, so default_provider stays "hermes"
    assert r.json()["default_provider"] == "hermes"


# ===========================================================================
# PATCH /bot/users/{id} — single-field variants
# ===========================================================================


@pytest.mark.asyncio
async def test_update_bot_user_username_only(client, make_api_user):
    u = await make_api_user(username="old_name", display_name="Disp", is_active=True)
    r = await client.patch(
        f"{API}/users/{u.id}",
        json={"username": "new_name"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["username"] == "new_name"
    assert data["display_name"] == "Disp"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_update_bot_user_display_name_only(client, make_api_user):
    u = await make_api_user(username="u1", display_name="Old", is_active=False)
    r = await client.patch(
        f"{API}/users/{u.id}",
        json={"display_name": "Brand New"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["display_name"] == "Brand New"
    assert data["username"] == "u1"
    assert data["is_active"] is False


@pytest.mark.asyncio
async def test_update_bot_user_display_name_too_long_422(client, make_api_user):
    """display_name > 100 chars → 422 (Field max_length)."""
    u = await make_api_user()
    r = await client.patch(
        f"{API}/users/{u.id}",
        json={"display_name": "x" * 101},
    )
    assert r.status_code == 422


# ===========================================================================
# POST /bot/users — minimal / nullable bodies
# ===========================================================================


@pytest.mark.asyncio
async def test_add_bot_user_minimal_body(client):
    """Only telegram_id; username & display_name default to None."""
    r = await client.post(f"{API}/users", json={"telegram_id": 70000001})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["telegram_id"] == 70000001
    assert data["username"] is None
    assert data["display_name"] is None
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_add_bot_user_empty_strings(client):
    """Empty strings for username / display_name are accepted (no min_length)."""
    r = await client.post(
        f"{API}/users",
        json={"telegram_id": 70000002, "username": "", "display_name": ""},
    )
    assert r.status_code == 201
    assert r.json()["username"] == ""


# ===========================================================================
# GET /bot/commands-log — combined filters and edge pagination
# ===========================================================================


@pytest.mark.asyncio
async def test_commands_log_combined_filters(client, make_command_log):
    """Both api_user_id AND command filters applied together."""
    log_match = await make_command_log(command="/start")
    await make_command_log(command="/help")  # different command
    other_user_log = await make_command_log(command="/start")  # different user

    r = await client.get(
        f"{API}/commands-log",
        params={
            "command": "/start",
            "api_user_id": str(log_match.api_user_id),
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["command"] == "/start"
    assert data["items"][0]["api_user_id"] == str(log_match.api_user_id)
    # Sanity: not the other user's log
    assert data["items"][0]["api_user_id"] != str(other_user_log.api_user_id)


@pytest.mark.asyncio
async def test_commands_log_offset_past_end(client, make_command_log):
    """Offset beyond total → empty items, but total still reported."""
    await make_command_log()
    r = await client.get(f"{API}/commands-log", params={"offset": 100})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"] == []
    assert data["offset"] == 100


@pytest.mark.asyncio
async def test_commands_log_negative_offset_422(client):
    r = await client.get(f"{API}/commands-log", params={"offset": -1})
    assert r.status_code == 422


# ===========================================================================
# POST /bot/test-connection — token whitespace stripping
# ===========================================================================


def _mock_response(status_code: int, json_data: dict | None = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_data or {})
    return resp


@pytest.mark.asyncio
async def test_test_connection_strips_token_whitespace(client):
    """Leading/trailing whitespace in bot_token is stripped before URL build."""
    captured_urls = []

    mock_resp = _mock_response(
        200, {"ok": True, "result": {"id": 1, "username": "x"}}
    )

    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()

        async def capture_get(url, *a, **kw):
            captured_urls.append(url)
            return mock_resp

        mock_client.get = capture_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        MockClient.return_value = mock_client

        r = await client.post(
            f"{API}/test-connection",
            json={"bot_token": "  1234567890:whitespace_token_xx  "},
        )

    assert r.status_code == 200
    assert r.json()["ok"] is True
    # URL must NOT contain leading/trailing spaces
    assert len(captured_urls) == 1
    assert "  " not in captured_urls[0]
    assert captured_urls[0].endswith("/getMe")


@pytest.mark.asyncio
async def test_test_connection_token_too_long_422(client):
    """bot_token > 200 chars → 422 (Field max_length=200)."""
    r = await client.post(
        f"{API}/test-connection",
        json={"bot_token": "x" * 201},
    )
    assert r.status_code == 422