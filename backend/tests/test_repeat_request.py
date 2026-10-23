import asyncio

import pytest

from src.control.agents.nodes.detect_intent import detect_intent_node
from src.control.agents.nodes.dialogue_guardrails import is_repeat_request
from src.core.services.intent_classification_service import intent_classification_service


@pytest.fixture(autouse=True)
def offline_classifier(monkeypatch):
    async def classify(user_message, conversation_context=None, **_):
        return intent_classification_service._fallback_heuristic_classify(user_message)

    monkeypatch.setattr(intent_classification_service, "classify_intent", classify)


@pytest.mark.parametrize("text", [
    "i counldn't understad what u speaking",
    "I couldn't understand what you said",
    "I did not understand",
    "i can't understand you",
    "sorry?", "what", "pardon", "can you repeat that",
    "please say that again", "speak slowly please", "you are too fast", "that was confusing",
])
def test_repeat_requests_are_recognised(text):
    assert is_repeat_request(text)


@pytest.mark.parametrize("text", [
    "i want to book an appointment", "yes", "no", "cancel my appointment", "i understand",
    "what are your clinic timings", "what doctors are available",
])
def test_normal_messages_are_not_repeat_requests(text):
    assert not is_repeat_request(text)


def _turn(text, last="Are you sure you want to cancel your appointment?", **extra):
    state = {"latest_user_speech": text, "latest_agent_speech": last, "is_verified": True, **extra}
    return asyncio.run(detect_intent_node(state, None))


def test_repeat_says_last_message_again_and_keeps_flow_state():
    result = _turn("i counldn't understad what u speaking", awaiting_cancel_confirmation=True)
    assert "Are you sure you want to cancel your appointment?" in result["latest_agent_speech"]
    assert result["intent"] == "faq_response"
    assert "awaiting_cancel_confirmation" not in result  # flow flags untouched


def test_second_repeat_in_a_row_offers_simpler_options_instead_of_looping():
    first = _turn("repeat please")
    second = _turn("repeat please", last=first["latest_agent_speech"], last_repeat_speech=first["last_repeat_speech"])
    assert "front desk" in second["latest_agent_speech"]
    assert first["latest_agent_speech"] != second["latest_agent_speech"]


def test_emergency_is_not_swallowed_by_repeat_handling():
    result = _turn("i can't understand, i have severe chest pain")
    assert result["intent"] == "handoff"
