"""Logging configuration with request and call correlation fields."""
import logging

from src.observability.context import get_call_id, get_request_id


class CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        record.call_id = get_call_id()
        return True


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s request_id=%(request_id)s call_id=%(call_id)s %(name)s: %(message)s",
        force=False,
    )
    root = logging.getLogger()
    correlation_filter = CorrelationFilter()
    if not any(isinstance(item, CorrelationFilter) for item in root.filters):
        root.addFilter(correlation_filter)
    for handler in root.handlers:
        if not any(isinstance(item, CorrelationFilter) for item in handler.filters):
            handler.addFilter(correlation_filter)
