"""E283: тесты для user-setting endpoints.

E283 fix: UserSettingResponse lives in app.routers.user_setting, not app.schemas.
"""
from datetime import datetime, timezone

import pytest
from app.routers.user_setting import UserSettingResponse


def _ts() -> datetime:
    return datetime.now(timezone.utc)


def test_user_setting_response_defaults():
    """UserSettingResponse создаётся с дефолтами."""
    r = UserSettingResponse(
        id="11111111-1111-1111-1111-111111111111",
        llm_provider="hermes",
        llm_model=None,
        whisper_model="base",
        whisper_prompt=None,
        theme="auto",
        hotkey_show_search="ctrl+space",
        notifications_enabled=True,
        updated_at=_ts(),
        default_language="ru",
        use_gpu=False,
    )
    assert r.whisper_model == "base"
    assert r.default_language == "ru"
    assert r.use_gpu is False


def test_user_setting_remote_fields():
    """E254: новые поля remote Whisper присутствуют."""
    r = UserSettingResponse(
        id="11111111-1111-1111-1111-111111111111",
        llm_provider="hermes",
        llm_model=None,
        whisper_model="base",
        whisper_prompt=None,
        theme="auto",
        hotkey_show_search="ctrl+space",
        notifications_enabled=True,
        updated_at=_ts(),
        whisper_remote_enabled=True,
        whisper_remote_url="http://195.133.77.76:8000",
        whisper_remote_path="/transcribe",
    )
    assert r.whisper_remote_enabled is True
    assert "195.133.77.76" in r.whisper_remote_url
