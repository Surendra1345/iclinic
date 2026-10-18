from contextlib import asynccontextmanager
import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from src.config.settings import settings
from src.api.middleware.correlation import CorrelationMiddleware
from src.data.clients.postgres import AsyncSessionLocal
from src.observability.logging_config import configure_logging
from src.observability.metrics import database_operation_duration_seconds

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown hooks."""
    # ── Startup ──────────────────────────────────────────────────────────────
    # Import here to avoid circular imports at module load time
    from src.api.rest.routes import voice  # noqa: F401  (registers router)
    # pyrefly: ignore[missing-import]
    from src.core.scheduler import start_scheduler
    await start_scheduler()
    yield
    # ── Shutdown ─────────────────────────────────────────────────────────────
    # pyrefly: ignore[missing-import]
    from src.core.scheduler import stop_scheduler
    await stop_scheduler()


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title=f"{settings.CLINIC_NAME} — Voice Agent API",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(CorrelationMiddleware)

    # ── CORS ─────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from src.api.rest.routes.voice import calls_router, twiml_router

    # 1. Outbound Call Trigger (POST /api/calls/trigger)
    app.include_router(calls_router)

    # 2. Twilio Conversational Webhooks (/twilio/voice, /twilio/agent-turn, /twilio/audio/{id})
    app.include_router(twiml_router)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        request_id = request.headers.get("X-Request-ID", "-")
        logger.exception("Unhandled request error path=%s request_id=%s", request.url.path, request_id)
        if request.url.path.startswith("/twilio/"):
            return Response(
                content=(
                    '<?xml version="1.0" encoding="UTF-8"?><Response>'
                    '<Say voice="Polly.Aditi" language="en-IN">'
                    "We are sorry, the service is temporarily unavailable. Please try again later."
                    "</Say><Hangup /></Response>"
                ),
                media_type="application/xml",
                status_code=200,
                headers={"X-Request-ID": request_id},
            )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error.", "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )

    @app.get("/health")
    async def health():
        started = time.perf_counter()
        database_status = "ok"
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            database_status = "error"
            logger.exception("Health check database probe failed")
        finally:
            database_operation_duration_seconds.labels("health_check").observe(
                time.perf_counter() - started
            )

        scheduler_status = "ok"
        from src.core.scheduler import is_scheduler_running
        if not is_scheduler_running():
            scheduler_status = "stopped"

        healthy = database_status == "ok" and scheduler_status == "ok"
        payload = {
            "status": "ok" if healthy else "degraded",
            "service": settings.CLINIC_NAME,
            "checks": {
                "database": database_status,
                "scheduler": scheduler_status,
            },
        }
        return JSONResponse(status_code=200 if healthy else 503, content=payload)

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app
