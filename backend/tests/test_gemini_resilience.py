import asyncio

import pytest

from src.config.settings import settings
from src.handlers.http_clients import gemini_service
from src.handlers.http_clients.gemini_service import GeminiService


def _service(monkeypatch, outcomes, fallback=""):
    """outcomes: model -> list of results/exceptions consumed per call."""
    calls = []
    gemini_service._model_down_until.clear()
    gemini_service._no_thinking_control.clear()

    class _Models:
        async def generate_content(self, model, contents, config):
            calls.append(model)
            item = outcomes[model].pop(0)
            if isinstance(item, Exception):
                raise item
            return type("R", (), {"text": item})()

    svc = GeminiService(api_key="x", model_name="primary")
    svc.client = type("C", (), {"aio": type("A", (), {"models": _Models()})()})()
    monkeypatch.setattr(settings, "GEMINI_FALLBACK_MODEL", fallback)
    monkeypatch.setattr(settings, "GEMINI_RETRY_DELAY_SECONDS", 0)
    return svc, calls


def test_retries_primary_once_on_503(monkeypatch):
    svc, calls = _service(monkeypatch, {"primary": [Exception("503 UNAVAILABLE"), "ok"]})
    assert asyncio.run(svc.generate_content("hi")) == "ok"
    assert calls == ["primary", "primary"]


def test_switches_to_backup_model_when_primary_stays_down(monkeypatch):
    svc, calls = _service(
        monkeypatch,
        {"primary": [Exception("503 UNAVAILABLE"), Exception("503 UNAVAILABLE")], "backup": ["from backup"]},
        fallback="backup",
    )
    assert asyncio.run(svc.generate_content("hi")) == "from backup"
    assert calls == ["primary", "primary", "backup"]


def test_config_errors_are_not_retried(monkeypatch):
    svc, calls = _service(monkeypatch, {"primary": [Exception("404 NOT_FOUND")]}, fallback="backup")
    with pytest.raises(Exception, match="404"):
        asyncio.run(svc.generate_content("hi"))
    assert calls == ["primary"]


def test_failed_primary_is_skipped_on_the_next_request(monkeypatch):
    svc, calls = _service(
        monkeypatch,
        {"primary": [Exception("503 UNAVAILABLE"), Exception("503 UNAVAILABLE")], "backup": ["a", "b"]},
        fallback="backup",
    )
    assert asyncio.run(svc.generate_content("1")) == "a"
    assert asyncio.run(svc.generate_content("2")) == "b"
    assert calls == ["primary", "primary", "backup", "backup"]  # 2nd request went straight to backup


def test_thinking_off_is_dropped_for_models_that_reject_it(monkeypatch):
    seen = []

    class _Models:
        async def generate_content(self, model, contents, config):
            seen.append(config.thinking_config is not None)
            if config.thinking_config is not None:
                raise Exception("400 INVALID_ARGUMENT thinking not supported")
            return type("R", (), {"text": "ok"})()

    gemini_service._model_down_until.clear()
    gemini_service._no_thinking_control.clear()
    monkeypatch.setattr(settings, "GEMINI_FALLBACK_MODEL", "")
    svc = GeminiService(api_key="x", model_name="primary")
    svc.client = type("C", (), {"aio": type("A", (), {"models": _Models()})()})()
    assert asyncio.run(svc.generate_content("hi")) == "ok"
    assert asyncio.run(svc.generate_content("again")) == "ok"
    assert seen == [True, False, False]  # tried once, then remembered the model rejects it


def test_quota_error_is_not_retried_and_skips_model_for_a_long_time(monkeypatch):
    svc, calls = _service(
        monkeypatch,
        {"primary": [Exception("429 RESOURCE_EXHAUSTED quota")], "backup": ["a", "b"]},
        fallback="b1, backup",
    )
    monkeypatch.setattr(settings, "GEMINI_FALLBACK_MODEL", "backup")
    assert asyncio.run(svc.generate_content("1")) == "a"
    assert asyncio.run(svc.generate_content("2")) == "b"
    assert calls == ["primary", "backup", "backup"]
    assert gemini_service._model_down_until["primary"] - __import__("time").monotonic() > 100
