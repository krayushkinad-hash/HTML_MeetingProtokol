"""E283: тесты для /screenshots/synthesize endpoint."""
import pytest


def test_synthesize_request_validation():
    """Проверка валидации SynthesizeRequest."""
    from app.routers.screenshots import SynthesizeRequest
    req = SynthesizeRequest()
    assert req.max_screenshots == 10
    assert req.strategy == "uniform"


def test_synthesize_strategy_options():
    """Поддерживаются все 4 стратегии."""
    from app.routers.screenshots import SynthesizeRequest
    for strat in ["uniform", "important", "decisions", "change_detection"]:
        req = SynthesizeRequest(strategy=strat)
        assert req.strategy == strat
