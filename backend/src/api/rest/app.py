from contextlib import asynccontextmanager
import asyncio
import hmac
import logging
import time

# pyrefly: ignore[missing-import]
from fastapi import FastAPI, Header, HTTPException, Request
# pyrefly: ignore[missing-import]
from fastapi.middleware.cors import CORSMiddleware
# pyrefly: ignore[missing-import]
from fastapi.responses import JSONResponse, Response
# pyrefly: ignore[missing-import]
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
# pyrefly: ignore[missing-import]
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
    from src.control.agents.graph import (
        close_persistent_checkpointer,
        initialize_persistent_checkpointer,
    )
    await initialize_persistent_checkpointer(settings.DATABASE_URL)
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
    await close_persistent_checkpointer()


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
    from src.api.rest.routes.voice_assistant import router as voice_assistant_router
    from src.api.rest.routes.dashboard import dashboard_router

    # 1. Outbound Call Trigger (POST /api/calls/trigger)
    app.include_router(calls_router)

    # 2. Twilio Conversational Webhooks (/twilio/voice, /twilio/agent-turn, /twilio/audio/{id})
    app.include_router(twiml_router)
    app.include_router(voice_assistant_router)

    # 3. Frontdesk Dashboard & Patient Chat (/api/dashboard/..., /api/chat)
    app.include_router(dashboard_router)

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

    @app.get("/internal/diagnostics/intent-classifier", include_in_schema=False)
    async def intent_classifier_diagnostics(
        x_diagnostics_key: str = Header(default="", alias="X-Diagnostics-Key"),
    ):
        configured_key = settings.DIAGNOSTICS_API_KEY
        if not configured_key:
            raise HTTPException(status_code=404, detail="Not found")
        if not hmac.compare_digest(x_diagnostics_key, configured_key):
            raise HTTPException(status_code=404, detail="Not found")
        from src.services.intent_classification_service import intent_classification_service
        return intent_classification_service.get_latency_stats()

    return app
