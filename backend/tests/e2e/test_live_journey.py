"""End-to-end journey against a RUNNING backend (real database, agent, Gemini).

Skipped unless E2E_BASE_URL is set, because it books and cancels a real appointment for a test patient.

    # start the backend (docker compose up -d, or uvicorn), then:
    $env:E2E_BASE_URL="http://localhost:8000"
    $env:E2E_PATIENT_NAME="Surendra"
    $env:E2E_PATIENT_DOB="3 September 2004"      # a seeded patient with NO active appointment
    $env:E2E_PATIENT_PHONE="+919986251229"       # that patient's phone, to tell them apart from same-named patients
    $env:E2E_FRONTDESK_EMAIL="frontdesk@gmail.com"
    $env:E2E_FRONTDESK_PASSWORD="frontdesk@123"
    uv run pytest tests/e2e -q -s

The test cancels what it books, also when it fails half way.
"""
import os
import uuid

import httpx
import pytest

BASE_URL = os.getenv("E2E_BASE_URL")
NAME = os.getenv("E2E_PATIENT_NAME")
DOB = os.getenv("E2E_PATIENT_DOB")
PHONE = os.getenv("E2E_PATIENT_PHONE")   # tells the test patient apart from others with the same name
FRONTDESK_EMAIL = os.getenv("E2E_FRONTDESK_EMAIL", "")
FRONTDESK_PASSWORD = os.getenv("E2E_FRONTDESK_PASSWORD", "")

pytestmark = pytest.mark.skipif(
    not (BASE_URL and NAME and DOB and PHONE),
    reason="Set E2E_BASE_URL, E2E_PATIENT_NAME, E2E_PATIENT_DOB and E2E_PATIENT_PHONE to run the live journey.",
)


class Chat:
    """One patient conversation over the real HTTP API."""

    def __init__(self, client: httpx.Client):
        self.client = client
        self.session_id = f"e2e_{uuid.uuid4().hex[:10]}"
        self.last: dict = {}

    def say(self, message: str) -> str:
        response = self.client.post("/api/chat", json={"message": message, "session_id": self.session_id})
        assert response.status_code == 200, response.text
        self.last = response.json()
        print(f"\nYOU  : {message}\nAGENT: {self.last['reply']}")
        return self.last["reply"]

    @property
    def buttons(self) -> list:
        return [option["message"] for option in self.last.get("slot_options", [])]

    def tap(self, index: int = 0) -> str:
        assert self.buttons, f"expected buttons after: {self.last.get('reply')}"
        return self.say(self.buttons[index])

    def verify_identity(self) -> None:
        self.say(f"My name is {NAME} and my date of birth is {DOB}")
        assert "verified" in self.last["reply"].lower(), self.last["reply"]


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=90) as http:
        yield http


@pytest.fixture(scope="module")
def frontdesk_token(client):
    if not (FRONTDESK_EMAIL and FRONTDESK_PASSWORD):
        pytest.skip("Set E2E_FRONTDESK_EMAIL and E2E_FRONTDESK_PASSWORD to check the front desk dashboard.")
    response = client.post("/api/auth/login", json={"email": FRONTDESK_EMAIL, "password": FRONTDESK_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _my_active_appointments(client, token):
    response = client.get(
        "/api/dashboard/appointments",
        params={"search": PHONE, "sort": "created_at", "order": "desc"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    return [
        a for a in response.json()["appointments"]
        if a["status"] in ("booked", "rescheduled") and a["patient_phone"] == PHONE and a["patient_name"] == NAME
    ]


def _hold_a_slot(chat: Chat, day: str) -> None:
    """Ask for a day, then tap through the offered buttons until a slot is held."""
    chat.say(f"{day}")
    for _ in range(4):
        if "tentatively held" in chat.last["reply"].lower() or "held" in chat.last["reply"].lower():
            return
        chat.tap(0)
    assert "held" in chat.last["reply"].lower(), chat.last["reply"]


def test_dashboard_requires_a_login(client):
    assert client.get("/api/dashboard/stats").status_code == 401
    assert client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong"}).status_code == 401


def test_clinic_questions_are_answered_from_clinic_data(client):
    chat = Chat(client)
    reply = chat.say("Which branches do you have and where are they?").lower()
    assert all(branch in reply for branch in ("anna nagar", "t. nagar", "tambaram", "velachery")), reply
    assert "chennai" in chat.say("Where is the Velachery branch?").lower()
    assert "30" in chat.say("How long is a consultation?")
    assert "one active appointment" in chat.say("Can I book more than one appointment at a time?").lower()
    assert "24" in chat.say("What is your cancellation policy?")
    assert "emergency" in chat.say("I have chest pain and can't breathe").lower()
    assert "clinic" in chat.say("What is the capital of France?").lower()


def test_book_reschedule_and_cancel_in_chat(client, frontdesk_token):
    before = _my_active_appointments(client, frontdesk_token)
    assert not before, "the test patient already has an active appointment; cancel it first"

    chat = Chat(client)
    try:
        # ---- book: identity, branch, day, button pick, reason, reconfirmation ----
        chat.say("I want to book a cardiology appointment")
        chat.verify_identity()
        chat.say("Anna Nagar")
        _hold_a_slot(chat, "Tuesday")
        chat.say("yes")                                        # confirm the held slot
        assert "reason for your visit" in chat.last["reply"].lower()
        assert chat.buttons, "visit types should be offered as buttons"
        chat.say("General Consultation")
        assert "just to confirm" in chat.last["reply"].lower()  # type, doctor, branch, time reconfirmed
        assert chat.buttons == ["yes", "no"]
        chat.say("yes")
        assert chat.last["booking_confirmed"] is True, chat.last["reply"]

        mine = _my_active_appointments(client, frontdesk_token)
        assert len(mine) == 1
        assert mine[0]["channel"] == "chat" and mine[0]["appointment_type"] == "General Consultation"

        # ---- one active appointment per patient ----
        chat.say("book another appointment with dermatology")
        assert "one active appointment" in chat.last["reply"].lower()
        chat.say("no")

        # ---- reschedule, keeping the day when only a time of day is given ----
        chat.say("reschedule my appointment to Wednesday")
        chat.say("afternoon")
        assert "wednesday" in chat.last["reply"].lower() and "pm" in chat.last["reply"].lower(), chat.last["reply"]
        chat.tap(0)
        assert "move your appointment" in chat.last["reply"].lower()
        chat.say("yes")
        assert chat.last["booking_confirmed"] is True, chat.last["reply"]
        assert "wednesday" in chat.last["reply"].lower()
        assert len(_my_active_appointments(client, frontdesk_token)) == 1

        # ---- cancel ----
        chat.say("cancel my appointment")
        chat.say("yes")
        assert "cancelled" in chat.last["reply"].lower()
        assert not _my_active_appointments(client, frontdesk_token)
    finally:
        # never leave a test booking behind, even when an assertion above failed
        if _my_active_appointments(client, frontdesk_token):
            cleanup = Chat(client)
            cleanup.say("cancel my appointment")
            cleanup.verify_identity()
            cleanup.say("yes")


def test_failed_identity_hands_over_to_the_front_desk_without_booking(client, frontdesk_token):
    chat = Chat(client)
    chat.say("I want to book an appointment")
    chat.say("Surendra, 1 January 1990")
    chat.say("Surendra, 2 February 1991")
    assert "front desk" in chat.last["reply"].lower()
    assert not _my_active_appointments(client, frontdesk_token)
