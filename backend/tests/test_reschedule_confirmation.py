import asyncio

import pytest

from src.control.agents.nodes.detect_intent import detect_intent_node
from src.control.agents.nodes.dialogue_guardrails import is_reschedule_confirmation
from src.control.agents.nodes.reschedule import (
    _slot_date_time_list,
    _slot_time_list,
    reschedule_agent_node,
)


def _held_reschedule_state(reply):
    slot = {
        "slot_id": "replacement-slot",
        "doctor_name": "Dr. Suresh Chandran",
        "location_name": "Velachery Branch",
        "start_time": "2026-10-27T04:30:00+00:00",
        "formatted_speech": "Dr. Suresh Chandran at Velachery Branch on Tuesday, October 27 at 10:00 AM",
    }
    return {
        "latest_user_speech": reply,
        "latest_agent_speech": "I can hold the proposed slot. Would you like me to move your appointment to that time?",
        "intent": "faq_response",
        "is_verified": True,
        "active_appointment_id": "active-appointment",
        "active_appointment_details": {
            "appointment_id": "active-appointment",
            "slot_id": "current-slot",
            "doctor_name": "Dr. Suresh Chandran",
            "location_name": "Velachery Branch",
            "specialty": "Orthopedics",
            "start_time": "2026-11-25T04:30:00+00:00",
        },
        "target_slot_id": slot["slot_id"],
        "target_slot_details": slot,
    }


def test_confirmation_is_routed_to_reschedule_even_after_intent_changed():
    state = _held_reschedule_state("ok do it")
    result = asyncio.run(detect_intent_node(state, None))
    assert result["intent"] == "reschedule"


def test_common_asr_transcription_of_yes_move_it_is_contextual_confirmation():
    assert is_reschedule_confirmation("yes move")
    state = _held_reschedule_state("yes move")
    result = asyncio.run(detect_intent_node(state, None))
    assert result["intent"] == "reschedule"


def test_unclear_reschedule_reply_keeps_existing_hold_and_does_not_search_again():
    state = _held_reschedule_state("book the appointment reschedule")
    result = asyncio.run(reschedule_agent_node(state, object()))

    assert result["target_slot_id"] == "replacement-slot"
    assert result["target_slot_details"] == state["target_slot_details"]
    assert "Please say yes" in result["latest_agent_speech"]


@pytest.mark.parametrize("message", ["October 28", "October 28 afternoon", "28"])
def test_reschedule_date_preferences_stay_in_reschedule_flow(message):
    state = {
        "latest_user_speech": message,
        "intent": "faq_response",
        "is_verified": True,
        "active_appointment_id": "active-appointment",
        "active_appointment_details": {"appointment_id": "active-appointment"},
        "awaiting_preferred_date": True,
    }

    result = asyncio.run(detect_intent_node(state, None))

    assert result["intent"] == "reschedule"


def test_reschedule_date_does_not_get_misread_as_doctor_name(monkeypatch):
    from src.control.agents.nodes import reschedule

    captured = {}

    async def fake_date_search(db, **kwargs):
        captured.update(kwargs)
        return []

    async def fake_doctor_search(doctor_name, db, limit=10):
        captured["fallback_doctor_name"] = doctor_name
        return []

    monkeypatch.setattr(reschedule, "get_slots_by_date_and_criteria", fake_date_search)
    monkeypatch.setattr(reschedule, "get_slots_by_doctor", fake_doctor_search)
    state = {
        "latest_user_speech": "I want to reset my appointment for the October 27th.",
        "intent": "reschedule",
        "is_verified": True,
        "patient_id": "patient-1",
        "conversation_id": "conversation-1",
        "active_appointment_id": "active-appointment",
        "active_appointment_details": {
            "appointment_id": "active-appointment",
            "slot_id": "current-slot",
            "doctor_name": "Dr. Lakshmi Narayanan",
            "location_name": "Tambaram Branch",
            "specialty": "General Medicine",
            "start_time": "2026-10-30T16:30:00+05:30",
        },
    }

    result = asyncio.run(reschedule.reschedule_agent_node(state, object()))

    assert captured["doctor_name"] == "Dr. Lakshmi Narayanan"
    assert captured["fallback_doctor_name"] == "Dr. Lakshmi Narayanan"
    assert "The October" not in result["latest_agent_speech"]


def test_reschedule_slot_lists_do_not_repeat_doctor_and_branch_for_every_time():
    slots = [
        {"start_time": "2026-10-27T04:00:00+00:00"},
        {"start_time": "2026-10-27T04:30:00+00:00"},
        {"start_time": "2026-10-27T05:00:00+00:00"},
    ]

    assert _slot_time_list(slots) == "9:30 AM, 10:00 AM, 10:30 AM"
    assert _slot_date_time_list(slots) == (
        "Tuesday, October 27 at 9:30 AM; Tuesday, October 27 at 10:00 AM; "
        "Tuesday, October 27 at 10:30 AM"
    )
