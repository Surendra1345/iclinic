import asyncio

import pytest

from src.control.agents.nodes.detect_intent import detect_intent_node
from src.core.services.intent_classification_service import intent_classification_service


@pytest.fixture(autouse=True)
def offline_classifier(monkeypatch):
    """Keep these tests deterministic: use the offline heuristic, never live Gemini."""
    async def classify(user_message, conversation_context=None, **_):
        return intent_classification_service._fallback_heuristic_classify(user_message)

    monkeypatch.setattr(intent_classification_service, "classify_intent", classify)

PROMPT = (
    "You already have an active appointment. Our clinic allows one active appointment per patient. "
    "Would you like to reschedule that appointment instead?"
)


def _run(text):
    state = {
        "latest_user_speech": text,
        "latest_agent_speech": PROMPT,
        "is_verified": True,
        "active_appointment_id": "appt-1",
    }
    return asyncio.run(detect_intent_node(state, None))


def test_cancel_with_typo_cancels():
    assert _run("cancle the appointment")["intent"] == "cancel"


def test_cancel_and_another_doctor_asks_which_action():
    result = _run("i want cancle this appointment and book for another doctor")
    assert result["awaiting_change_action_choice"] is True


def test_another_is_not_treated_as_no():
    assert "remains unchanged" not in (_run("another doctor please").get("latest_agent_speech") or "")


def test_bare_yes_reschedules_and_no_keeps():
    assert _run("yes")["intent"] == "reschedule"
    assert "remains unchanged" in _run("no")["latest_agent_speech"]
