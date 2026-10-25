import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from src.config.settings import settings
from src.control.agents.tools.registration_tools import dob_retry_message
from src.control.agents.tools.slot_speech import MAX_BUTTON_SLOTS, chat_options
from src.control.agents.tools.slot_tools import discussed_date_range, refers_to_discussed_day
from src.control.agents.tools.visit_type import resolve_visit_type, visit_type_question
from src.core.services import notification_service as notif
from src.utils.indic_lexicon import quick_english

IST = ZoneInfo("Asia/Kolkata")
TYPES = [
    "Dental Consultation", "Follow-up Consultation", "General Consultation",
    "Preventive Health Check", "Specialist Consultation",
]


def _slot(day, hour, minute=0):
    dt = datetime(2026, 10, day, hour, minute, tzinfo=IST).astimezone(timezone.utc)
    return {
        "start_time": dt.isoformat(), "slot_id": f"{day}-{hour}-{minute}", "doctor_name": "Dr. A",
        "location_name": "X Branch", "formatted_speech": f"Dr. A on October {day} at {hour}:{minute:02d}",
    }


# ---- discussed date ----------------------------------------------------------------------------

def test_discussed_date_is_resolved_from_saved_state():
    start, end = discussed_date_range("2026-10-27T09:00:00+05:30")
    assert start.astimezone(IST).date().isoformat() == "2026-10-27"
    assert end.astimezone(IST).date().isoformat() == "2026-10-27"


def test_no_saved_date_gives_no_range():
    assert discussed_date_range(None) == (None, None)


@pytest.mark.parametrize("text", ["that day please", "same day", "on that date"])
def test_that_day_refers_to_the_discussed_day(text):
    assert refers_to_discussed_day(text)


def test_plain_time_is_not_a_day_reference():
    assert not refers_to_discussed_day("the 3 o'clock slot")


# ---- date of birth message ---------------------------------------------------------------------

def test_future_dob_gets_a_specific_message():
    assert "doesn't look right" in dob_retry_message("my dob is 14 August 2999")


def test_speech_without_a_date_has_no_dob_message():
    assert dob_retry_message("I would like to book") is None


def test_valid_dob_has_no_retry_message():
    assert dob_retry_message("14 August 2004") is None


# ---- Tamil / Telugu short answers --------------------------------------------------------------

@pytest.mark.parametrize("text, english", [
    ("ஆம்", "yes"), ("అవును.", "yes"), ("illai", "no"), ("వద్దు", "no"), ("நன்றி", "thank you"),
])
def test_common_indic_answers_are_translated_offline(text, english):
    assert quick_english(text) == english


def test_longer_indic_sentence_is_left_to_the_translator():
    assert quick_english("எனக்கு நாளை அப்பாயின்ட்மெண்ட் வேண்டும்") is None


# ---- chat quick replies ------------------------------------------------------------------------

def test_one_day_gives_a_button_per_time():
    options = chat_options([_slot(27, 15), _slot(27, 9, 30)])
    assert [o["label"] for o in options] == ["9:30 AM", "3:00 PM"]
    assert options[0]["message"] == "9:30 AM"


def test_several_days_include_the_date_in_the_message():
    options = chat_options([_slot(27, 9), _slot(28, 9)])
    assert options[0]["message"] == "9:00 AM on 27 October"
    assert options[1]["label"].startswith("Wed 28 Oct")


def test_many_slots_collapse_to_period_buttons():
    slots = [_slot(27, 9, 5 * i) for i in range(MAX_BUTTON_SLOTS)] + [_slot(27, 14)]
    options = chat_options(slots)
    assert [o["message"] for o in options] == ["morning", "afternoon"]


def test_no_slots_no_buttons():
    assert chat_options(None) == [] and chat_options([]) == []


# ---- visit type --------------------------------------------------------------------------------

@pytest.mark.parametrize("speech, expected", [
    ("general consultation please", "General Consultation"),
    ("I need a dental appointment", "Dental Consultation"),
    ("this is a follow-up", "Follow-up Consultation"),
    ("just a routine checkup", "Preventive Health Check"),
    ("I want to see a specialist", "Specialist Consultation"),
    ("I have a fever and cough", None),
    ("I need to update my records", None),
])
def test_visit_type_is_matched_from_configured_names(speech, expected):
    assert resolve_visit_type(speech, TYPES) == expected


def test_question_lists_every_configured_type():
    question = visit_type_question(TYPES)
    assert all(name in question for name in TYPES) and "reason" in question


# ---- notification retries and content ----------------------------------------------------------

class _Repo:
    def __init__(self):
        self.sent, self.failed = [], []

    async def create_notification(self, **kwargs):
        return SimpleNamespace(id="n1")

    async def mark_sent(self, nid, provider_response=None):
        self.sent.append(nid)

    async def mark_failed(self, nid, error_detail=""):
        self.failed.append(error_detail)


class _Twilio:
    def __init__(self, fail_times):
        self.calls, self.fail_times, self.messages = 0, fail_times, []

    def send_sms(self, to, message):
        self.calls += 1
        self.messages.append(message)
        if self.calls <= self.fail_times:
            raise RuntimeError("temporary outage")
        return {"sid": "SM1"}


def _service(fail_times, monkeypatch):
    monkeypatch.setattr(settings, "NOTIFICATION_RETRY_ATTEMPTS", 3)
    monkeypatch.setattr(settings, "NOTIFICATION_RETRY_DELAY_SECONDS", 0)
    service = notif.NotificationService.__new__(notif.NotificationService)
    service.notification_repo, service.twilio_service = _Repo(), _Twilio(fail_times)
    return service


def _send(service, **extra):
    return asyncio.run(service.send_confirmation_sms(
        appointment_id="a1", to_phone="+910000000000", patient_name="Sam", doctor_name="Dr. A",
        start_time_str="Mon 9 AM", **extra,
    ))


def test_sms_is_retried_until_it_goes_through(monkeypatch):
    service = _service(2, monkeypatch)
    assert _send(service) is True
    assert service.twilio_service.calls == 3 and service.notification_repo.sent


def test_sms_failure_is_recorded_after_the_last_attempt(monkeypatch):
    service = _service(10, monkeypatch)
    assert _send(service) is False
    assert service.twilio_service.calls == 3
    assert service.notification_repo.failed and not service.notification_repo.sent


def test_sms_carries_branch_type_and_instructions(monkeypatch):
    service = _service(0, monkeypatch)
    _send(service, location_name="T. Nagar Branch", appointment_type="General Consultation", instructions="Arrive early")
    message = service.twilio_service.messages[0]
    assert "T. Nagar Branch" in message and "General Consultation" in message and "Arrive early" in message


def test_cancellation_sms_has_no_visit_details(monkeypatch):
    service = _service(0, monkeypatch)
    _send(service, action="cancelled", location_name="T. Nagar Branch", instructions="Arrive early")
    assert "Arrive early" not in service.twilio_service.messages[0]


def test_email_body_lists_the_visit_details():
    _, body = notif.NotificationService._build_email_content(
        patient_name="Sam", doctor_name="Dr. A", start_time_str="Mon 9 AM", action="booked",
        location_name="T. Nagar Branch", appointment_type="Dental Consultation", instructions="Bring X-rays",
    )
    assert "Branch: T. Nagar Branch" in body and "Visit type: Dental Consultation" in body and "Bring X-rays" in body


# ---- outbound call allowlist -------------------------------------------------------------------

def test_call_allowlist_is_off_unless_configured(monkeypatch):
    from src.api.rest.routes.voice import _call_allowed

    monkeypatch.setattr(settings, "OUTBOUND_CALL_ALLOWED_NUMBERS", "")
    assert _call_allowed("+919876543210")
    monkeypatch.setattr(settings, "OUTBOUND_CALL_ALLOWED_NUMBERS", "+91 98765 43210, +919000000001")
    assert _call_allowed("+919876543210") and _call_allowed("+919000000001")
    assert not _call_allowed("+919111111111")


# ---- visit-type step inside the held-slot dialogue ---------------------------------------------

def _held_slot_call(monkeypatch, speech, state_extra):
    from src.control.agents.nodes import _booking_held_slot as held

    booked = {}

    async def fake_names(db):
        return TYPES

    async def fake_execute(**kwargs):
        booked.update(kwargs)
        return {"booking_confirmed": True}

    monkeypatch.setattr(held, "active_visit_names", fake_names)
    monkeypatch.setattr(held, "_execute_booking", fake_execute)
    slot = {**_slot(27, 9), "specialty": "General Medicine"}
    state = {"channel": "chat", "patient_name": "Sam Rao", "patient_email": "sam@example.com", **state_extra}
    result = asyncio.run(held.handle_held_slot(
        state=state, db=None, user_speech=speech, lower_speech=speech.lower(), target_slot=slot,
        target_slot_id=slot["slot_id"], requested_time=None, requested_window=None, has_date_in_speech=False,
        patient_id=None, patient_name="Sam Rao", patient_email="sam@example.com", convo_id=None, repo=None,
    ))
    return result, booked


def test_chat_confirmation_first_asks_for_the_visit_reason(monkeypatch):
    result, booked = _held_slot_call(monkeypatch, "yes", {})
    assert result["awaiting_appointment_type"] is True and "reason for your visit" in result["latest_agent_speech"]
    assert not booked


def test_naming_a_type_reconfirms_it_then_books_that_type(monkeypatch):
    result, booked = _held_slot_call(monkeypatch, "a dental visit", {"awaiting_appointment_type": True})
    assert not booked
    assert result["preferred_appointment_type"] == "Dental Consultation"
    assert "Just to confirm: a Dental Consultation" in result["latest_agent_speech"]
    _, booked = _held_slot_call(monkeypatch, "yes", {"preferred_appointment_type": "Dental Consultation"})
    assert booked["appointment_type_name"] == "Dental Consultation" and booked["reason"] is None


def test_giving_only_a_reason_reconfirms_the_default_type_and_keeps_the_reason(monkeypatch):
    result, booked = _held_slot_call(monkeypatch, "I have had a fever for two days", {"awaiting_appointment_type": True})
    assert not booked
    assert result["preferred_appointment_type"] == "General Consultation"
    assert result["visit_reason"] == "I have had a fever for two days"
    _, booked = _held_slot_call(
        monkeypatch, "yes",
        {"preferred_appointment_type": "General Consultation", "visit_reason": "I have had a fever for two days"},
    )
    assert booked["appointment_type_name"] == "General Consultation"
    assert booked["reason"] == "I have had a fever for two days"


def test_every_channel_is_asked_for_the_visit_type(monkeypatch):
    for channel in ("chat", "voice_assistant", "outbound_call"):
        result, booked = _held_slot_call(monkeypatch, "yes", {"channel": channel})
        assert result["awaiting_appointment_type"] is True and not booked, channel


# ---- reschedule keeps the date being discussed -------------------------------------------------

def _reschedule(monkeypatch, speech, preferred_date, extra=None):
    from src.control.agents.nodes import reschedule as r

    searched = {}

    async def fake_by_date(db, date_query=None, **kwargs):
        searched["date_query"] = date_query
        return [_slot(28, 15), _slot(28, 9)]

    async def fake_noop(*args, **kwargs):
        return None

    monkeypatch.setattr(r, "get_slots_by_date_and_criteria", fake_by_date)
    monkeypatch.setattr(r, "release_slot", fake_noop)
    monkeypatch.setattr(r, "reserve_slot", fake_noop)
    far = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
    state = {
        "latest_user_speech": speech, "patient_id": "p1", "conversation_id": "c1",
        "preferred_date": preferred_date,
        **(extra or {}),
        "active_appointment_details": {
            "appointment_id": "a1", "slot_id": "old", "start_time": far, "doctor_name": "Dr. A",
            "location_name": "X Branch", "specialty": "General Medicine",
        },
    }
    result = asyncio.run(r.reschedule_agent_node(state, None))
    return result, searched


def test_bare_time_uses_the_date_already_discussed(monkeypatch):
    result, searched = _reschedule(monkeypatch, "the 3 o'clock slot", "2026-10-28")
    assert searched["date_query"] == "2026-10-28"
    assert result["target_slot_details"]["slot_id"] == "28-15-0"
    assert result["preferred_date"] == "2026-10-28"


def test_bare_time_without_a_discussed_date_does_not_search_one_date(monkeypatch):
    class _Db:
        pass

    from src.control.agents.nodes import reschedule as r

    async def fake_by_doctor(*args, **kwargs):
        return []

    async def fake_loc(*args, **kwargs):
        return []

    monkeypatch.setattr(r, "get_slots_by_doctor", fake_by_doctor)
    monkeypatch.setattr(r, "get_slots_by_specialty_and_location", fake_loc)
    result, searched = _reschedule(monkeypatch, "the 3 o'clock slot", None)
    assert "date_query" not in searched


def test_a_clock_time_is_not_mistaken_for_a_day_of_the_month():
    from src.control.agents.tools.slot_tools import has_date_reference, parse_date_query_to_range

    for speech in ("the 3 o'clock slot", "the 3 pm slot", "on the 10:30 one"):
        assert parse_date_query_to_range(speech) == (None, None), speech
        assert not has_date_reference(speech), speech
    start, _ = parse_date_query_to_range("on the 3rd")
    assert start is not None and has_date_reference("on the 3rd")


# ---- Tamil / Telugu translation helpers --------------------------------------------------------

def test_short_tamil_answer_needs_no_translation_call(monkeypatch):
    from src.api.rest.routes import voice_assistant as va

    async def boom(*args, **kwargs):
        raise AssertionError("the translator must not be called for a plain yes")

    monkeypatch.setattr(va.gemini_service, "generate_content", boom)
    assert asyncio.run(va._to_english("ஆம்", "ta-IN")) == "yes"


def test_translation_is_retried_once_then_reported(monkeypatch):
    from src.api.rest.routes import voice_assistant as va

    monkeypatch.setattr(settings, "VOICE_ASSISTANT_TRANSLATION_ATTEMPTS", 2)
    calls = []

    async def flaky(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            raise RuntimeError("503")
        return "  வணக்கம்  "

    monkeypatch.setattr(va.gemini_service, "generate_content", flaky)
    assert asyncio.run(va._translate("Hello", "ta-IN")) == "வணக்கம்"
    assert len(calls) == 2

    async def always_down(prompt, **kwargs):
        raise RuntimeError("quota")

    monkeypatch.setattr(va.gemini_service, "generate_content", always_down)
    with pytest.raises(RuntimeError, match="translation unavailable"):
        asyncio.run(va._translate("Hello", "te-IN"))


# ---- routing when the classifier is unsure or unavailable --------------------------------------

@pytest.fixture
def unsure_classifier(monkeypatch):
    from src.control.agents.nodes.detect_intent import intent_classification_service
    from src.core.services.intent_classification_service import IntentClassificationResult, IntentLabel

    async def classify(user_message, conversation_context=None):
        return IntentClassificationResult(intent=IntentLabel.UNKNOWN, confidence="low", needs_clarification=True)

    monkeypatch.setattr(intent_classification_service, "classify_intent", classify)


def _route(state):
    from src.control.agents.nodes.detect_intent import detect_intent_node

    return asyncio.run(detect_intent_node(state, None))


def test_unclear_question_goes_to_the_grounded_faq_answer(unsure_classifier):
    for text in ("What is the capital of France?", "do you have parking", "Hi, what can you help me with?"):
        assert _route({"latest_user_speech": text, "channel": "chat"})["intent"] == "faq", text


def test_plain_yes_with_a_held_slot_confirms_the_booking(unsure_classifier):
    state = {"latest_user_speech": "yes", "intent": "book", "target_slot_id": "s1", "channel": "chat"}
    assert _route(state)["intent"] == "book"


def test_unclear_reply_with_a_held_slot_stays_in_the_booking(unsure_classifier):
    state = {"latest_user_speech": "hmm maybe", "intent": "reschedule", "target_slot_id": "s1", "is_verified": True, "channel": "chat"}
    assert _route(state)["intent"] == "reschedule"


def test_a_reply_with_a_date_continues_the_booking_already_started(unsure_classifier):
    state = {"latest_user_speech": "Wednesday morning", "intent": "book", "is_verified": True, "channel": "chat"}
    assert _route(state)["intent"] == "book"


# ---- availability answers stay short when many doctors match ------------------------------------

def _many_doctors(count, hour=9):
    slots = []
    for i in range(count):
        slot = _slot(25, hour)
        slot.update({"doctor_name": f"Dr. {i}", "location_name": f"{'AB'[i % 2]} Branch", "slot_id": f"d{i}"})
        slots.append(slot)
    return slots


def test_many_doctors_are_summarised_by_branch_not_listed_one_by_one():
    from src.control.agents.tools.slot_speech import day_availability_speech

    speech, offered, asks = day_availability_speech(_many_doctors(8), day_label="Sunday, October 25", period="morning")
    assert "8 doctors have morning openings" in speech and "A (4 doctors" in speech and "Dr. 3" not in speech
    assert len(offered) == 8 and asks


def test_many_doctors_with_no_slots_in_the_asked_period_stay_short():
    from src.control.agents.tools.slot_speech import day_availability_speech

    speech, _, _ = day_availability_speech(_many_doctors(8), day_label="Sunday", period="afternoon")
    assert speech.startswith("No doctors have afternoon slots on Sunday") and "Dr. 3" not in speech


def test_slot_count_and_earliest_questions_go_to_the_grounded_answer(unsure_classifier):
    from src.control.agents.nodes.detect_intent import _handle_doctor_availability_query

    class _Db:
        async def scalars(self, *_args, **_kwargs):
            class _R:
                def all(self):
                    return []
            return _R()

    for text in ("How many slots does Dr. Arjun have on Monday?", "What is the earliest slot for dermatology?"):
        result = asyncio.run(_handle_doctor_availability_query(_Db(), None, text))
        assert result["intent"] == "faq", text


def test_a_period_word_after_a_day_listing_keeps_that_day(monkeypatch):
    offered = [_slot(28, h) for h in (9, 10, 11)] + [_slot(28, h) for h in (14, 15, 16)]
    result, searched = _reschedule(monkeypatch, "afternoon", "2026-10-28", {"offered_slots": offered, "awaiting_preferred_date": True})
    assert searched["date_query"] == "2026-10-28"
    assert "Sunday" not in result["latest_agent_speech"] and result["preferred_date"] == "2026-10-28"


# ---- final fixes: other doctor, unclear twice, wrong person, confirmation status, step log -------

def test_confirmation_is_flagged_when_any_attempted_message_fails():
    from src.constants.enums import ConfirmationStatusType as C
    from src.control.agents.nodes.confirmation import _confirmation_status

    assert _confirmation_status(True, True, True, True) == C.SENT
    assert _confirmation_status(True, False, True, True) == C.FLAGGED   # SMS failed, email went out
    assert _confirmation_status(False, False, True, True) == C.SENT     # no phone on file is not a failure
    assert _confirmation_status(True, False, False, False) == C.FLAGGED


def test_conversation_state_log_can_record_confirmation_sent():
    from src.constants.enums import ConversationState

    assert ConversationState.CONFIRMATION_SENT.value == "confirmation_sent"


def test_step_log_records_input_output_and_result():
    from src.core.services.conversation_turn_service import ConversationTurnService as T

    ok = T._step_log({"intent": "book", "is_verified": True}, "chat", None, 0.25, "I want to book on 14-12-2003", "Which branch?")
    assert ok["result"] == "success" and ok["output"] == "Which branch?" and ok["elapsed_ms"] == 250
    assert "14-12-2003" not in ok["input"]
    assert T._step_log({}, "chat", "graph", 1.0, "x", "sorry")["result"] == "error"
    assert T._step_log({}, "chat", None, 1.0, "x", "I didn't quite understand that")["result"] == "warning"
    assert T._step_log({"handoff_required": True}, "chat", None, 1.0, "x", "connecting you")["result"] == "warning"


def test_asking_for_another_doctor_mid_booking_stays_in_the_booking(unsure_classifier):
    for text in ("any other doctor for cardiology?", "can I see someone else"):
        state = {"latest_user_speech": text, "intent": "book", "is_verified": True}
        assert _route(state)["intent"] == "book", text


def test_second_unclear_reply_offers_the_front_desk(unsure_classifier):
    state = {
        "latest_user_speech": "blah blah", "channel": "chat", "is_verified": True,
        "latest_agent_speech": "I didn\u2019t quite understand that. Could you rephrase your question?",
    }
    speech = _route(state)["latest_agent_speech"]
    assert "front desk" in speech and "still having trouble" in speech
    first = _route({"latest_user_speech": "blah blah", "channel": "chat", "is_verified": True})
    assert "front desk" not in first["latest_agent_speech"]


def test_wrong_person_on_an_outbound_call_ends_the_call_without_booking(unsure_classifier):
    for text in ("sorry wrong number", "you have the wrong person", "I don't know anyone by that name"):
        result = _route({"latest_user_speech": text, "channel": "outbound_call"})
        assert result["intent"] == "close" and result["wrong_person"] is True, text
    # the same words in chat are not treated as a wrong-person call
    assert "wrong_person" not in _route({"latest_user_speech": "sorry wrong number", "channel": "chat"})


def test_wrong_person_is_recorded_as_the_call_outcome():
    from src.constants.enums import OutcomeType
    from src.control.agents.nodes import end_call

    closed = {}

    class _Repo:
        def __init__(self, db): pass
        async def get(self, _id): return None
        async def mark_ended(self, _id): pass
        async def close(self, conversation_id, outcome, **_): closed["outcome"] = outcome

    original = end_call.ConversationRepository
    end_call.ConversationRepository = _Repo
    try:
        result = asyncio.run(end_call.end_call_node(
            {"conversation_id": "00000000-0000-0000-0000-000000000001", "wrong_person": True,
             "latest_agent_speech": "I'm sorry for the mix-up."}, None))
    finally:
        end_call.ConversationRepository = original
    assert closed["outcome"] == OutcomeType.WRONG_PERSON and "mix-up" in result["latest_agent_speech"]


def test_several_doctors_get_doctor_buttons_and_many_doctors_get_branch_buttons():
    few = chat_options(_many_doctors(3))
    assert [o["message"] for o in few] == ["Dr. 0", "Dr. 1", "Dr. 2"]
    many = chat_options(_many_doctors(8))
    assert [o["message"] for o in many] == ["A", "B"]


def test_speech_to_text_numbers_like_930_are_read_as_times_but_years_are_not():
    from src.control.agents.nodes.booking_helpers import _extract_time_of_day

    assert _extract_time_of_day("930") == (9, 30)
    assert _extract_time_of_day("1030") == (10, 30)
    assert _extract_time_of_day("200") == (14, 0)
    assert _extract_time_of_day("2026") is None
    assert _extract_time_of_day("1990") is None
    assert _extract_time_of_day("my number is 930 1234") is None


def test_english_voice_session_turns_indic_script_back_into_english(monkeypatch):
    from src.api.rest.routes import voice_assistant as va

    seen = {}

    async def fake_translate(prompt):
        seen["prompt"] = prompt
        return "Dr. Rajesh Kannan"

    monkeypatch.setattr(va, "_gemini_translate", fake_translate)
    assert va._INDIC_SCRIPT.search("டாக்டர் ராஜேஷ் கண்ணன்") and va._INDIC_SCRIPT.search("कैंसिल माय अपॉइंटमेंट")
    assert not va._INDIC_SCRIPT.search("Dr. Rajesh Kannan")
    assert asyncio.run(va._english_from_indic_script("டாக்டர் ராஜேஷ் கண்ணன்")) == "Dr. Rajesh Kannan"
    assert "டாக்டர் ராஜேஷ் கண்ணன்" in seen["prompt"]


# ---- reschedule: another doctor across branches, and no repeated doctor list ---------------------

def test_reschedule_another_doctor_checks_every_branch(monkeypatch):
    from src.control.agents.nodes import reschedule as r

    async def fake_by_date(db, date_query=None, **kwargs):
        assert kwargs.get("location_name") is None   # no branch named: look everywhere
        return [
            {**_slot(28, 9), "doctor_name": "Dr. Rajesh Kannan", "location_name": "Anna Nagar Branch", "slot_id": "a"},
            {**_slot(28, 9), "doctor_name": "Dr. Harish Gautham", "location_name": "Tambaram Branch", "slot_id": "b"},
        ]

    monkeypatch.setattr(r, "get_slots_by_date_and_criteria", fake_by_date)

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(r, "release_slot", noop)
    far = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
    state = {
        "latest_user_speech": "i want to book for another doctor", "patient_id": "p", "conversation_id": "c",
        "active_appointment_details": {
            "appointment_id": "a1", "slot_id": "old", "start_time": far, "doctor_name": "Dr. Rajesh Kannan",
            "location_name": "Anna Nagar Branch", "specialty": "Cardiology",
        },
    }
    result = asyncio.run(r.reschedule_agent_node(state, None))
    speech = result["latest_agent_speech"]
    assert "Dr. Harish Gautham at Tambaram" in speech and "Rajesh" not in speech
    assert "Branch branch" not in speech and result["preferred_doctor"] is None


def test_a_branch_reply_after_a_browsing_answer_continues_the_reschedule_not_the_old_answer(unsure_classifier):
    class _Result:
        def __init__(self, values): self._values = values
        def scalars(self): return self
        def all(self): return self._values

    class _Db:
        async def execute(self, statement):
            text = str(statement)
            return _Result(["Anna Nagar Branch", "Tambaram Branch"] if "locations" in text else ["Dr. Harish Gautham"])

    from src.control.agents.nodes.detect_intent import detect_intent_node

    state = {
        "latest_user_speech": "Tambaram", "intent": "faq_response", "pending_intent": "reschedule",
        "is_verified": True, "awaiting_preferred_date": True, "channel": "chat",
        "active_appointment_id": "a1", "active_appointment_details": {"appointment_id": "a1"},
    }
    assert asyncio.run(detect_intent_node(state, _Db()))["intent"] == "reschedule"


# ---- chat buttons for branch / doctor / visit type / yes-no questions ----------------------------

def _choices(speech):
    from src.control.agents.tools.chat_choices import reply_choices

    return reply_choices(
        speech,
        branch_names=["Anna Nagar Branch", "T. Nagar Branch", "Tambaram Branch", "Velachery Branch"],
        visit_types=["Dental Consultation", "General Consultation"],
    )


def test_branch_question_offers_the_branches_named_in_the_reply():
    speech = "For Cardiology, available doctors are Dr. A B at Tambaram, Dr. C D at Anna Nagar. Which branch would you prefer?"
    assert [c["message"] for c in _choices(speech)] == ["Anna Nagar", "Tambaram"]
    generic = [c["message"] for c in _choices("Which clinic branch would you prefer?")]
    assert generic == ["Anna Nagar", "T. Nagar", "Tambaram", "Velachery"]


def test_doctor_question_offers_the_doctors_in_the_reply():
    speech = "Other Cardiology doctors are Dr. Harish Gautham at Tambaram, Dr. Sandeep Kumar at Velachery. Which doctor would you prefer?"
    assert [c["message"] for c in _choices(speech)] == ["Dr. Harish Gautham", "Dr. Sandeep Kumar"]


def test_visit_reason_question_offers_the_visit_types():
    assert [c["message"] for c in _choices("Before I confirm, what is the reason for your visit?")] == [
        "Dental Consultation", "General Consultation",
    ]


def test_confirmation_questions_get_yes_and_no_but_open_questions_do_not():
    for speech in ("Shall I book it?", "Are you sure you want to cancel your appointment?",
                   "Would you like me to move your appointment to that time?"):
        assert [c["message"] for c in _choices(speech)] == ["yes", "no"], speech
    assert _choices("What date works best for you?") == []
    assert _choices("Your appointment has been booked. Would you like help with anything else?") == []


# ---- specialty words are not names; "ok" is acknowledged; one-branch specialties --------------------

def test_a_specialty_or_branch_word_is_not_taken_as_a_patient_name(monkeypatch):
    from src.control.agents.tools import clinic_directory
    from src.control.agents.tools.registration_tools import is_name_only_candidate

    monkeypatch.setattr(clinic_directory, "all_specialties", lambda: ["Cardiology", "Gynecology"])
    monkeypatch.setattr(
        clinic_directory, "match_branch",
        lambda text: "Velachery Branch" if "velachery" in text.lower() else None,
    )
    for word in ("Gynecology", "gynaecology", "Cardiology", "Velachery"):
        assert not is_name_only_candidate(word), word
    assert is_name_only_candidate("Surendra") and is_name_only_candidate("Priya Nair")


def test_ok_after_an_answer_is_acknowledged_not_misunderstood(unsure_classifier):
    reply = _route({"latest_user_speech": "ok", "channel": "chat",
                    "latest_agent_speech": "City Care Clinic is open from 09:00 to 18:00 local time."})
    assert reply["intent"] == "faq_response" and "anything else" in reply["latest_agent_speech"]
    # but "ok" answering a question is not swallowed here
    after_question = _route({"latest_user_speech": "ok", "channel": "chat", "is_verified": True, "intent": "book",
                             "target_slot_id": "s1", "latest_agent_speech": "Shall I book it?"})
    assert "anything else" not in after_question.get("latest_agent_speech", "")


def test_specialty_with_doctors_at_one_branch_does_not_ask_which_branch():
    from src.control.agents.nodes.detect_intent import _handle_doctor_availability_query

    class _Loc:
        id = "l1"; name = "Tambaram Branch"

    class _Doc:
        full_name = "Dr. Vivek Sharma"; specialty = "ENT"; location = _Loc(); location_id = "l1"

    class _Db:
        async def scalars(self, *_a, **_k):
            class _R:
                def all(self): return [_Doc()]
            return _R()

    result = asyncio.run(_handle_doctor_availability_query(_Db(), "ENT", "what are the doctors available for the ENT"))
    assert "Which branch" not in result["latest_agent_speech"]
    assert "Dr. Vivek Sharma is available at our Tambaram branch" in result["latest_agent_speech"]
    assert result["preferred_location"] == "Tambaram Branch"


# ---- edge cases: bare yes/no, walking away, two-digit year, nearest times -----------------------

def test_lone_yes_or_no_with_nothing_pending_gets_a_clear_reply(unsure_classifier):
    yes = _route({"latest_user_speech": "yes", "channel": "chat"})["latest_agent_speech"]
    no = _route({"latest_user_speech": "no", "channel": "chat"})["latest_agent_speech"]
    assert "not sure what you are saying yes to" in yes and "No problem" in no


def test_walking_away_mid_booking_stops_it_and_frees_the_hold(unsure_classifier, monkeypatch):
    from src.control.agents.nodes import detect_intent as di

    released = []

    async def fake_release(slot_id, db):
        released.append(slot_id)

    monkeypatch.setattr(di, "release_slot", fake_release)
    state = {"latest_user_speech": "forget it, I will call later", "intent": "book", "is_verified": True,
             "target_slot_id": "s1", "channel": "chat"}
    result = _route(state)
    assert released == ["s1"] and result["target_slot_id"] is None and "stopped the booking" in result["latest_agent_speech"]


def test_two_digit_year_date_of_birth_asks_for_the_full_year():
    assert "four-digit year" in dob_retry_message("Surendra, 03-09-04")
    assert dob_retry_message("14-12-2003") is None


# ---- final edge cases: gibberish names, booking for someone else, past dates ---------------------

def test_keyboard_mashing_is_not_a_name_but_real_names_are():
    from src.control.agents.tools.registration_tools import is_name_only_candidate, looks_like_gibberish

    for junk in ("asdf qwer zxcv", "qwerty", "aaaa", "xkcdfgh", "hjkl"):
        assert looks_like_gibberish(junk) and not is_name_only_candidate(junk), junk
    for name in ("Surendra", "Lakshmi Narayanan", "Priya Nair", "Krishnamurthy", "Sandhya Rani", "Ashwin Balaji", "Ng Wei"):
        assert not looks_like_gibberish(name), name


def test_booking_for_someone_else_is_explained_not_started(unsure_classifier):
    for text in ("I want to book an appointment for my mother", "please schedule a visit for my son",
                 "can you make an appointment for my friend"):
        reply = _route({"latest_user_speech": text, "channel": "chat"})["latest_agent_speech"]
        assert "only book for the patient who is verified" in reply and "front desk" in reply, text
    # asking about services for family is just a question, not a booking
    assert "only book for the patient" not in str(
        _route({"latest_user_speech": "do you have a pediatrician for my son?", "channel": "chat"})
    )


def test_a_date_that_has_passed_is_called_out(unsure_classifier):
    from src.control.agents.tools.slot_tools import refers_to_past_date

    assert refers_to_past_date("yesterday") and refers_to_past_date("last Monday") and refers_to_past_date("2020-01-05")
    assert refers_to_past_date("12-03-2021") and not refers_to_past_date("tomorrow") and not refers_to_past_date("2099-01-05")
    state = {"latest_user_speech": "yesterday", "intent": "book", "is_verified": True, "channel": "chat"}
    assert "already passed" in _route(state)["latest_agent_speech"]
    # a date of birth typed while identity is being checked is never treated as a past appointment date
    unverified = {"latest_user_speech": "Surendra, 14-12-2003", "intent": "book", "channel": "chat"}
    assert "already passed" not in str(_route(unverified))


def test_unverified_nonsense_gets_a_name_prompt_and_normal_words_are_not_nonsense(unsure_classifier):
    from src.control.agents.tools.registration_tools import is_all_gibberish

    reply = _route({"latest_user_speech": "asdf qwer zxcv", "channel": "chat"})["latest_agent_speech"]
    assert "couldn't make that out" in reply and "full name" in reply
    for fine in ("what are my strengths", "hmm", "I want to book", "Lakshmi Narayanan"):
        assert not is_all_gibberish(fine), fine


def test_repeated_past_dates_keep_being_called_out(unsure_classifier):
    first = _route({"latest_user_speech": "yesterday", "intent": "book", "is_verified": True, "channel": "chat"})
    assert first["awaiting_preferred_date"] is True
    again = _route({"latest_user_speech": "last Monday", "intent": "faq_response", "pending_intent": "book",
                    "awaiting_preferred_date": True, "is_verified": True, "channel": "chat"})
    assert "already passed" in again["latest_agent_speech"]


def test_nearest_times_for_several_doctors_read_naturally():
    from src.control.agents.tools.slot_speech import day_availability_speech

    slots = [
        {**_slot(25, 9), "doctor_name": "Dr. A", "location_name": "X Branch", "slot_id": "1"},
        {**_slot(25, 10), "doctor_name": "Dr. B", "location_name": "Y Branch", "slot_id": "2"},
    ]
    speech, _, _ = day_availability_speech(slots, day_label="Sunday", exact_time=(7, 0))
    assert "On that day" not in speech and "Dr. A at X, 9:00 AM" in speech and "Dr. B at Y, 10:00 AM" in speech


def test_bare_specialty_outside_a_booking_asks_about_its_doctors(unsure_classifier, monkeypatch):
    from src.control.agents.nodes import detect_intent as di
    from src.control.agents.tools import clinic_directory

    monkeypatch.setattr(clinic_directory, "all_specialties", lambda: ["Cardiology", "Gynecology"])
    asked = {}

    async def fake_availability(db, requested_specialty=None, user_speech=""):
        asked["specialty"] = requested_specialty
        return {"intent": "faq_response", "latest_agent_speech": "doctors"}

    monkeypatch.setattr(di, "_handle_doctor_availability_query", fake_availability)
    assert _route({"latest_user_speech": "Gynecology", "channel": "chat"})["intent"] == "faq_response"
    assert asked["specialty"] == "Gynecology"
    asked.clear()
    _route({"latest_user_speech": "gynaecology", "channel": "chat"})
    assert asked["specialty"] == "Gynecology"
    # inside a booking the same word is an answer to the agent's question, not a new question
    asked.clear()
    _route({"latest_user_speech": "Cardiology", "intent": "book", "is_verified": True, "channel": "chat"})
    assert not asked


def test_a_short_specialty_name_matches_only_as_a_whole_word(monkeypatch):
    from src.control.agents.tools import clinic_directory

    monkeypatch.setattr(clinic_directory, "all_specialties", lambda: ["Cardiology", "ENT", "Gynecology"])
    for text in ("cancel my appointment", "I am a student", "parent", "I want to reschedule my appointment", "yesterday"):
        assert clinic_directory.specialty_in_text(text) is None, text
    assert clinic_directory.specialty_in_text("what are the doctors available for the ENT") == "ENT"
    assert clinic_directory.specialty_in_text("ent doctor") == "ENT"
    assert clinic_directory.specialty_in_text("cardiologist") == "Cardiology"
    assert clinic_directory.specialty_in_text("gynaecology") == "Gynecology"


def test_ordinary_short_requests_are_not_mistaken_for_a_specialty_question(unsure_classifier, monkeypatch):
    from src.control.agents.nodes import detect_intent as di
    from src.control.agents.tools import clinic_directory

    monkeypatch.setattr(clinic_directory, "all_specialties", lambda: ["Cardiology", "ENT"])

    async def boom(*args, **kwargs):
        raise AssertionError("must not be treated as a specialty question")

    monkeypatch.setattr(di, "_handle_doctor_availability_query", boom)
    for text in ("cancel my appointment", "I want to cancel", "reschedule my appointment"):
        _route({"latest_user_speech": text, "channel": "chat"})


def test_a_booking_label_on_a_plain_question_does_not_start_the_identity_check(monkeypatch):
    from src.control.agents.nodes import detect_intent as di
    from src.core.services.intent_classification_service import IntentClassificationResult, IntentLabel

    async def says_book(user_message, conversation_context=None):
        return IntentClassificationResult(intent=IntentLabel.BOOK, confidence="high", needs_clarification=False)

    monkeypatch.setattr(di.intent_classification_service, "classify_intent", says_book)
    assert _route({"latest_user_speech": "What is the earliest slot for dermatology?", "channel": "chat",
                   "is_verified": True})["intent"] == "faq"
    # a real booking request is untouched
    assert _route({"latest_user_speech": "I want to book a dermatology appointment", "channel": "chat",
                   "is_verified": True})["intent"] == "book"


def test_another_doctor_works_out_the_specialty_from_the_conversation(monkeypatch):
    from src.control.agents.nodes import booking as bk

    seen = {}

    async def fake_slots(db, date_query=None, specialty=None, **kwargs):
        seen["specialty"] = specialty
        return [
            {**_slot(28, 9), "doctor_name": "Dr. Rajesh Kannan", "location_name": "Anna Nagar Branch", "slot_id": "a"},
            {**_slot(28, 9), "doctor_name": "Dr. Harish Gautham", "location_name": "Tambaram Branch", "slot_id": "b"},
        ]

    monkeypatch.setattr(bk, "get_slots_by_date_and_criteria", fake_slots)
    state = {
        "latest_user_speech": "any other doctor?",
        "offered_slots": [{**_slot(28, 9), "doctor_name": "Dr. Rajesh Kannan", "specialty": "Cardiology", "slot_id": "a"}],
    }
    result = asyncio.run(bk._other_doctors_response(state, None))
    assert seen["specialty"] == "Cardiology"
    assert "Dr. Harish Gautham" in result["latest_agent_speech"] and "Rajesh" not in result["latest_agent_speech"]


# ---- answering the offer that ends a clinic answer ------------------------------------------------

def test_no_to_a_clinic_answers_offer_is_accepted_politely(unsure_classifier):
    state = {"latest_user_speech": "no", "intent": "faq_response", "channel": "chat",
             "latest_agent_speech": "For ENT, Dr. Vivek Sharma is available at our Tambaram branch. Would you like to book an appointment?"}
    reply = _route(state)
    assert reply["intent"] == "faq_response" and "No problem" in reply["latest_agent_speech"]


def test_yes_to_a_booking_offer_starts_the_booking_and_yes_to_other_offers_goes_to_the_answer_step(unsure_classifier):
    book_offer = {"latest_user_speech": "yes", "intent": "faq_response", "channel": "chat",
                  "latest_agent_speech": "For ENT, Dr. Vivek Sharma is available. Would you like to book an appointment?"}
    assert _route(book_offer)["intent"] == "book"
    explain_offer = {"latest_user_speech": "yes", "intent": "faq_response", "channel": "chat",
                     "latest_agent_speech": "We offer five types. Would you like me to explain what any of these involve?"}
    assert _route(explain_offer)["intent"] == "faq"


def test_a_real_question_after_a_misunderstanding_is_answered_not_escalated(unsure_classifier):
    state = {"latest_user_speech": "what are the doctors available for the Dental Consultation", "channel": "chat",
             "latest_agent_speech": "I'm sorry, I didn't quite understand that. Could you please tell me what you need?"}
    assert _route(state)["intent"] == "faq"


def test_yes_to_an_offer_to_explain_the_appointment_types_is_answered_from_the_data():
    from src.control.agents.nodes import faq

    class _Type:
        def __init__(self, name, instructions): self.name, self.duration_minutes, self.instructions = name, 30, instructions

    class _Db:
        def __init__(self):
            self.calls = 0

        async def scalars(self, *_a, **_k):
            self.calls += 1
            rows = {1: [], 2: [], 3: [_Type("Dental Consultation", "Bring X-rays."), _Type("General Consultation", "Arrive early.")]}[self.calls]

            class _R:
                def all(self): return rows
            return _R()

    state = {"latest_user_speech": "yes", "latest_agent_speech": "We offer five types. Would you like me to explain what any of these involve?"}
    result = asyncio.run(faq.faq_agent_node(state, _Db()))
    speech = result["latest_agent_speech"]
    assert "Dental Consultation: 30 minutes. Bring X-rays." in speech and "General Consultation" in speech


# ---- the three issues from the demo rehearsal ---------------------------------------------------

def test_a_specialty_is_not_found_inside_another_word_in_the_doctor_lookup():
    from src.control.agents.nodes.detect_intent import _handle_doctor_availability_query

    class _Loc:
        id = "l1"; name = "Tambaram Branch"

    class _Doc:
        full_name = "Dr. Vivek Sharma"; specialty = "ENT"; location = _Loc(); location_id = "l1"

    class _Db:
        async def scalars(self, *_a, **_k):
            class _R:
                def all(self): return [_Doc()]
            return _R()

    question = asyncio.run(_handle_doctor_availability_query(_Db(), None, "what are the doctors available for Preventive Health Check"))
    assert question["intent"] == "faq"              # answered from clinic facts, not as "For ENT, ..."
    statement = asyncio.run(_handle_doctor_availability_query(_Db(), None, "doctors for the Dental Consultation"))
    assert not statement["latest_agent_speech"].startswith("For ENT")
    still = asyncio.run(_handle_doctor_availability_query(_Db(), None, "what are the doctors available for the ENT"))
    assert "Dr. Vivek Sharma" in still["latest_agent_speech"]


def test_plain_answers_without_the_ai_model_cover_types_policies_and_doctors_by_type():
    from src.control.agents.nodes.faq import _fallback_answer

    class _Type:
        def __init__(self, name): self.name, self.duration_minutes, self.instructions = name, 30, "Arrive early."

    class _Doc:
        def __init__(self, specialty): self.specialty = specialty

    types = [_Type("Dental Consultation"), _Type("Preventive Health Check"), _Type("Specialist Consultation")]
    docs = [_Doc("ENT"), _Doc("Cardiology")]
    for question in ("what are the avaliable appointment types", "what kinds of appointments can i book", "types of consultation"):
        answer = _fallback_answer(question, [], docs, types)
        assert "Dental Consultation (30 minutes)" in answer and "Specialist Consultation" in answer, question
    by_type = _fallback_answer("what are the doctors available for preventive health check", [], docs, types)
    assert "not a doctor specialty" in by_type and "ENT" in by_type and "For ENT" not in by_type
    assert "24 hours" in _fallback_answer("what is your cancellation policy", [], docs, types)
    assert "one active appointment" in _fallback_answer("can i book more than one appointment", [], docs, types)


def test_a_booking_request_is_kept_even_when_the_model_marks_it_unclear(monkeypatch):
    from src.control.agents.nodes import detect_intent as di
    from src.core.services.intent_classification_service import IntentClassificationResult, IntentLabel

    async def unsure_book(user_message, conversation_context=None):
        return IntentClassificationResult(intent=IntentLabel.BOOK, confidence="high", needs_clarification=True)

    async def names(db):
        return ["Dental Consultation", "Specialist Consultation"]

    monkeypatch.setattr(di.intent_classification_service, "classify_intent", unsure_book)
    monkeypatch.setattr(di, "active_visit_names", names)
    for text in ("i want book an appointment for the  Specialist Consultation", "i want to book an appointment for Specialist Consultation"):
        result = _route({"latest_user_speech": text, "channel": "chat", "is_verified": True})
        assert result["intent"] == "book" and result["preferred_appointment_type"] == "Specialist Consultation", text
    # an unclear message with no booking verb is still not treated as a booking
    unclear = _route({"latest_user_speech": "specialist consultation", "channel": "chat", "is_verified": True})
    assert unclear["intent"] != "book"


def test_questions_about_types_and_policies_are_answered_not_treated_as_actions(unsure_classifier):
    for text in ("what kinds of appointments can I book", "types of consultation you offer",
                 "what is your cancellation policy", "can I book more than one appointment at a time",
                 "what should I bring for a follow-up consultation"):
        assert _route({"latest_user_speech": text, "channel": "chat"})["intent"] == "faq", text
    # a real follow-up booking request is untouched
    assert _route({"latest_user_speech": "I want to book a follow-up consultation", "channel": "chat"})["intent"] != "faq"


def test_offline_classifier_treats_an_explicit_booking_request_as_a_booking():
    from src.core.services.intent_classification_service import IntentLabel, intent_classification_service as svc

    for text in ("i want to book an appointment for Specialist Consultation", "book an appointment for the dental consultation"):
        assert svc._fallback_heuristic_classify(text, reason="test").intent == IntentLabel.BOOK, text
    assert svc._fallback_heuristic_classify("which doctors are available for ENT", reason="test").intent == IntentLabel.DOCTOR_AVAILABILITY


def test_a_reply_in_the_wrong_indian_script_is_not_treated_as_already_localized():
    from src.control.agents.nodes.faq import _is_in_language

    tamil, telugu = "அண்ணா நகர் கிளை", "అన్నా నగర్ బ్రాంచ్"
    assert _is_in_language(tamil, "ta-IN") and _is_in_language(telugu, "te-IN")
    assert not _is_in_language(tamil, "te-IN")      # Tamil letters in a Telugu session
    assert not _is_in_language(telugu, "ta-IN")
    assert not _is_in_language("City Care Clinic has four branches.", "te-IN")
    assert _is_in_language("City Care Clinic has four branches.", "en-IN") and _is_in_language("hello", None)


def test_translation_names_the_script_and_asks_again_when_the_script_is_wrong(monkeypatch):
    from src.api.rest.routes import voice_assistant as va

    prompts, replies = [], iter(["City Care Clinic-க்கு 4 கிளைகள்", "సిటీ కేర్ క్లినిక్‌కు 4 బ్రాంచ్‌లు"])

    async def fake(prompt):
        prompts.append(prompt)
        return next(replies)

    monkeypatch.setattr(va, "_gemini_translate", fake)
    result = asyncio.run(va._translate("City Care Clinic has 4 branches.", "te-IN"))
    assert "సిటీ" in result and len(prompts) == 2                 # Tamil letters were rejected, the retry was kept
    assert "Telugu" in prompts[0] and "language code te-IN" in prompts[0]

    async def always_wrong(prompt):
        return "தமிழ் மட்டும்"

    monkeypatch.setattr(va, "_gemini_translate", always_wrong)
    import pytest
    with pytest.raises(RuntimeError, match="translation unavailable"):
        asyncio.run(va._translate("Hello", "te-IN"))


def test_declining_a_cancellation_to_reschedule_starts_the_reschedule(unsure_classifier):
    state = {"latest_user_speech": "No, I want to reschedule it.", "awaiting_cancel_confirmation": True, "channel": "outbound_call"}
    result = _route(state)
    assert result["intent"] == "reschedule"
    assert result["awaiting_cancel_confirmation"] is False


def test_plain_no_to_a_cancellation_still_keeps_the_appointment(unsure_classifier):
    state = {"latest_user_speech": "no", "awaiting_cancel_confirmation": True, "channel": "outbound_call"}
    assert _route(state)["intent"] == "cancel"


def test_clear_reschedule_request_skips_the_model(monkeypatch):
    from src.control.agents.nodes.detect_intent import intent_classification_service

    async def boom(*args, **kwargs):
        raise AssertionError("the classifier should not be called")

    monkeypatch.setattr(intent_classification_service, "classify_intent", boom)
    for text in ("I want to reschedule my appointment.", "I would like to reschedule", "Reschedule please"):
        state = {"latest_user_speech": text, "is_verified": True, "channel": "outbound_call"}
        assert _route(state)["intent"] == "reschedule", text


def test_clinic_hours_questions_are_recognised_in_common_wordings():
    from src.control.agents.nodes.faq import _asks_clinic_hours

    for text in ("What are the timings of the clinic?", "clinic opening timings", "what are your clinic hours", "hours of the clinic"):
        assert _asks_clinic_hours(text), text
    assert not _asks_clinic_hours("what time is my appointment")
