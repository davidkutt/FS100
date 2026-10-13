import pytest

from ai_service.core.settings import Settings


def test_defaults() -> None:
    settings = Settings()

    assert (settings.ai_port, settings.log_level) == (8000, "info")


def test_empty_values_behave_like_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PORT", "")
    monkeypatch.setenv("LOG_LEVEL", "")

    assert (Settings().ai_port, Settings().log_level) == (8000, "info")


def test_rejects_unknown_log_levels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "verbose")

    with pytest.raises(ValueError, match="log_level"):
        Settings()
