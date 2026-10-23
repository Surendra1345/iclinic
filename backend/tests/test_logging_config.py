import json
import logging

from src.config.settings import settings
from src.observability.logging import JsonFormatter, configure_logging


def test_json_formatter_outputs_one_json_object_with_correlation_ids():
    record = logging.LogRecord("svc", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    record.request_id, record.call_id = "req-1", "call-9"
    data = json.loads(JsonFormatter().format(record))
    assert data["message"] == "hello world" and data["level"] == "INFO"
    assert data["request_id"] == "req-1" and data["call_id"] == "call-9"


def test_configure_logging_switches_to_json_when_asked(monkeypatch):
    root = logging.getLogger()
    saved = list(root.handlers)
    monkeypatch.setattr(settings, "LOG_FORMAT", "json")
    try:
        root.handlers = [logging.StreamHandler()]
        configure_logging()
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
    finally:
        root.handlers = saved
