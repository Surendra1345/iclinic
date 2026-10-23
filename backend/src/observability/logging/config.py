"""Logging configuration with request and call correlation fields.

Set LOG_FORMAT=json for one JSON object per line (for log shippers); the default is plain text.
"""
import json
import logging

from src.config.settings import settings
from src.observability.context import get_call_id, get_request_id

TEXT_FORMAT = "%(asctime)s %(levelname)s request_id=%(request_id)s call_id=%(call_id)s %(name)s: %(message)s"


class CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        record.call_id = get_call_id()
        return True


class JsonFormatter(logging.Formatter):
    """Structured log line: time, level, logger, message and the correlation ids."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
            "call_id": getattr(record, "call_id", None),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    level = getattr(logging, str(settings.LOG_LEVEL).upper(), logging.INFO)
    logging.basicConfig(level=level, format=TEXT_FORMAT, force=False)
    root = logging.getLogger()
    correlation_filter = CorrelationFilter()
    if not any(isinstance(item, CorrelationFilter) for item in root.filters):
        root.addFilter(correlation_filter)
    for handler in root.handlers:
        if not any(isinstance(item, CorrelationFilter) for item in handler.filters):
            handler.addFilter(correlation_filter)
        if str(settings.LOG_FORMAT).lower() == "json":
            handler.setFormatter(JsonFormatter())
