"""User settings (US-026, US-036, US-054..066, API §12)."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import get_logger
from app.db.models import UserSetting
from app.db.session import get_db

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas — расширенные (US-054..066)
# ---------------------------------------------------------------------------

UserSettingProvider = Literal["local_ollama", "gigachat", "hermes"]
UserSettingWhisper = Literal["tiny", "base", "small", "medium", "large-v3"]
UserSettingTheme = Literal["light", "dark", "auto"]


class UserSettingUpdate(BaseModel):
    """Partial update payload for PATCH /user-setting."""
    llm_provider: UserSettingProvider | None = None
    llm_model: str | None = Field(None, max_length=100)
    whisper_model: UserSettingWhisper | None = None
    whisper_prompt: str | None = None
    theme: UserSettingTheme | None = None
    notifications_enabled: bool | None = None

    # Extended fields (US-054..066)
    user_name: str | None = Field(None, max_length=100)
    email: str | None = Field(None, max_length=255)
    timezone: str | None = Field(None, max_length=50)
    default_language: str | None = Field(None, max_length=20)
    use_gpu: bool | None = None
    default_provider: UserSettingProvider | None = None
    fallback_provider: UserSettingProvider | None = None
    api_keys: str | None = None
    telegram_bot_token: str | None = None
    telegram_webhook_url: str | None = None
    telegram_allowed_users: str | None = None


class UserSettingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    llm_provider: str
    llm_model: str | None
    whisper_model: str
    whisper_prompt: str | None
    theme: str
    hotkey_show_search: str
    notifications_enabled: bool
    updated_at: datetime

    # Extended fields (US-054..066)
    user_name: str | None = None
    email: str | None = None
    timezone: str | None = None
    default_language: str | None = None
    use_gpu: bool | None = None
    default_provider: str | None = None
    fallback_provider: str | None = None
    api_keys: str | None = None
    telegram_bot_token: str | None = None
    telegram_webhook_url: str | None = None
    telegram_allowed_users: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def get_or_create_singleton_user_setting(db: AsyncSession) -> UserSetting:
    """MVP single-user: the first user_setting row is the singleton."""
    result = await db.execute(select(UserSetting).limit(1))
    setting = result.scalar_one_or_none()
    if setting is None:
        setting = UserSetting()
        db.add(setting)
        await db.commit()
        await db.refresh(setting)
        logger.info("user_setting_created")
    return setting


def _to_response(setting: UserSetting) -> UserSettingResponse:
    """Convert ORM → response."""
    return UserSettingResponse(
        id=str(setting.id),
        llm_provider=setting.llm_provider,
        llm_model=setting.llm_model,
        whisper_model=setting.whisper_model,
        whisper_prompt=setting.whisper_prompt,
        theme=setting.theme,
        hotkey_show_search=setting.hotkey_show_search,
        notifications_enabled=setting.notifications_enabled,
        updated_at=setting.updated_at,
        user_name=setting.user_name,
        email=setting.email,
        timezone=setting.timezone,
        default_language=setting.default_language,
        use_gpu=setting.use_gpu,
        default_provider=setting.default_provider,
        fallback_provider=setting.fallback_provider,
        api_keys=setting.api_keys,
        telegram_bot_token=setting.telegram_bot_token,
        telegram_webhook_url=setting.telegram_webhook_url,
        telegram_allowed_users=setting.telegram_allowed_users,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/user-setting",
    response_model=UserSettingResponse,
    summary="Get current user settings (singleton)",
)
async def get_user_setting(
    db: AsyncSession = Depends(get_db),
) -> UserSettingResponse:
    """Return the singleton user setting, creating it on first call (US-026)."""
    setting = await get_or_create_singleton_user_setting(db)
    return _to_response(setting)


@router.patch(
    "/user-setting",
    response_model=UserSettingResponse,
    summary="Update user settings (partial)",
)
async def update_user_setting(
    body: UserSettingUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserSettingResponse:
    """Partial update of all settings fields (US-054..066)."""
    setting = await get_or_create_singleton_user_setting(db)
    correlation_id = getattr(request.state, "correlation_id", None)

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if hasattr(setting, field):
            setattr(setting, field, value)
        else:
            logger.warning(
                "unknown_user_setting_field",
                field=field,
                correlation_id=correlation_id,
            )

    setting.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(setting)

    logger.info(
        "user_setting_updated",
        fields=list(update_data.keys()),
        correlation_id=correlation_id,
    )

    return _to_response(setting)
