from typing import Literal
from datetime import datetime, timezone
from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, ConfigDict, Field

from app.db.session import get_db
from app.db.models import UserSetting
from app.core.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()

# -----------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------}
UserSettingProvider = Literal["local_ollama", "gigachat", "hermes"]
UserSettingWhisper = Literal["tiny", "base", "small", "medium", "large-v3"]
UserSettingTheme = Literal["light", "dark", "auto"]


# -----------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------}
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

    # E257: remote Whisper settings (US-089)
    whisper_remote_enabled: bool | None = None
    whisper_remote_url: str | None = Field(None, max_length=255)
    whisper_remote_path: str | None = Field(None, max_length=100)


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

    # E257: remote Whisper settings (US-089)
    whisper_remote_enabled: bool = False
    whisper_remote_url: str | None = None
    whisper_remote_path: str | None = "/transcribe"


# -----------------------------------------------------------------------
# ORM → API conversion
# -----------------------------------------------------------------------}
def _to_response(setting: UserSetting) -> UserSettingResponse:
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
        whisper_remote_enabled=bool(getattr(setting, "whisper_remote_enabled", False)),
        whisper_remote_url=getattr(setting, "whisper_remote_url", None),
        whisper_remote_path=getattr(setting, "whisper_remote_path", None) or "/transcribe",
    )


# -----------------------------------------------------------------------
# Singleton helpers
# -----------------------------------------------------------------------}
async def get_or_create_singleton_user_setting(db: AsyncSession) -> UserSetting:
    from sqlalchemy import select
    try:
        result = await db.execute(select(UserSetting).limit(1))
    except Exception as e:
        # E257: если модель имеет поля которых нет в БД — fallback на текстовый запрос
        logger.warning("user_setting_select_failed_try_text", error=str(e))
        try:
            await db.rollback()
        except Exception:
            pass
        from sqlalchemy import text
        result = await db.execute(text("SELECT id FROM user_setting LIMIT 1"))
        row = result.fetchone()
        if row:
            # Получаем через get() — Pydantic ничего не валидирует здесь, но SQLAlchemy может
            from uuid import UUID
            try:
                setting = await db.get(UserSetting, UUID(str(row[0])))
                if setting:
                    return setting
            except Exception:
                pass
        # Создаём новый
        setting = UserSetting()
        db.add(setting)
        await db.commit()
        await db.refresh(setting)
        return setting

    setting = result.scalar_one_or_none()
    if setting:
        return setting

    setting = UserSetting()
    db.add(setting)
    await db.commit()
    await db.refresh(setting)
    logger.info("initial_user_setting_created")
    return setting


# -----------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------}
@router.get("/user-setting")
async def get_user_setting(db: AsyncSession = Depends(get_db)) -> UserSettingResponse:
    setting = await get_or_create_singleton_user_setting(db)
    return _to_response(setting)


@router.patch("/user-setting")
async def update_user_setting(
    body: UserSettingUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserSettingResponse:
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

    try:
        await db.commit()
        await db.refresh(setting)
    except Exception as e:
        await db.rollback()
        logger.error("user_setting_update_failed", error=str(e))
        raise

    logger.info(
        "user_setting_updated",
        fields=list(update_data.keys()),
        correlation_id=correlation_id,
    )

    return _to_response(setting)
