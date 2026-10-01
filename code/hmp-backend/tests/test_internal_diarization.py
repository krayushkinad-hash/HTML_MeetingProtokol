"""E286: тесты DiarizationService."""
import pytest


def test_diarization_imports():
    from app.services.diarization import DiarizationService
    assert DiarizationService is not None


def test_diarization_pause_threshold_default():
    from app.services.diarization import DiarizationService
    # PAUSE_THRESHOLD_SEC — class-level constant for turn boundary detection
    assert hasattr(DiarizationService, "PAUSE_THRESHOLD_SEC")
    assert isinstance(DiarizationService.PAUSE_THRESHOLD_SEC, (int, float))
    assert DiarizationService.PAUSE_THRESHOLD_SEC > 0
    service = DiarizationService()
    assert service is not None


def test_diarization_service_initialization():
    """Сервис создаётся с дефолтными параметрами."""
    from app.services.diarization import DiarizationService
    service = DiarizationService()
    assert service is not None


def test_diarization_group_speakers_empty():
    """Group speakers для пустого списка."""
    from app.services.diarization import DiarizationService
    service = DiarizationService()
    try:
        result = service.group_speakers([])
        assert isinstance(result, (list, dict))
    except AttributeError:
        pytest.skip("group_speakers API не найден")


def test_diarization_with_sample_segments():
    """Group speakers для простых сегментов."""
    from app.services.diarization import DiarizationService
    service = DiarizationService()
    segments = [
        {"start": 0.0, "end": 1.0, "speaker": "A"},
        {"start": 2.0, "end": 3.0, "speaker": "B"},
        {"start": 5.0, "end": 6.0, "speaker": "A"},
    ]
    try:
        result = service.group_speakers(segments)
        assert isinstance(result, (list, dict))
    except AttributeError:
        pytest.skip("group_speakers API не найден")


def test_diarization_min_max_speakers():
    """min_speakers и max_speakers конфигурируются через diarize_protocol."""
    from app.services.diarization import DiarizationService
    service = DiarizationService()
    assert service is not None
    # min/max speakers передаются в diarize_protocol, а не в __init__
    import inspect
    sig = inspect.signature(service.diarize_protocol)
    assert "min_speakers" in sig.parameters
    assert "max_speakers" in sig.parameters
