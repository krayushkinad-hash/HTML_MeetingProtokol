"""Unit tests for Pydantic schemas in app/schemas/__init__.py and routers.

These tests verify schema defaults, validation rules, and serialization.
They do NOT touch the database — purely synchronous in-memory Pydantic checks.

Naming convention:
  test_<schema>_defaults  — schema created with minimal/typical data
  test_<schema>_with_data — schema with full data including optionals
  test_<schema>_validation_errors — invalid input rejected by validator
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError


# ============================================================================
# ProtocolResponse / ProtocolCreate / ProtocolUpdate
# ============================================================================


def test_protocol_create_defaults():
    """ProtocolCreate requires title+date; everything else optional."""
    from app.schemas import ProtocolCreate

    proto = ProtocolCreate(title="My meeting", date=date(2026, 1, 15))
    assert proto.title == "My meeting"
    assert proto.date == date(2026, 1, 15)
    assert proto.location is None
    assert proto.chair is None
    assert proto.agenda is None


def test_protocol_create_with_data():
    """ProtocolCreate accepts all optional fields."""
    from app.schemas import ProtocolCreate

    proto = ProtocolCreate(
        title="Sprint planning",
        date=date(2026, 2, 1),
        location="Room 42",
        chair="Alice",
        agenda="Quarterly OKRs",
    )
    assert proto.location == "Room 42"
    assert proto.chair == "Alice"
    assert proto.agenda == "Quarterly OKRs"


def test_protocol_create_validation_errors():
    """ProtocolCreate rejects empty title and oversized location."""
    from app.schemas import ProtocolCreate

    with pytest.raises(ValidationError):
        ProtocolCreate(title="", date=date(2026, 1, 1))  # min_length=1
    with pytest.raises(ValidationError):
        ProtocolCreate(
            title="x", date=date(2026, 1, 1), location="a" * 300,  # max=255
        )


def test_protocol_update_partial():
    """ProtocolUpdate allows every field to be None."""
    from app.schemas import ProtocolUpdate

    upd = ProtocolUpdate(title="New title")
    assert upd.title == "New title"
    assert upd.location is None
    assert upd.agenda is None


def test_protocol_update_with_language_fields():
    """E148/E149: language and translation_language fields accepted."""
    from app.schemas import ProtocolUpdate

    upd = ProtocolUpdate(language="en", translation_language="ru")
    assert upd.language == "en"
    assert upd.translation_language == "ru"


def test_protocol_response_defaults():
    """ProtocolResponse defaults language='ru', translation_language=None."""
    from app.schemas import ProtocolResponse

    resp = ProtocolResponse(
        id=uuid.uuid4(),
        title="Meeting",
        date=date(2026, 1, 1),
        location=None,
        chair=None,
        agenda=None,
        duration_sec=None,
        wer_quality=None,
        status="loaded",
        audio_file=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    assert resp.language == "ru"
    assert resp.translation_language is None
    assert resp.duration_sec is None
    assert resp.wer_quality is None
    assert resp.audio_file is None
    assert resp.folder_id is None


# ============================================================================
# UtteranceResponse / UtteranceUpdateText / UtteranceUpdateImportant
# ============================================================================


def test_utterance_response_defaults():
    """UtteranceResponse with low_confidence/important False by default."""
    from app.schemas import UtteranceResponse

    resp = UtteranceResponse(
        id=uuid.uuid4(),
        protocol_id=uuid.uuid4(),
        speaker_id=None,
        speaker_label=None,
        start_sec=0.0,
        end_sec=1.0,
        text="hello",
        confidence=None,
        low_confidence=False,
        important=False,
        corrected_by_llm=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    assert resp.low_confidence is False
    assert resp.important is False
    assert resp.corrected_by_llm is False
    assert resp.confidence is None
    assert resp.speaker_id is None
    assert resp.speaker_label is None


def test_utterance_response_with_data():
    """UtteranceResponse round-trips data correctly."""
    from app.schemas import UtteranceResponse

    pid = uuid.uuid4()
    sid = uuid.uuid4()
    resp = UtteranceResponse(
        id=uuid.uuid4(),
        protocol_id=pid,
        speaker_id=sid,
        speaker_label="Alice",
        start_sec=10.5,
        end_sec=15.0,
        text="Hello world",
        confidence=0.92,
        low_confidence=True,
        important=True,
        corrected_by_llm=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    assert resp.protocol_id == pid
    assert resp.speaker_id == sid
    assert resp.confidence == 0.92
    assert resp.low_confidence is True
    assert resp.important is True


def test_utterance_update_text_validation_errors():
    """UtteranceUpdateText: min_length=1, max_length=10000 (E197)."""
    from app.schemas import UtteranceUpdateText

    with pytest.raises(ValidationError):
        UtteranceUpdateText(text="")  # too short
    with pytest.raises(ValidationError):
        UtteranceUpdateText(text="a" * 11000)  # too long


def test_utterance_update_text_defaults():
    """UtteranceUpdateText has version_snapshot=True default."""
    from app.schemas import UtteranceUpdateText

    upd = UtteranceUpdateText(text="fixed typo")
    assert upd.text == "fixed typo"
    assert upd.version_snapshot is True


def test_utterance_update_important():
    """UtteranceUpdateImportant just toggles the flag."""
    from app.schemas import UtteranceUpdateImportant

    assert UtteranceUpdateImportant(important=True).important is True
    assert UtteranceUpdateImportant(important=False).important is False


# ============================================================================
# ScreenshotResponse
# ============================================================================


def test_screenshot_response_defaults():
    """ScreenshotResponse: id/protocol_id/file_path/timestamp_sec/created_at required."""
    from app.routers.screenshots import ScreenshotResponse

    sid = uuid.uuid4()
    pid = uuid.uuid4()
    resp = ScreenshotResponse(
        id=sid,
        protocol_id=pid,
        file_path="/tmp/shot.png",
        timestamp_sec=12.5,
        width_px=None,
        height_px=None,
        file_size_kb=None,
        caption=None,
        created_at="2026-01-15T10:00:00",
    )
    assert resp.id == sid
    assert resp.protocol_id == pid
    assert resp.timestamp_sec == 12.5
    assert resp.width_px is None
    assert resp.height_px is None
    assert resp.file_size_kb is None
    assert resp.caption is None


def test_screenshot_response_with_data():
    """ScreenshotResponse with all optional fields populated."""
    from app.routers.screenshots import ScreenshotResponse

    resp = ScreenshotResponse(
        id=uuid.uuid4(),
        protocol_id=uuid.uuid4(),
        file_path="/data/shots/01.png",
        timestamp_sec=100.0,
        width_px=1920,
        height_px=1080,
        file_size_kb=512,
        caption="Dashboard slide",
        created_at="2026-01-15T10:00:00",
    )
    assert resp.width_px == 1920
    assert resp.height_px == 1080
    assert resp.file_size_kb == 512
    assert resp.caption == "Dashboard slide"


# ============================================================================
# ActionItemResponse / ActionItemCreate / ActionItemUpdate
# ============================================================================


def test_action_item_create_defaults():
    """ActionItemCreate requires task (5..500 chars)."""
    from app.schemas import ActionItemCreate

    item = ActionItemCreate(protocol_id=uuid.uuid4(), task="Write report")
    assert item.task == "Write report"
    assert item.owner is None
    assert item.deadline is None
    assert item.source_utterance_id is None


def test_action_item_create_validation_errors():
    """ActionItemCreate: task min_length=5, max_length=500."""
    from app.schemas import ActionItemCreate

    with pytest.raises(ValidationError):
        ActionItemCreate(protocol_id=uuid.uuid4(), task="a")  # too short
    with pytest.raises(ValidationError):
        ActionItemCreate(protocol_id=uuid.uuid4(), task="x" * 600)  # too long


def test_action_item_update_status_literal():
    """ActionItemUpdate.status is a Literal — invalid values rejected."""
    from app.schemas import ActionItemUpdate

    upd = ActionItemUpdate(status="done")
    assert upd.status == "done"
    with pytest.raises(ValidationError):
        ActionItemUpdate(status="nonsense")


def test_action_item_response_defaults():
    """ActionItemResponse: status='open' for new rows; completed_at None."""
    from app.schemas import ActionItemResponse

    resp = ActionItemResponse(
        id=uuid.uuid4(),
        protocol_id=uuid.uuid4(),
        owner=None,
        task="Task",
        deadline=None,
        status="open",
        source="manual",
        confidence=None,
        completed_at=None,
        created_at=datetime.now(timezone.utc),
    )
    assert resp.status == "open"
    assert resp.source == "manual"
    assert resp.owner is None
    assert resp.deadline is None
    assert resp.confidence is None
    assert resp.completed_at is None


# ============================================================================
# DecisionResponse / DecisionCreate
# ============================================================================


def test_decision_response_defaults():
    """DecisionResponse: priority='medium' default is NOT in response — comes from DB."""
    from app.routers.decisions import DecisionResponse

    resp = DecisionResponse(
        id=uuid.uuid4(),
        protocol_id=uuid.uuid4(),
        text="Approved budget",
        decided_by=None,
        source_utterance_id=None,
        timestamp_sec=None,
        priority="high",
        created_at=datetime.now(timezone.utc),
    )
    assert resp.text == "Approved budget"
    assert resp.priority == "high"
    assert resp.decided_by is None
    assert resp.source_utterance_id is None
    assert resp.timestamp_sec is None


def test_decision_create_with_priority_literal():
    """DecisionCreate priority is Literal — reject invalid."""
    from app.routers.decisions import DecisionCreate

    # Valid priorities
    for p in ("low", "medium", "high"):
        d = DecisionCreate(protocol_id=uuid.uuid4(), text="x", priority=p)
        assert d.priority == p
    # Default
    d = DecisionCreate(protocol_id=uuid.uuid4(), text="x")
    assert d.priority == "medium"
    # Invalid
    with pytest.raises(ValidationError):
        DecisionCreate(protocol_id=uuid.uuid4(), text="x", priority="urgent")


def test_decision_create_validation_errors():
    """DecisionCreate: text min_length=1, max_length=2000."""
    from app.routers.decisions import DecisionCreate

    with pytest.raises(ValidationError):
        DecisionCreate(protocol_id=uuid.uuid4(), text="")
    with pytest.raises(ValidationError):
        DecisionCreate(protocol_id=uuid.uuid4(), text="a" * 3000)


# ============================================================================
# FolderResponse / FolderCreate / FolderUpdate
# ============================================================================


def test_folder_create_defaults():
    """FolderCreate: color='#3b82f6', icon='folder', sort_order=0."""
    from app.schemas import FolderCreate

    f = FolderCreate(name="Q1 meetings")
    assert f.name == "Q1 meetings"
    assert f.color == "#3b82f6"
    assert f.icon == "folder"
    assert f.sort_order == 0
    assert f.parent_id is None


def test_folder_create_color_pattern():
    """FolderCreate.color must match #rrggbb (6 hex digits)."""
    from app.schemas import FolderCreate

    f = FolderCreate(name="x", color="#FF00AA")
    assert f.color == "#FF00AA"
    with pytest.raises(ValidationError):
        FolderCreate(name="x", color="not-a-color")
    with pytest.raises(ValidationError):
        FolderCreate(name="x", color="#FF00")  # too short


def test_folder_update_partial():
    """FolderUpdate allows any subset of fields."""
    from app.schemas import FolderUpdate

    upd = FolderUpdate(name="Renamed")
    assert upd.name == "Renamed"
    assert upd.color is None
    assert upd.icon is None


def test_folder_response_defaults():
    """FolderResponse: protocol_count=0 default, sort_order echoed."""
    from app.schemas import FolderResponse

    fid = uuid.uuid4()
    resp = FolderResponse(
        id=fid,
        name="My folder",
        color="#000000",
        icon="folder",
        parent_id=None,
        sort_order=5,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    assert resp.protocol_count == 0
    assert resp.sort_order == 5
    assert resp.parent_id is None


# ============================================================================
# UserSettingResponse / UserSettingUpdate (defined in app/routers/user_setting)
# ============================================================================


def test_user_setting_response_defaults():
    """UserSettingResponse: id must be str (not UUID)."""
    from app.routers.user_setting import UserSettingResponse

    resp = UserSettingResponse(
        id="1",
        llm_provider="local_ollama",
        llm_model="gpt-oss",
        whisper_model="base",
        whisper_prompt=None,
        theme="dark",
        hotkey_show_search="Ctrl+K",
        notifications_enabled=True,
        updated_at=datetime.now(timezone.utc),
    )
    assert resp.id == "1"
    assert resp.theme == "dark"
    assert resp.use_gpu is None
    assert resp.default_language is None
    assert resp.whisper_remote_enabled is False  # explicit default
    assert resp.whisper_remote_path == "/transcribe"


def test_user_setting_response_with_remote():
    """E257: Remote Whisper fields round-trip."""
    from app.routers.user_setting import UserSettingResponse

    resp = UserSettingResponse(
        id="1",
        llm_provider="hermes",
        llm_model="hermes-3",
        whisper_model="large-v3",
        whisper_prompt=None,
        theme="light",
        hotkey_show_search="Ctrl+K",
        notifications_enabled=False,
        updated_at=datetime.now(timezone.utc),
        whisper_remote_enabled=True,
        whisper_remote_url="http://example.com:8000",
        whisper_remote_path="/v1/transcribe",
    )
    assert resp.whisper_remote_enabled is True
    assert resp.whisper_remote_url == "http://example.com:8000"
    assert resp.whisper_remote_path == "/v1/transcribe"


def test_user_setting_update_partial():
    """UserSettingUpdate: every field optional."""
    from app.routers.user_setting import UserSettingUpdate

    upd = UserSettingUpdate(theme="dark", notifications_enabled=False)
    assert upd.theme == "dark"
    assert upd.notifications_enabled is False
    assert upd.llm_provider is None
    assert upd.whisper_model is None


def test_user_setting_update_theme_literal():
    """UserSettingUpdate.theme is Literal — invalid rejected."""
    from app.routers.user_setting import UserSettingUpdate

    UserSettingUpdate(theme="light")
    with pytest.raises(ValidationError):
        UserSettingUpdate(theme="neon")


# ============================================================================
# TagResponse / TagCreate
# ============================================================================


def test_tag_create_defaults():
    """TagCreate: name required, color optional."""
    from app.routers.tags import TagCreate

    t = TagCreate(protocol_id=uuid.uuid4(), name="urgent")
    assert t.name == "urgent"
    assert t.color is None


def test_tag_create_validation_errors():
    """TagCreate: name min_length=1, max_length=50; color must match hex."""
    from app.routers.tags import TagCreate

    with pytest.raises(ValidationError):
        TagCreate(protocol_id=uuid.uuid4(), name="")
    with pytest.raises(ValidationError):
        TagCreate(protocol_id=uuid.uuid4(), name="a" * 60)
    with pytest.raises(ValidationError):
        TagCreate(protocol_id=uuid.uuid4(), name="ok", color="red")


def test_tag_response_defaults():
    """TagResponse created_at is str (ISO-8601)."""
    from app.routers.tags import TagResponse

    resp = TagResponse(
        id=uuid.uuid4(),
        protocol_id=uuid.uuid4(),
        name="important",
        source="manual",
        color=None,
        created_at="2026-01-15T10:00:00",
    )
    assert resp.name == "important"
    assert resp.source == "manual"
    assert resp.color is None


# ============================================================================
# SpeakerResponse / SpeakerCreate / SpeakerUpdate
# ============================================================================


def test_speaker_create_defaults():
    """SpeakerCreate: speaker_label required, color pattern #rrggbb."""
    from app.schemas import SpeakerCreate

    sp = SpeakerCreate(speaker_label="SPEAKER_00", display_name="Alice", color="#3b82f6")
    assert sp.speaker_label == "SPEAKER_00"
    assert sp.display_name == "Alice"
    assert sp.color == "#3b82f6"


def test_speaker_create_color_validation():
    """SpeakerCreate.color must match ^#[0-9A-Fa-f]{6}$."""
    from app.schemas import SpeakerCreate

    with pytest.raises(ValidationError):
        SpeakerCreate(speaker_label="S1", color="not-a-color")
    with pytest.raises(ValidationError):
        SpeakerCreate(speaker_label="S1", color="#FFF")  # too short


def test_speaker_response_defaults():
    """SpeakerResponse: utterance_count=0 default."""
    from app.schemas import SpeakerResponse

    resp = SpeakerResponse(
        id=uuid.uuid4(),
        protocol_id=uuid.uuid4(),
        speaker_label="S0",
        is_user=False,
        created_at=datetime.now(timezone.utc),
    )
    assert resp.is_user is False
    assert resp.utterance_count == 0
    assert resp.display_name is None
    assert resp.color is None


def test_speaker_merge_request():
    """SpeakerMergeRequest: source_id+target_id required, display_name optional."""
    from app.schemas import SpeakerMergeRequest

    req = SpeakerMergeRequest(source_id=uuid.uuid4(), target_id=uuid.uuid4())
    assert req.source_id != req.target_id
    assert req.new_display_name is None

    req2 = SpeakerMergeRequest(
        source_id=uuid.uuid4(),
        target_id=uuid.uuid4(),
        new_display_name="Merged",
    )
    assert req2.new_display_name == "Merged"


# ============================================================================
# ExportRequest
# ============================================================================


def test_export_request_defaults():
    """ExportRequest: include_* all True except mark_doubtful."""
    from app.schemas import ExportRequest

    req = ExportRequest(protocol_id=uuid.uuid4())
    assert req.include_timestamps is True
    assert req.include_screenshots is True
    assert req.include_video_links is True
    assert req.group_by_speaker is True
    assert req.mark_doubtful is True
    assert req.include_summary is True
    assert req.include_decisions is True
    assert req.include_action_items is True
    assert req.template == "default"


def test_export_request_custom_template():
    """ExportRequest.template is free-form string."""
    from app.schemas import ExportRequest

    req = ExportRequest(protocol_id=uuid.uuid4(), template="compact")
    assert req.template == "compact"


# ============================================================================
# SynthesizeRequest
# ============================================================================


def test_synthesize_request_defaults():
    """SynthesizeRequest: max_screenshots=10, strategy='uniform'."""
    from app.routers.screenshots import SynthesizeRequest

    req = SynthesizeRequest()
    assert req.max_screenshots == 10
    assert req.strategy == "uniform"


def test_synthesize_request_validation_errors():
    """SynthesizeRequest: max_screenshots in [1, 50]."""
    from app.routers.screenshots import SynthesizeRequest

    with pytest.raises(ValidationError):
        SynthesizeRequest(max_screenshots=0)
    with pytest.raises(ValidationError):
        SynthesizeRequest(max_screenshots=100)


def test_synthesize_request_strategies():
    """SynthesizeRequest accepts all four strategies as free-form string."""
    from app.routers.screenshots import SynthesizeRequest

    for strat in ("uniform", "important", "decisions", "change_detection"):
        req = SynthesizeRequest(strategy=strat)
        assert req.strategy == strat


# ============================================================================
# TranscriptionRequest / TranscriptionStatus
# ============================================================================


def test_transcription_request_defaults():
    """TranscriptionRequest: language='ru', beam_size=1, model=None."""
    from app.schemas import TranscriptionRequest

    req = TranscriptionRequest(protocol_id=uuid.uuid4())
    assert req.language == "ru"
    assert req.beam_size == 1
    assert req.model is None
    assert req.compute_type is None
    assert req.prompt is None
    assert req.initial_prompt is None


def test_transcription_request_model_literal():
    """TranscriptionRequest.model is Literal — invalid rejected."""
    from app.schemas import TranscriptionRequest

    for m in ("tiny", "base", "small", "medium", "large-v3"):
        req = TranscriptionRequest(protocol_id=uuid.uuid4(), model=m)
        assert req.model == m
    with pytest.raises(ValidationError):
        TranscriptionRequest(protocol_id=uuid.uuid4(), model="huge")


def test_transcription_request_beam_size_bounds():
    """TranscriptionRequest.beam_size in [1, 5]."""
    from app.schemas import TranscriptionRequest

    with pytest.raises(ValidationError):
        TranscriptionRequest(protocol_id=uuid.uuid4(), beam_size=0)
    with pytest.raises(ValidationError):
        TranscriptionRequest(protocol_id=uuid.uuid4(), beam_size=10)


def test_transcription_status_defaults():
    """TranscriptionStatus: progress_percent ge=0, le=100."""
    from app.schemas import TranscriptionStatus

    ts = TranscriptionStatus(
        task_id=uuid.uuid4(),
        protocol_id=uuid.uuid4(),
        status="queued",
        progress_percent=0,
    )
    assert ts.progress_percent == 0
    assert ts.current_chunk is None
    assert ts.peak_rss_mb is None
    assert ts.estimated_completion is None


def test_transcription_status_progress_bounds():
    """TranscriptionStatus.progress_percent in [0, 100]."""
    from app.schemas import TranscriptionStatus

    with pytest.raises(ValidationError):
        TranscriptionStatus(
            task_id=uuid.uuid4(), protocol_id=uuid.uuid4(),
            status="queued", progress_percent=-1,
        )
    with pytest.raises(ValidationError):
        TranscriptionStatus(
            task_id=uuid.uuid4(), protocol_id=uuid.uuid4(),
            status="queued", progress_percent=200,
        )


# ============================================================================
# SummarizeRequest / ExtractActionsRequest / DictionaryTerm
# ============================================================================


def test_summarize_request_defaults():
    """SummarizeRequest: provider=hermes, style=brief, max_words=500."""
    from app.schemas import SummarizeRequest

    req = SummarizeRequest(protocol_id=uuid.uuid4())
    assert req.provider == "hermes"
    assert req.style == "brief"
    assert req.max_words == 500
    assert req.include_citations is True


def test_summarize_request_max_words_bounds():
    """SummarizeRequest.max_words in [100, 2000]."""
    from app.schemas import SummarizeRequest

    with pytest.raises(ValidationError):
        SummarizeRequest(protocol_id=uuid.uuid4(), max_words=50)
    with pytest.raises(ValidationError):
        SummarizeRequest(protocol_id=uuid.uuid4(), max_words=3000)


def test_extract_actions_request_defaults():
    """ExtractActionsRequest: min_confidence=0.6, add_to_existing=True."""
    from app.schemas import ExtractActionsRequest

    req = ExtractActionsRequest(protocol_id=uuid.uuid4())
    assert req.provider == "hermes"
    assert req.min_confidence == 0.6
    assert req.add_to_existing is True


def test_extract_actions_request_confidence_bounds():
    """ExtractActionsRequest.min_confidence in [0.0, 1.0]."""
    from app.schemas import ExtractActionsRequest

    with pytest.raises(ValidationError):
        ExtractActionsRequest(protocol_id=uuid.uuid4(), min_confidence=-0.1)
    with pytest.raises(ValidationError):
        ExtractActionsRequest(protocol_id=uuid.uuid4(), min_confidence=1.5)


def test_dictionary_term_create_defaults():
    """DictionaryTermCreate: category='other', weight=1.00."""
    from app.schemas import DictionaryTermCreate

    t = DictionaryTermCreate(term="API")
    assert t.category == "other"
    assert t.weight == 1.00


def test_dictionary_term_create_category_literal():
    """DictionaryTermCreate.category is Literal — invalid rejected."""
    from app.schemas import DictionaryTermCreate

    for cat in ("name", "product", "abbreviation", "other"):
        t = DictionaryTermCreate(term="xyz", category=cat)
        assert t.category == cat
    with pytest.raises(ValidationError):
        DictionaryTermCreate(term="xyz", category="place")


def test_dictionary_term_create_validation_errors():
    """DictionaryTermCreate: term min_length=2, max_length=100; weight [0,1]."""
    from app.schemas import DictionaryTermCreate

    with pytest.raises(ValidationError):
        DictionaryTermCreate(term="A")  # too short
    with pytest.raises(ValidationError):
        DictionaryTermCreate(term="x" * 200)  # too long
    with pytest.raises(ValidationError):
        DictionaryTermCreate(term="ok", weight=1.5)


# ============================================================================
# Live / Bot
# ============================================================================


def test_live_start_request_validation_errors():
    """LiveStartRequest: telemost_url pattern https://.*."""
    from app.schemas import LiveStartRequest

    req = LiveStartRequest(
        telemost_url="https://telemost.yandex.ru/j/123",
        title="Live Meeting",
    )
    assert req.title == "Live Meeting"
    assert req.audio_device == "default"
    assert req.enable_screenshots is True
    assert req.screenshot_interval_sec == 60

    with pytest.raises(ValidationError):
        LiveStartRequest(telemost_url="http://insecure", title="x")
    with pytest.raises(ValidationError):
        LiveStartRequest(telemost_url="https://ok.com", title="")


def test_live_start_request_screenshot_interval_bounds():
    """LiveStartRequest.screenshot_interval_sec in [10, 600]."""
    from app.schemas import LiveStartRequest

    with pytest.raises(ValidationError):
        LiveStartRequest(telemost_url="https://x.com", title="t", screenshot_interval_sec=5)
    with pytest.raises(ValidationError):
        LiveStartRequest(telemost_url="https://x.com", title="t", screenshot_interval_sec=1000)


def test_bot_user_create_defaults():
    """BotUserCreate: only telegram_id required."""
    from app.schemas import BotUserCreate

    user = BotUserCreate(telegram_id=12345)
    assert user.telegram_id == 12345
    assert user.username is None
    assert user.display_name is None


# ============================================================================
# FromUrlRequest / MoveProtocolRequest
# ============================================================================


def test_from_url_request_defaults():
    """FromUrlRequest: only url required."""
    from app.schemas import FromUrlRequest

    req = FromUrlRequest(url="https://meet.example.com/abc")
    assert req.url == "https://meet.example.com/abc"
    assert req.title is None
    assert req.date is None
    assert req.location is None
    assert req.chair is None


def test_move_protocol_request_with_null_folder():
    """MoveProtocolRequest accepts None folder_id (remove from folder)."""
    from app.schemas import MoveProtocolRequest

    req = MoveProtocolRequest(folder_id=None)
    assert req.folder_id is None

    fid = uuid.uuid4()
    req2 = MoveProtocolRequest(folder_id=fid)
    assert req2.folder_id == fid


def test_move_protocols_batch_defaults():
    """MoveProtocolsBatch: protocol_ids list, folder_id required (None allowed)."""
    from app.schemas import MoveProtocolsBatch

    pids = [uuid.uuid4(), uuid.uuid4()]
    batch = MoveProtocolsBatch(protocol_ids=pids, folder_id=None)
    assert len(batch.protocol_ids) == 2
    assert batch.folder_id is None


# ============================================================================
# PaginationParams / ProblemDetails
# ============================================================================


def test_pagination_params_defaults():
    """PaginationParams: page=1, limit=50."""
    from app.schemas import PaginationParams

    pp = PaginationParams()
    assert pp.page == 1
    assert pp.limit == 50
    assert pp.sort is None


def test_pagination_params_bounds():
    """PaginationParams: page ge=1, limit ge=1 le=200."""
    from app.schemas import PaginationParams

    with pytest.raises(ValidationError):
        PaginationParams(page=0)
    with pytest.raises(ValidationError):
        PaginationParams(limit=0)
    with pytest.raises(ValidationError):
        PaginationParams(limit=500)


def test_problem_details_defaults():
    """ProblemDetails: optional fields default to None."""
    from app.schemas import ProblemDetails

    pd = ProblemDetails(
        type="about:blank",
        title="Err",
        status=500,
        code="ERR",
        message="Oops",
    )
    assert pd.details is None
    assert pd.correlation_id is None
    assert pd.timestamp is None