"""Request and call correlation context."""
from contextvars import ContextVar
from typing import Optional

request_id_context: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
call_id_context: ContextVar[Optional[str]] = ContextVar("call_id", default=None)


def get_request_id() -> str:
    return request_id_context.get() or "-"


def get_call_id() -> str:
    return call_id_context.get() or "-"
