"""Front desk login endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.rest.dependencies import require_frontdesk
from src.core.services.auth_service import (
    create_token,
    credentials_valid,
    login_limiter,
)
from src.schemas.auth import LoginRequest, LoginResponse

logger = logging.getLogger(__name__)

auth_router = APIRouter(prefix="/api/auth", tags=["Front desk login"])


@auth_router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request):
    client = request.client.host if request.client else "unknown"
    key = f"{client}:{payload.email.strip().lower()}"
    if login_limiter.is_blocked(key):
        raise HTTPException(status_code=429, detail="Too many failed attempts. Please wait a few minutes and try again.")
    if not credentials_valid(payload.email, payload.password):
        login_limiter.record_failure(key)
        logger.warning("Failed front desk login for %s from %s", payload.email.strip().lower(), client)
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    login_limiter.reset(key)
    token, ttl = create_token(payload.email)
    return LoginResponse(access_token=token, expires_in=ttl, email=payload.email.strip().lower())


@auth_router.get("/me")
async def me(email: str = Depends(require_frontdesk)):
    """Lets the dashboard check that its stored token is still valid."""
    return {"email": email, "role": "frontdesk"}
