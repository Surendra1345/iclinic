import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from src.control.agents.nodes.detect_intent import detect_intent_node
from src.control.agents.nodes.dialogue_guardrails import is_repeat_request
from src.control.agents.nodes.identity import identity_agent_node
from src.control.agents.tools.registration_tools import is_name_correction, name_from_speech
from src.control.agents.tools.slot_speech import day_availability_speech, period_from_request
from src.core.services.intent_classification_service import intent_classification_service

IST = ZoneInfo("Asia/Kolkata")


def _slots(times, doctor="Dr. Asha Rao", branch="Riverside Branch"):
    out = []
    for hour, minute in times:
        dt = datetime(2026, 10, 25, hour, minute, tzinfo=IST).astimezone(timezone.utc)
        out.append({"doctor_name": doctor, "location_name": branch, "start_time": dt.isoformat(), "slot_id": f"{hour}{minute}"})
    return out


MORNING_AND_AFTERNOON = _slots([(9, 0), (9, 30), (10, 0), (10, 30), (11, 0), (14, 0), (14, 30), (15, 0)])


def test_doctor_and_branch_are_said_once_not_per_slot():
    speech, _, _ = day_availability_speech(_slots([(9, 0), (9, 30), (10, 0)]), day_label="Sunday, October 25")
    assert speech.count("Dr. Asha Rao") == 1 and speech.count("Riverside") == 1
    assert "9:00, 9:30, 10:00 AM" in speech and "09:00" not in speech


def test_requested_period_lists_only_that_period():
    speech, offered, asks = day_availability_speech(MORNING_AND_AFTERNOON, day_label="Sunday", period="afternoon")
    assert "2:00, 2:30, 3:00 PM" in speech and "AM" not in speech
    assert len(offered) == 3 and not asks


def test_empty_period_says_so_and_suggests_the_periods_that_have_slots():
    speech, _, asks = day_availability_speech(MORNING_AND_AFTERNOON, day_label="Sunday", period="evening")
    assert "doesn't have evening slots" in speech
    assert "morning" in speech and "afternoon" in speech
    assert "a morning slot or an afternoon slot" in speech
    assert asks


def test_no_period_summarises_a_long_day_instead_of_reading_every_slot():
    speech, _, asks = day_availability_speech(MORNING_AND_AFTERNOON, day_label="Sunday")
    assert "morning (9:00 AM to 11:00 AM)" in speech and "afternoon (2:00 PM to 3:00 PM)" in speech
    assert "Which time of day" in speech and asks


def test_exact_time_without_a_slot_offers_the_closest_times_not_the_earliest():
    speech, offered, _ = day_availability_speech(MORNING_AND_AFTERNOON, day_label="Sunday", exact_time=(17, 0))
    assert "no opening at 5:00 PM" in speech
    assert [s["slot_id"] for s in offered] == ["140", "1430", "150"] or len(offered) == 3
    assert "9:00" not in speech


@pytest.mark.parametrize("text,expected", [("in the morning", "morning"), ("evening please", "evening"), ("afternoon", "afternoon"), ("hello", None)])
def test_period_is_read_from_the_patients_words(text, expected):
    assert period_from_request(text) == expected


@pytest.mark.parametrize("text,name", [
    ("Sonia", "Sonia"), ("my name is Sonia", "Sonia"), ("I am Sonia", "Sonia"),
    ("this is Sonia", "Sonia"), ("I'm Sonia Reddy", "Sonia Reddy"),
    ("I want to book", None), ("yes", None), ("I am new patient", None),
])
def test_names_are_accepted_with_or_without_an_introduction(text, name):
    assert name_from_speech(text) == name


@pytest.mark.parametrize("text", ["this is not my name", "that's not my name", "no that is wrong", "wrong name"])
def test_name_corrections_are_recognised(text):
    assert is_name_correction(text)


def _identity(text, **state):
    return asyncio.run(identity_agent_node({"latest_user_speech": text, "channel": "chat", **state}, None))


def test_patient_can_say_the_captured_name_is_wrong_and_give_another():
    result = _identity("this is not my name, my name is Meera", patient_name="Sonia")
    assert result["patient_name"] == "Meera" and result["patient_dob"] is None
    assert "date of birth" in result["latest_agent_speech"]


def test_patient_can_reject_the_name_and_be_asked_again():
    result = _identity("this is not my name", patient_name="Sonia")
    assert result["patient_name"] is None
    assert "full name" in result["latest_agent_speech"]


def test_my_name_is_x_asks_for_the_date_of_birth():
    result = _identity("my name is Sonia")
    assert result["patient_name"] == "Sonia" and "date of birth" in result["latest_agent_speech"]


@pytest.fixture
def offline_classifier(monkeypatch):
    async def classify(user_message, conversation_context=None, **_):
        return intent_classification_service._fallback_heuristic_classify(user_message)

    monkeypatch.setattr(intent_classification_service, "classify_intent", classify)


def test_introduced_name_and_correction_are_routed_to_identity(offline_classifier):
    for text in ("my name is Sonia", "this is not my name"):
        state = {"latest_user_speech": text, "latest_agent_speech": "What is your name?", "channel": "outbound_call"}
        assert asyncio.run(detect_intent_node(state, None))["intent"] == "identity"


@pytest.mark.parametrize("text", [
    "Yeah, can you please read that?", "yes can you repeat that", "tell me again", "pardon me",
    "can you speak louder", "okay sorry say that again", "what do you mean",
])
def test_more_repeat_phrases_including_a_leading_yeah(text):
    assert is_repeat_request(text)


@pytest.mark.parametrize("text", ["yes", "yeah", "yes please", "ok", "yes book it", "sure"])
def test_plain_agreement_is_not_a_repeat_request(text):
    assert not is_repeat_request(text)
