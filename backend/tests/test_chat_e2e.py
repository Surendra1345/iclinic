"""HTTP-level chat journey tests against a dedicated PostgreSQL test database.

The classifier is deterministic in these tests, while the real FastAPI route,
agent graph, identity node, and PostgreSQL transcript persistence are exercised.
"""
import uuid
from datetime import date

import psycopg
import pytest
from fastapi.testclient import TestClient

from src.api.rest.app import create_app
from src.config.settings import settings
from src.control.agents.nodes.detect_intent import intent_classification_service
from src.core.services.intent_classification_service import IntentClassificationResult, IntentLabel


if "test" not in settings.DATABASE_URL.lower():
    pytest.skip(
        "Chat E2E tests require a dedicated database URL containing 'test'.",
        allow_module_level=True,
    )


def _db_url():
    return settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)


def _fake_classifier(message, conversation_context=None):
    text = (message or "").lower()
    if "book" in text or "appointment" in text:
        label = IntentLabel.BOOK
    elif "front desk" in text or "frontdesk" in text or "human" in text:
        label = IntentLabel.HANDOFF
    elif "branch" in text or "location" in text:
        label = IntentLabel.FAQ
    else:
        label = IntentLabel.UNKNOWN
    return IntentClassificationResult(
        intent=label,
        confidence="high" if label != IntentLabel.UNKNOWN else "low",
        needs_clarification=label == IntentLabel.UNKNOWN,
    )


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def classifier_stub(monkeypatch):
    async def classify_intent(user_message, conversation_context=None):
        return _fake_classifier(user_message, conversation_context)

    monkeypatch.setattr(intent_classification_service, "classify_intent", classify_intent)


def test_chat_greeting_and_branch_faq_persist_across_turns(client):
    session_id = f"pytest-chat-{uuid.uuid4().hex}"
    with psycopg.connect(_db_url()) as db:
        if not db.execute("SELECT id FROM locations LIMIT 1").fetchone():
            with db.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO locations (name, address, is_active) VALUES (%s, %s, true)",
                    [(f"{name} Branch", name) for name in ("Anna Nagar", "T. Nagar", "Tambaram", "Velachery")],
                )

    greeting = client.post("/api/chat", json={"message": "hello", "session_id": session_id})
    assert greeting.status_code == 200
    assert "Welcome to City Care Clinic" in greeting.json()["reply"]

    faq = client.post("/api/chat", json={"message": "what branches do you have?", "session_id": session_id})
    assert faq.status_code == 200
    assert all(name in faq.json()["reply"] for name in ("Anna Nagar", "T. Nagar", "Tambaram", "Velachery"))

    with psycopg.connect(_db_url()) as db:
        row = db.execute(
            "SELECT messages FROM conversations WHERE collected_details->>'call_sid' = %s",
            (session_id,),
        ).fetchone()
        assert row is not None
        messages = row[0]
        assert [item["content"] for item in messages if item["role"] == "patient"] == [
            "hello", "what branches do you have?"
        ]
        assert len([item for item in messages if item["role"] == "agent"]) == 2
        assert any("Anna Nagar" in item.get("content", "") for item in messages if item["role"] == "agent")


def test_booking_requires_identity_then_accepts_name_and_dob(client):
    session_id = f"pytest-chat-{uuid.uuid4().hex}"
    patient_id = uuid.uuid4()
    suffix = "".join(chr(ord("a") + int(char, 16)) for char in uuid.uuid4().hex[:8])
    patient_name = f"Kiran Kumar {suffix}"
    phone = f"+1555{uuid.uuid4().int % 10**7:07d}"
    with psycopg.connect(_db_url()) as db:
        db.execute(
            "INSERT INTO patients (id, full_name, date_of_birth, phone, email) VALUES (%s, %s, %s, %s, %s)",
            (patient_id, patient_name, date(1990, 2, 3), phone, "e2e-patient@example.test"),
        )

    booking = client.post("/api/chat", json={"message": "I want to book an appointment", "session_id": session_id})
    assert booking.status_code == 200
    assert "verify your identity" in booking.json()["reply"].lower()

    name = client.post("/api/chat", json={"message": patient_name, "session_id": session_id})
    assert name.status_code == 200
    assert "date of birth" in name.json()["reply"].lower()

    dob = client.post("/api/chat", json={"message": "03-02-1990", "session_id": session_id})
    assert dob.status_code == 200
    assert "identity has been verified" in dob.json()["reply"].lower()

    with psycopg.connect(_db_url()) as db:
        row = db.execute(
            "SELECT patient_id, identity_verified_at, messages FROM conversations WHERE collected_details->>'call_sid' = %s",
            (session_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == patient_id
        assert row[1] is not None
        assert len([m for m in row[2] if m["role"] == "patient"]) == 3


def test_unknown_question_gets_clarification_without_identity_gate(client):
    session_id = f"pytest-chat-{uuid.uuid4().hex}"
    response = client.post("/api/chat", json={"message": "what does Python mean?", "session_id": session_id})
    assert response.status_code == 200
    reply = response.json()["reply"].lower()
    assert "rephrase" in reply or "clinic" in reply
    assert "verify your identity" not in reply


def test_repeated_identity_failure_escalates_and_records_callback_contact(client):
    session_id = f"pytest-chat-{uuid.uuid4().hex}"
    patient_id = uuid.uuid4()
    with psycopg.connect(_db_url()) as db:
        db.execute(
            "INSERT INTO patients (id, full_name, date_of_birth, phone, email) VALUES (%s, %s, %s, %s, %s)",
            (patient_id, "Maya Patient", date(1988, 6, 5), f"+1555{uuid.uuid4().int % 10**7:07d}", None),
        )

    steps = (
        ("I want to book an appointment", "verify your identity"),
        ("Maya Patient", "date of birth"),
        ("05-06-1989", "couldn't match"),
        ("05-06-1989", "front desk"),
        ("6303023283", "front desk"),
    )
    for message, expected in steps:
        response = client.post("/api/chat", json={"message": message, "session_id": session_id})
        assert response.status_code == 200
        assert expected in response.json()["reply"].lower()

    with psycopg.connect(_db_url()) as db:
        row = db.execute(
            "SELECT identity_verified_at, outcome, collected_details, messages FROM conversations "
            "WHERE collected_details->>'call_sid' = %s",
            (session_id,),
        ).fetchone()
        assert row is not None
        assert row[0] is None
        assert row[1] == "handed_to_front_desk"
        assert row[2].get("handoff_completed") is True
        assert row[2].get("patient_phone") == "+916303023283"
        assert len([m for m in row[3] if m["role"] == "patient"]) == 5
