"""Telegram bot endpoints (US-041, US-042, US-043, US-037, US-038, API §16).

Endpoints:
    GET   /bot/settings              — get bot settings (singleton)
    PATCH /bot/settings              — update bot settings
    POST  /bot/test                  — send test message (stub)
    POST  /bot/restart               — restart bot (stub)
    GET   /bot/users                 — whitelist of api_user rows
    POST  /bot/users                 — add a user (creates user_setting + api_user)
    PATCH /bot/users/{id}            — update user (username, display_name, is_active)
    DELETE /bot/users/{id}           — remove user from whitelist
    GET   /bot/commands-log          — paginated log of bot commands

Bot settings are persisted as a singleton row in `user_setting` (table 1).
This avoids a separate `bot_settings` table while keeping the contract
clean — the first row is canonical.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status, Response
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import get_logger
from app.db.models import ApiUser, CommandLog, UserSetting
from app.db.session import get_db
from app.schemas import BotSettingsUpdate, BotUserCreate

logger = get_logger(__name__)
router = APIRouter()


# ============================================================================
# Response schemas (local — keep router self-contained)
# ============================================================================


class BotSettingsResponse(BaseModel):
    """Bot settings (singleton)."""

    is_active: bool
    default_provider: Literal["hermes", "gigachat", "local_ollama"]
    fallback_provider: Literal["hermes", "gigachat", "local_ollama"]
    notifications_enabled: bool
    updated_at: datetime


class BotUserResponse(BaseModel):
    """API user / whitelist entry."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    telegram_id: int
    username: str | None
    display_name: str | None
    is_active: bool
    last_active_at: datetime | None
    created_at: datetime


class BotUserUpdate(BaseModel):
    """Update fields for /bot/users/{id}."""

    username: str | None = Field(None, max_length=100)
    display_name: str | None = Field(None, max_length=100)
    is_active: bool | None = None


class CommandLogResponse(BaseModel):
    """Single command-log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    api_user_id: uuid.UUID
    command: str
    args: str | None
    status: str
    error_message: str | None
    execution_ms: int | None
    tokens_used: int | None
    created_at: datetime


# ============================================================================
# Helpers
# ============================================================================


async def _get_or_create_singleton_user_setting(
    db: AsyncSession,
) -> UserSetting:
    """Return the singleton user_setting row (create if missing)."""
    query = select(UserSetting).order_by(UserSetting.updated_at.asc()).limit(1)
    result = await db.execute(query)
    setting = result.scalar_one_or_none()
    if setting is None:
        setting = UserSetting(
            id=uuid.uuid4(),
            llm_provider="hermes",
            whisper_model="large-v3",
            theme="auto",
        )
        db.add(setting)
        await db.commit()
        await db.refresh(setting)
        logger.info("bot_singleton_user_setting_created", id=str(setting.id))
    return setting


def _to_settings_response(s: UserSetting) -> BotSettingsResponse:
    """ORM → BotSettingsResponse.

    `is_active` is a derived flag (we treat the singleton as 'active' if
    updated within 24h, or always True for simplicity — here: always True
    unless explicitly disabled via settings file). Stored implicitly as
    `notifications_enabled`. For a richer contract, add a column in a
    future migration.
    """
    return BotSettingsResponse(
        is_active=True,
        default_provider=s.llm_provider,  # type: ignore[arg-type]
        fallback_provider="gigachat",     # default fallback
        notifications_enabled=s.notifications_enabled,
        updated_at=s.updated_at,
    )


# ============================================================================
# GET /bot/settings
# ============================================================================


@router.get(
    "/bot/settings",
    response_model=BotSettingsResponse,
    summary="Get bot settings (singleton)",
)
async def get_bot_settings(
    db: AsyncSession = Depends(get_db),
) -> BotSettingsResponse:
    """US-041 — fetch current bot configuration."""
    setting = await _get_or_create_singleton_user_setting(db)
    return _to_settings_response(setting)


# ============================================================================
# PATCH /bot/settings
# ============================================================================


@router.patch(
    "/bot/settings",
    response_model=BotSettingsResponse,
    summary="Update bot settings",
)
async def update_bot_settings(
    body: BotSettingsUpdate,
    db: AsyncSession = Depends(get_db),
) -> BotSettingsResponse:
    """US-041 — partially update bot configuration.

    Maps `default_provider` → `llm_provider`. `is_active` is acknowledged
    (logged) but not persisted (no dedicated column).
    """
    setting = await _get_or_create_singleton_user_setting(db)

    update_data = body.model_dump(exclude_unset=True)
    if "default_provider" in update_data and update_data["default_provider"] is not None:
        # Map schema value → ORM enum (literal values are identical strings)
        setting.llm_provider = update_data["default_provider"]
    if "notifications_enabled" in update_data and update_data["notifications_enabled"] is not None:
        setting.notifications_enabled = update_data["notifications_enabled"]

    setting.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(setting)

    logger.info(
        "bot_settings_updated",
        fields=list(update_data.keys()),
        default_provider=setting.llm_provider,
        notifications_enabled=setting.notifications_enabled,
    )
    return _to_settings_response(setting)


# ============================================================================
# POST /bot/test — stub
# ============================================================================


@router.post(
    "/bot/test",
    summary="Send a test message (MOCK)",
)
async def test_bot() -> dict:
    """US-042 — send a test notification to the bot owner. Stub for now."""
    logger.info("bot_test_message_sent")
    return {
        "sent": True,
        "provider": "mock",
        "message": "Test message (MOCK — Telegram bot not connected)",
    }


# ============================================================================
# POST /bot/restart — stub
# ============================================================================


@router.post(
    "/bot/restart",
    summary="Restart bot (MOCK)",
)
async def restart_bot() -> dict:
    """US-042 — restart the bot process. Stub for now."""
    logger.info("bot_restart_requested")
    return {
        "restarted": True,
        "provider": "mock",
        "message": "Bot restart requested (MOCK — supervisor not connected)",
    }


# ============================================================================
# GET /bot/users — list whitelist
# ============================================================================


@router.get(
    "/bot/users",
    response_model=list[BotUserResponse],
    summary="List whitelist users",
)
async def list_bot_users(
    is_active: bool | None = Query(None, description="Filter by active status"),
    db: AsyncSession = Depends(get_db),
) -> list[BotUserResponse]:
    """US-042 — return whitelist of Telegram users allowed to use the bot."""
    query = select(ApiUser).order_by(ApiUser.created_at.desc())
    if is_active is not None:
        query = query.where(ApiUser.is_active == is_active)
    result = await db.execute(query)
    users = result.scalars().all()
    return [BotUserResponse.model_validate(u) for u in users]


# ============================================================================
# POST /bot/users — add user
# ============================================================================


@router.post(
    "/bot/users",
    response_model=BotUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add user to whitelist",
)
async def add_bot_user(
    body: BotUserCreate,
    db: AsyncSession = Depends(get_db),
) -> BotUserResponse:
    """US-042 — register a Telegram user. Auto-creates a user_setting row."""
    # Ensure no duplicate telegram_id
    query = select(ApiUser).where(ApiUser.telegram_id == body.telegram_id)
    existing = (await db.execute(query)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с таким telegram_id уже зарегистрирован",
        )

    # Each api_user needs its own user_setting (FK NOT NULL RESTRICT)
    user_setting = UserSetting(
        id=uuid.uuid4(),
        llm_provider="hermes",
        whisper_model="large-v3",
        theme="auto",
    )
    db.add(user_setting)
    await db.flush()  # populate user_setting.id

    api_user = ApiUser(
        id=uuid.uuid4(),
        telegram_id=body.telegram_id,
        username=body.username,
        display_name=body.display_name,
        is_active=True,
        user_setting_id=user_setting.id,
    )
    db.add(api_user)
    await db.commit()
    await db.refresh(api_user)

    logger.info(
        "bot_user_added",
        user_id=str(api_user.id),
        telegram_id=api_user.telegram_id,
    )
    return BotUserResponse.model_validate(api_user)


# ============================================================================
# PATCH /bot/users/{id}
# ============================================================================


@router.patch(
    "/bot/users/{user_id}",
    response_model=BotUserResponse,
    summary="Update whitelist user",
)
async def update_bot_user(
    user_id: uuid.UUID,
    body: BotUserUpdate,
    db: AsyncSession = Depends(get_db),
) -> BotUserResponse:
    """US-042 — update username / display_name / is_active."""
    api_user = await db.get(ApiUser, user_id)
    if not api_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        )

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(api_user, field, value)
    await db.commit()
    await db.refresh(api_user)

    logger.info(
        "bot_user_updated",
        user_id=str(user_id),
        fields=list(update_data.keys()),
    )
    return BotUserResponse.model_validate(api_user)


# ============================================================================
# DELETE /bot/users/{id}
# ============================================================================


@router.delete(
    "/bot/users/{user_id}",
    status_code=status.HTTP_200_OK,
    summary="Remove user from whitelist",
)
async def delete_bot_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """US-042 — remove a user from whitelist (deletes api_user + user_setting)."""
    api_user = await db.get(ApiUser, user_id)
    if not api_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        )

    user_setting_id = api_user.user_setting_id

    await db.delete(api_user)
    await db.commit()

    # Clean up the associated user_setting row if no other api_user references it
    # (RESTRICT FK would prevent the delete above if any other row references it,
    # so this is just a defensive cleanup).
    user_setting = await db.get(UserSetting, user_setting_id)
    if user_setting:
        try:
            await db.delete(user_setting)
            await db.commit()
        except Exception as e:
            logger.warning(
                "bot_user_setting_cleanup_failed",
                user_setting_id=str(user_setting_id),
                error=str(e),
            )

    logger.info("bot_user_deleted", user_id=str(user_id))
    return None


# ============================================================================
# GET /bot/commands-log
# ============================================================================


@router.get(
    "/bot/commands-log",
    response_model=dict,
    summary="Get bot command log (paginated)",
)
async def get_commands_log(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    api_user_id: uuid.UUID | None = Query(None, description="Filter by user"),
    command: str | None = Query(None, description="Filter by command name"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """US-037/038 — paginated command execution log.

    Returns: { total, limit, offset, items: [CommandLogResponse, ...] }
    """
    from sqlalchemy import func

    query = select(CommandLog).order_by(CommandLog.created_at.desc())
    count_query = select(func.count()).select_from(CommandLog)

    if api_user_id is not None:
        query = query.where(CommandLog.api_user_id == api_user_id)
        count_query = count_query.where(CommandLog.api_user_id == api_user_id)
    if command is not None:
        query = query.where(CommandLog.command == command)
        count_query = count_query.where(CommandLog.command == command)

    total = (await db.execute(count_query)).scalar() or 0

    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    rows = result.scalars().all()
    items = [CommandLogResponse.model_validate(r) for r in rows]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


# ============================================================================
# POST /bot/test-connection (US-067)
# ============================================================================


class BotTestConnectionRequest(BaseModel):
    """Request body for bot test connection."""
    bot_token: str = Field(..., min_length=10, max_length=200)


class BotTestConnectionResponse(BaseModel):
    """Response for bot test connection."""
    ok: bool
    bot: dict | None = None
    error: str | None = None
    latency_ms: int
    hint: str | None = None


@router.post(
    "/bot/test-connection",
    response_model=BotTestConnectionResponse,
    summary="Test Telegram bot connection (US-067)",
)
async def test_bot_connection(
    body: BotTestConnectionRequest,
) -> BotTestConnectionResponse:
    """Test if bot token is valid via Telegram getMe API (US-067).

    Does NOT save token to DB. Uses httpx with 10s timeout.
    """
    import hashlib
    import time
    import httpx

    bot_token = body.bot_token.strip()

    # Telegram API URL
    url = f"https://api.telegram.org/bot{bot_token}/getMe"
    start_time = time.time()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)

        latency_ms = int((time.time() - start_time) * 1000)

        if response.status_code == 200:
            data = response.json()
            if data.get("ok"):
                bot_info = data.get("result", {})
                logger.info(
                    "bot_test_connection_success",
                    bot_id=bot_info.get("id"),
                    bot_username=bot_info.get("username"),
                    latency_ms=latency_ms,
                )
                return BotTestConnectionResponse(
                    ok=True,
                    bot=bot_info,
                    latency_ms=latency_ms,
                )
            else:
                error_msg = data.get("description", "Unknown Telegram API error")
                logger.warning(
                    "bot_test_connection_api_error",
                    error=error_msg,
                    latency_ms=latency_ms,
                )
                return BotTestConnectionResponse(
                    ok=False,
                    error=error_msg,
                    latency_ms=latency_ms,
                    hint="Проверьте токен в @BotFather. Формат: 1234567890:ABC-DEF...",
                )
        elif response.status_code == 401:
            return BotTestConnectionResponse(
                ok=False,
                error="Токен невалидный или отозван",
                latency_ms=latency_ms,
                hint="Откройте @BotFather → /revoke → /token для нового токена",
            )
        elif response.status_code == 404:
            return BotTestConnectionResponse(
                ok=False,
                error="Бот с таким токеном не найден",
                latency_ms=latency_ms,
                hint="Проверьте правильность токена",
            )
        else:
            return BotTestConnectionResponse(
                ok=False,
                error=f"Telegram API вернул {response.status_code}",
                latency_ms=latency_ms,
            )
    except httpx.TimeoutException:
        latency_ms = int((time.time() - start_time) * 1000)
        logger.warning("bot_test_connection_timeout", latency_ms=latency_ms)
        return BotTestConnectionResponse(
            ok=False,
            error="Превышено время ожидания (10 секунд)",
            latency_ms=latency_ms,
            hint="Telegram недоступен. Проверьте интернет или VPN.",
        )
    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        logger.error("bot_test_connection_failed", error=str(e), latency_ms=latency_ms)
        return BotTestConnectionResponse(
            ok=False,
            error=f"Ошибка соединения: {str(e)[:200]}",
            latency_ms=latency_ms,
        )
