"""HTTP correlation middleware."""
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.observability.context import call_id_context, request_id_context
from src.observability.metrics import (
    http_request_duration_seconds,
    http_requests_total,
)


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid4().hex
        token = request_id_context.set(request_id)
        call_id = request.query_params.get("call_sid") or request.query_params.get("CallSid")
        call_token = call_id_context.set(call_id) if call_id else None
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            path = request.url.path
            elapsed = time.perf_counter() - started
            http_request_duration_seconds.labels(request.method, path).observe(elapsed)
            http_requests_total.labels(request.method, path, str(status)).inc()
            request_id_context.reset(token)
            if call_token is not None:
                call_id_context.reset(call_token)
