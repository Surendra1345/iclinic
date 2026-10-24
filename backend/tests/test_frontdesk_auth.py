import time

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from src.api.rest.dependencies import require_frontdesk
from src.api.rest.routes.auth import auth_router
from src.api.rest.routes.dashboard import dashboard_router
from src.config.settings import settings
from src.core.services import auth_service

EMAIL, PASSWORD = "desk@example.com", "correct horse battery"


@pytest.fixture(autouse=True)
def configured_account(monkeypatch):
    monkeypatch.setattr(settings, "FRONTDESK_EMAIL", EMAIL)
    monkeypatch.setattr(settings, "FRONTDESK_PASSWORD", PASSWORD)
    monkeypatch.setattr(settings, "AUTH_SECRET", "test-secret")
    auth_service.login_limiter._failures.clear()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(auth_router)
    return TestClient(app)  # no lifespan: no database or checkpoint setup


def _login(client, email=EMAIL, password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_correct_credentials_return_a_token_that_opens_the_session(client):
    response = _login(client)
    assert response.status_code == 200
    token = response.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["email"] == EMAIL


def test_email_is_not_case_sensitive_but_password_is(client):
    assert _login(client, email="DESK@Example.com").status_code == 200
    assert _login(client, password=PASSWORD.upper()).status_code == 401


def test_wrong_credentials_are_rejected_without_saying_which_part_was_wrong(client):
    wrong_email = _login(client, email="other@example.com")
    wrong_password = _login(client, password="nope")
    assert wrong_email.status_code == wrong_password.status_code == 401
    assert wrong_email.json() == wrong_password.json()


def test_no_login_is_possible_when_no_account_is_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "FRONTDESK_PASSWORD", "")
    assert _login(client, password="").status_code == 401


def test_repeated_failures_lock_the_client_out_for_a_while(client):
    for _ in range(5):
        assert _login(client, password="wrong").status_code == 401
    assert _login(client, password="wrong").status_code == 429
    assert _login(client).status_code == 429  # even the right password waits


def test_missing_garbled_tampered_and_expired_tokens_are_refused(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Basic abc"}).status_code == 401

    token, _ = auth_service.create_token(EMAIL)
    payload, signature = token.split(".")
    tampered = f"{payload}.{signature[:-2]}xx"
    assert auth_service.verify_token(tampered) is None

    expired, _ = auth_service.create_token(EMAIL, ttl_seconds=-5)
    assert auth_service.verify_token(expired) is None

    other_secret = auth_service.create_token(EMAIL)[0]
    settings.AUTH_SECRET = "a-different-secret"
    assert auth_service.verify_token(other_secret) is None


def test_every_dashboard_endpoint_requires_login_but_patient_chat_does_not():
    def needs_login(route):
        return any(dep.call is require_frontdesk for dep in route.dependant.dependencies)

    by_path = {route.path: route for route in dashboard_router.routes}
    protected = [p for p in by_path if p.startswith("/api/dashboard")]
    assert len(protected) >= 7
    assert all(needs_login(by_path[p]) for p in protected)
    assert not needs_login(by_path["/api/chat"])


def test_dashboard_returns_401_without_a_token(client):
    app = FastAPI()
    app.include_router(dashboard_router)
    anonymous = TestClient(app)
    for path in ("/api/dashboard/stats", "/api/dashboard/appointments", "/api/dashboard/conversations"):
        assert anonymous.get(path).status_code == 401
