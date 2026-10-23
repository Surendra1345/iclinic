import asyncio
from datetime import date

from src.control.agents.nodes import _booking_discovery
from src.control.agents.nodes._booking_discovery import (
    _branch_availability_response,
    _slot_offer_response,
)


def test_branch_response_names_single_doctor_once_and_asks_for_date_time():
    response = _branch_availability_response(
        [
            {"doctor_name": "Dr. Lakshmi Narayanan", "start_time": "2026-10-25T03:30:00+00:00"},
            {"doctor_name": "Dr. Lakshmi Narayanan", "start_time": "2026-10-25T04:00:00+00:00"},
        ],
        location="Tambaram Branch",
        specialty="General Medicine",
    )

    assert response["latest_agent_speech"] == (
        "For General Medicine at our Tambaram branch, Dr. Lakshmi Narayanan is available. "
        "What date and time would you prefer?"
    )
    assert response["preferred_doctor"] == "Dr. Lakshmi Narayanan"
    assert response["offered_slots"] == []
    assert response["awaiting_preferred_date"] is True


def test_branch_response_lists_multiple_doctors_once_and_asks_patient_to_choose():
    response = _branch_availability_response(
        [
            {"doctor_name": "Dr. Lakshmi Narayanan"},
            {"doctor_name": "Dr. Lakshmi Narayanan"},
            {"doctor_name": "Dr. Harish Gautham"},
        ],
        location="Tambaram",
        specialty="General Medicine",
    )

    assert response["latest_agent_speech"] == (
        "For General Medicine at our Tambaram branch, available doctors are "
        "Dr. Lakshmi Narayanan and Dr. Harish Gautham. Which doctor, date, and time would you prefer?"
    )
    assert response["preferred_doctor"] is None


def test_selecting_offered_time_keeps_the_requested_date(monkeypatch):
    slots = [
        {
            "slot_id": "slot-4pm",
            "doctor_name": "Dr. Lakshmi Narayanan",
            "specialty": "General Medicine",
            "location_name": "Tambaram Branch",
            "start_time": "2026-10-29T10:30:00+00:00",
        },
        {
            "slot_id": "slot-430pm",
            "doctor_name": "Dr. Lakshmi Narayanan",
            "specialty": "General Medicine",
            "location_name": "Tambaram Branch",
            "start_time": "2026-10-29T11:00:00+00:00",
        },
    ]

    async def get_slots(*args, **kwargs):
        return slots

    async def reserve(*args, **kwargs):
        return None

    monkeypatch.setattr(_booking_discovery, "get_slots_by_date_and_criteria", get_slots)
    monkeypatch.setattr(_booking_discovery, "reserve_slot", reserve)

    async def journey():
        date_reply = await _booking_discovery.discover_booking_slots(
            state={"awaiting_preferred_date": True, "preferred_doctor": "Dr. Lakshmi Narayanan",
                   "preferred_location": "Tambaram", "preferred_specialty": "General Medicine"},
            db=None, user_speech="October 29 afternoon", lower_speech="october 29 afternoon",
            requested_time=None, requested_window=((12, 0), (16, 59)),
            has_date_in_speech=True, parsed_date_start=date(2026, 10, 29), alternative_date=None,
        )
        assert "Thursday, October 29" in date_reply["latest_agent_speech"]

        selected = await _booking_discovery.discover_booking_slots(
            state={"awaiting_preferred_date": True, **date_reply},
            db=None, user_speech="4:30", lower_speech="4:30",
            requested_time=(16, 30), requested_window=None,
            has_date_in_speech=False, parsed_date_start=None, alternative_date=None,
        )
        return selected

    selected = asyncio.run(journey())
    assert selected["target_slot_id"] == "slot-430pm"
    assert "Thursday, October 29 at 04:30 PM" in selected["latest_agent_speech"]


def test_afternoon_after_morning_offer_searches_saved_date_and_preserves_afternoon_options(monkeypatch):
    morning_slots = [
        {
            "slot_id": f"morning-{index}",
            "doctor_name": "Dr. Lakshmi Narayanan",
            "specialty": "General Medicine",
            "location_name": "Tambaram Branch",
            "start_time": f"2026-10-30T{hour:02d}:{minute:02d}:00+00:00",
        }
        for index, (hour, minute) in enumerate(
            [(3, 30), (4, 0), (4, 30), (5, 0), (5, 30), (6, 0)]
        )
    ]
    afternoon_slots = [
        {
            "slot_id": f"afternoon-{index}",
            "doctor_name": "Dr. Lakshmi Narayanan",
            "specialty": "General Medicine",
            "location_name": "Tambaram Branch",
            "start_time": f"2026-10-30T{hour:02d}:{minute:02d}:00+00:00",
        }
        for index, (hour, minute) in enumerate(
            [(8, 30), (9, 0), (9, 30), (10, 0), (10, 30)]
        )
    ]
    all_slots = morning_slots + afternoon_slots

    async def get_slots(_db, *, requested_time=None, requested_window=None, **_kwargs):
        if requested_window:
            return afternoon_slots
        if requested_time:
            return []
        return all_slots

    async def reserve(*_args, **_kwargs):
        return None

    monkeypatch.setattr(_booking_discovery, "get_slots_by_date_and_criteria", get_slots)
    monkeypatch.setattr(_booking_discovery, "reserve_slot", reserve)

    async def journey():
        initial_options = await _booking_discovery.discover_booking_slots(
            state={
                "awaiting_preferred_date": True,
                "preferred_doctor": "Dr. Lakshmi Narayanan",
                "preferred_location": "Tambaram Branch",
                "preferred_specialty": "General Medicine",
            },
            db=None,
            user_speech="October 30",
            lower_speech="october 30",
            requested_time=None,
            requested_window=None,
            has_date_in_speech=True,
            parsed_date_start=date(2026, 10, 30),
            alternative_date=None,
        )
        assert all("morning-" in slot["slot_id"] for slot in initial_options["offered_slots"])

        afternoon_options = await _booking_discovery.discover_booking_slots(
            state={"awaiting_preferred_date": True, **initial_options},
            db=None,
            user_speech="afternoon",
            lower_speech="afternoon",
            requested_time=None,
            requested_window=((12, 0), (16, 59)),
            has_date_in_speech=False,
            parsed_date_start=None,
            alternative_date=None,
        )
        assert all("afternoon-" in slot["slot_id"] for slot in afternoon_options["offered_slots"])
        assert "within your preferred range" in afternoon_options["latest_agent_speech"]

        unavailable_430 = await _booking_discovery.discover_booking_slots(
            state={"awaiting_preferred_date": True, **afternoon_options},
            db=None,
            user_speech="4:30",
            lower_speech="4:30",
            requested_time=(16, 30),
            requested_window=None,
            has_date_in_speech=False,
            parsed_date_start=None,
            alternative_date=None,
        )
        return afternoon_options, unavailable_430

    afternoon_options, unavailable_430 = asyncio.run(journey())
    assert "Friday, October 30" in afternoon_options["latest_agent_speech"]
    assert "02:00 PM" in afternoon_options["latest_agent_speech"]
    assert "04:00 PM" in afternoon_options["latest_agent_speech"]
    assert all("afternoon-" in slot["slot_id"] for slot in unavailable_430["offered_slots"])


def test_same_doctor_is_named_once_when_listing_multiple_openings():
    response = _slot_offer_response(
        [
            {
                "doctor_name": "Dr. Lakshmi Narayanan",
                "location_name": "Tambaram Branch",
                "start_time": "2026-10-25T03:30:00+00:00",
            },
            {
                "doctor_name": "Dr. Lakshmi Narayanan",
                "location_name": "Tambaram Branch",
                "start_time": "2026-10-25T04:00:00+00:00",
            },
            {
                "doctor_name": "Dr. Lakshmi Narayanan",
                "location_name": "Tambaram Branch",
                "start_time": "2026-10-25T04:30:00+00:00",
            },
        ],
        doctor="Dr. Lakshmi Narayanan",
        location="Tambaram Branch",
        specialty="General Medicine",
    )

    speech = response["latest_agent_speech"]
    assert speech.count("Dr. Lakshmi Narayanan") == 1
    assert speech.count("Tambaram") == 1
    assert "Sunday, October 25" in speech
    assert "9:00 AM, 9:30 AM, 10:00 AM" in speech


def test_direct_doctor_date_and_time_request_holds_that_exact_slot(monkeypatch):
    requested_slot = {
        "slot_id": "lakshmi-oct30-4pm",
        "doctor_name": "Dr. Lakshmi Narayanan",
        "specialty": "General Medicine",
        "location_name": "Tambaram Branch",
        "start_time": "2026-10-30T10:30:00+00:00",
    }
    reserved = []

    async def get_slots(*_args, **_kwargs):
        return [requested_slot]

    async def reserve(slot_id, _db):
        reserved.append(slot_id)

    monkeypatch.setattr(_booking_discovery, "get_slots_by_date_and_criteria", get_slots)
    monkeypatch.setattr(_booking_discovery, "reserve_slot", reserve)

    result = asyncio.run(_booking_discovery.discover_booking_slots(
        state={
            "awaiting_preferred_date": True,
            "preferred_doctor": "Dr. Lakshmi Narayanan",
            "preferred_location": "Tambaram Branch",
            "preferred_specialty": "General Medicine",
        },
        db=None,
        user_speech="Dr. Lakshmi Narayanan on October 30 at 4 PM",
        lower_speech="dr. lakshmi narayanan on october 30 at 4 pm",
        requested_time=(16, 0),
        requested_window=None,
        has_date_in_speech=True,
        parsed_date_start=date(2026, 10, 30),
        alternative_date=None,
    ))

    assert reserved == ["lakshmi-oct30-4pm"]
    assert result["target_slot_id"] == "lakshmi-oct30-4pm"
    assert result["latest_agent_speech"].count("Dr. Lakshmi Narayanan") == 1
    assert "Friday, October 30" in result["latest_agent_speech"]
    assert "04:00 PM" in result["latest_agent_speech"]
