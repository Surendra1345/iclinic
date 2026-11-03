import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from src.config.settings import settings
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


# ---- date of birth message ---------------------------------------------------------------------


# ---- Tamil / Telugu short answers --------------------------------------------------------------

@pytest.mark.parametrize("text, english", [
    ("ஆம்", "yes"), ("అవును.", "yes"), ("illai", "no"), ("వద్దు", "no"), ("நன்றி", "thank you"),
])
def test_common_indic_answers_are_translated_offline(text, english):
    assert quick_english(text) == english


def test_longer_indic_sentence_is_left_to_the_translator():
    assert quick_english("எனக்கு நாளை அப்பாயின்ட்மெண்ட் வேண்டும்") is None


# ---- chat quick replies ------------------------------------------------------------------------


# ---- visit type --------------------------------------------------------------------------------


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


# ---- reschedule keeps the date being discussed -------------------------------------------------


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


# ---- availability answers stay short when many doctors match ------------------------------------

def _many_doctors(count, hour=9):
    slots = []
    for i in range(count):
        slot = _slot(25, hour)
        slot.update({"doctor_name": f"Dr. {i}", "location_name": f"{'AB'[i % 2]} Branch", "slot_id": f"d{i}"})
        slots.append(slot)
    return slots


# ---- final fixes: other doctor, unclear twice, wrong person, confirmation status, step log -------


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


# ---- chat buttons for branch / doctor / visit type / yes-no questions ----------------------------


# ---- specialty words are not names; "ok" is acknowledged; one-branch specialties --------------------


# ---- edge cases: bare yes/no, walking away, two-digit year, nearest times -----------------------


# ---- final edge cases: gibberish names, booking for someone else, past dates ---------------------


def test_a_short_specialty_name_matches_only_as_a_whole_word(monkeypatch):
    from src.control.agents.tools import clinic_directory

    monkeypatch.setattr(clinic_directory, "all_specialties", lambda: ["Cardiology", "ENT", "Gynecology"])
    for text in ("cancel my appointment", "I am a student", "parent", "I want to reschedule my appointment", "yesterday"):
        assert clinic_directory.specialty_in_text(text) is None, text
    assert clinic_directory.specialty_in_text("what are the doctors available for the ENT") == "ENT"
    assert clinic_directory.specialty_in_text("ent doctor") == "ENT"
    assert clinic_directory.specialty_in_text("cardiologist") == "Cardiology"
    assert clinic_directory.specialty_in_text("gynaecology") == "Gynecology"


# ---- answering the offer that ends a clinic answer ------------------------------------------------


# ---- the three issues from the demo rehearsal ---------------------------------------------------


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


