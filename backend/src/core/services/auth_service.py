"""Front desk login: credentials come from settings, sessions are signed, expiring tokens.

Uses only the standard library. The password is never stored in code; set FRONTDESK_EMAIL,
FRONTDESK_PASSWORD and AUTH_SECRET in the environment.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple

from src.config.settings import settings

# Used only when AUTH_SECRET is not configured: tokens then stop working when the server restarts.
_FALLBACK_SECRET = secrets.token_urlsafe(32)


def _secret() -> bytes:
    return (settings.AUTH_SECRET or _FALLBACK_SECRET).encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload_b64: str) -> str:
    return _b64(hmac.new(_secret(), payload_b64.encode(), hashlib.sha256).digest())


def credentials_valid(email: str, password: str) -> bool:
    """Constant-time check against the configured front desk account."""
    expected_email = (settings.FRONTDESK_EMAIL or "").strip().lower()
    expected_password = settings.FRONTDESK_PASSWORD or ""
    if not expected_email or not expected_password:
        return False  # no account configured: nobody can log in
    email_ok = hmac.compare_digest((email or "").strip().lower().encode(), expected_email.encode())
    password_ok = hmac.compare_digest((password or "").encode(), expected_password.encode())
    return email_ok and password_ok


def create_token(email: str, ttl_seconds: Optional[int] = None) -> Tuple[str, int]:
    ttl = ttl_seconds if ttl_seconds is not None else int(settings.AUTH_TOKEN_TTL_MINUTES) * 60
    payload = {"sub": email.strip().lower(), "role": "frontdesk", "exp": int(time.time()) + ttl}
    payload_b64 = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{payload_b64}.{_sign(payload_b64)}", ttl


def verify_token(token: Optional[str]) -> Optional[str]:
    """Return the account email if the token is genuine and not expired, else None."""
    if not token or token.count(".") != 1:
        return None
    payload_b64, signature = token.split(".")
    if not hmac.compare_digest(signature.encode(), _sign(payload_b64).encode()):
        return None
    try:
        payload = json.loads(_unb64(payload_b64))
    except (ValueError, json.JSONDecodeError):
        return None
    if payload.get("role") != "frontdesk" or int(payload.get("exp", 0)) < time.time():
        return None
    return payload.get("sub")


class LoginRateLimiter:
    """Blocks repeated failed logins from the same client (in memory, per server process)."""

    def __init__(self, max_failures: int = 5, window_seconds: int = 300) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: Dict[str, Deque[float]] = defaultdict(deque)

    def _recent(self, key: str) -> Deque[float]:
        failures = self._failures[key]
        cutoff = time.time() - self.window_seconds
        while failures and failures[0] < cutoff:
            failures.popleft()
        return failures

    def is_blocked(self, key: str) -> bool:
        return len(self._recent(key)) >= self.max_failures

    def record_failure(self, key: str) -> None:
        self._recent(key).append(time.time())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


login_limiter = LoginRateLimiter()
