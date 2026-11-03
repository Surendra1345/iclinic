"""The tool-calling agent, tested with a scripted model and a fake database.

No API keys or database are needed. The model is replaced by scripted answers, and the functions that touch
the database are replaced by small fakes. What is under test is what the tools allow and refuse (the safety
rules), and that the loop turns the model's tool calls and reply into the turn result.
"""
import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.control.agents import toolbox as tbx
from src.control.agents.nodes import agent as agent_module
from src.control.agents.nodes.agent import agent_node, clean_reply
from src.control.agents.nodes.gate import gate_node
from src.control.agents.prompts import agent_system, build_context
from src.control.agents.state import AWAITING_HANDOFF_CONTACT, build_input_state
from src.control.agents.toolbox import TOOL_SPECS, Toolbox
from src.control.agents.tools import clinic_directory, slot_tools
from src.core.exceptions import AppointmentServiceError, SlotUnavailableError
from src.core.services.conversation_turn_service import ConversationTurnService
from src.core.services.llm_service import GeminiProvider, LLMError, LLMService, ModelTurn, ToolCall

IST = timezone(timedelta(hours=5, minutes=30))
PATIENT = {"id": str(uuid.uuid4()), "full_name": "Ananya Rao", "date_of_birth": "1995-03-12", "phone": "+919876543210", "email": None}
TYPES = ["Follow-up Consultation", "General Consultation", "Specialist Consultation"]


# ── Fakes ─────────────────────────────────────────────────────────────────────

class FakeDb:
    @asynccontextmanager
    async def begin_nested(self):
        yield

    async def get(self, *_a, **_k):
        return SimpleNamespace(email=None)

    async def flush(self):
        pass

    async def scalars(self, *_a, **_k):
        raise RuntimeError("no database in this test")


def make_slot(n: int, doctor="Dr. Rao", hours_ahead=72):
    start = (datetime.now(timezone.utc) + timedelta(hours=hours_ahead + n)).replace(minute=0, second=0, microsecond=0)
    local = start.astimezone(IST)
    return {
        "slot_id": f"slot-{n}", "doctor_name": doctor, "specialty": "Cardiology", "location_name": "Anna Nagar Branch",
        "location_address": "1 Main Road", "start_time": start.isoformat(), "local_date": local.date().isoformat(),
        "local_time": local.strftime("%H:%M"), "spoken_time": local.strftime("%A, %B %d at %I:%M %p"),
        "formatted_speech": f"{doctor} at Anna Nagar Branch",
    }


def active_appointment(hours_ahead=72):
    slot = make_slot(9, hours_ahead=hours_ahead)
    return {**slot, "appointment_id": "appt-1", "status": "booked"}


class Calls:
    def __init__(self):
        self.reserved, self.released, self.booked, self.rescheduled, self.cancelled = [], [], [], [], []
        self.alerts, self.confirmations, self.registered, self.searches = [], [], [], []
        self.slots = [make_slot(1), make_slot(2), make_slot(3)]
        self.taken = set()
        self.book_error = None
        self.active = None
        self.verify_ok = True
        self.registered_name = None   # what the registration returns when it reuses a profile


@pytest.fixture
def calls(monkeypatch):
    c = Calls()

    async def search_slots(db, **kw):
        c.searches.append(kw)
        return [s for s in c.slots if s["slot_id"] not in kw.get("exclude_slot_ids", ())]

    async def reserve_slot(slot_id, db):
        if slot_id in c.taken:
            raise SlotUnavailableError("taken")
        c.reserved.append(slot_id)
        return True

    async def release_slot(slot_id, db):
        c.released.append(slot_id)
        return True

    async def book(patient_id, slot_id, conversation_id, db, reason=None, appointment_type_name=None):
        if c.book_error:
            raise c.book_error
        c.booked.append((slot_id, appointment_type_name, reason))
        return {"appointment_id": "appt-1", "status": "booked", "slot_id": slot_id}

    async def resched(appointment_id, slot_id, conversation_id, db, reason=None):
        c.rescheduled.append((appointment_id, slot_id))
        return {"appointment_id": appointment_id, "status": "rescheduled", "new_slot_id": slot_id, "reschedule_id": "r1"}

    async def cancel(appointment_id, conversation_id, db, reason=None):
        c.cancelled.append(appointment_id)
        return {"appointment_id": appointment_id, "status": "cancelled", "cancellation_id": "c1"}

    async def active(patient_id, db):
        return c.active

    async def verify(name, dob, db):
        return (True, dict(PATIENT)) if c.verify_ok else (False, None)

    async def register(name, dob, phone, email, db):
        c.registered.append((name, dob.isoformat(), phone, email))
        return {"id": "new-patient", "full_name": c.registered_name or name, "date_of_birth": dob.isoformat(), "phone": phone, "email": email}

    async def confirmation(db, **kw):
        c.confirmations.append(kw)
        return {"sms": False, "email": True, "email_address": "a@example.com"}

    def alert(**kw):
        c.alerts.append(kw)
        return True

    async def visit_names(db):
        return list(TYPES)

    async def previous_visits(patient_id, db):
        return [{"doctor_name": "Dr. Rao", "specialty": "Cardiology", "location_name": "Anna Nagar Branch", "formatted_date": "Monday, March 3"}]

    monkeypatch.setattr(slot_tools, "search_slots", search_slots)
    monkeypatch.setattr(slot_tools, "reserve_slot", reserve_slot)
    monkeypatch.setattr(slot_tools, "release_slot", release_slot)
    monkeypatch.setattr(tbx, "book_appointment", book)
    monkeypatch.setattr(tbx, "reschedule_appointment", resched)
    monkeypatch.setattr(tbx, "cancel_appointment", cancel)
    monkeypatch.setattr(tbx, "check_patient_active_appointment", active)
    monkeypatch.setattr(tbx, "queue_confirmation", confirmation)
    monkeypatch.setattr(tbx, "verify_patient_by_name_and_dob", verify)
    monkeypatch.setattr(tbx, "register_new_patient", register)
    monkeypatch.setattr(tbx, "queue_frontdesk_alert", alert)
    monkeypatch.setattr(tbx, "active_visit_names", visit_names)
    monkeypatch.setattr(tbx, "get_followup_candidates", previous_visits)
    for name in ("canonical_specialty", "canonical_doctor", "canonical_branch"):
        monkeypatch.setattr(clinic_directory, name, lambda value: value or None)
    return c


def state_for(channel="chat", verified=False, speech="hi", **saved):
    conversation = SimpleNamespace(
        id=uuid.uuid4(), collected_details=saved, messages=[], patient_id=None,
        identity_verified_at=datetime.now(timezone.utc) if verified else None,
    )
    state = build_input_state(conversation, channel=channel, call_sid="CA1", speech=speech,
                              patient_phone="+919999999999" if channel == "outbound_call" else "")
    if verified:
        state.update({"patient_id": PATIENT["id"], "patient_name": PATIENT["full_name"]})
    return state


def verified_state(**kw):
    return state_for(verified=True, **kw)


def box(state=None, **kw):
    return Toolbox(FakeDb(), state if state is not None else verified_state(**kw))


def run(coro):
    return asyncio.run(coro)


def call(toolbox, name, **args):
    return run(toolbox.call(name, args))


def held_state(**extra):
    slot = make_slot(1)
    return verified_state(target_slot_id=slot["slot_id"], target_slot_details=slot, offered_slots=[slot], **extra)


# ── Tool descriptions ─────────────────────────────────────────────────────────

def test_every_tool_has_a_description_and_a_handler():
    toolbox = box()
    names = [t["name"] for t in TOOL_SPECS]
    assert len(names) == len(set(names))
    assert set(names) == set(toolbox._handlers)
    assert all(len(t["description"]) > 30 and t["parameters"]["type"] == "object" for t in TOOL_SPECS)


def test_unknown_tool_and_bad_arguments_are_reported_not_raised(calls):
    toolbox = box()
    assert call(toolbox, "drop_tables")["status"] == "unknown_tool"
    assert call(toolbox, "search_slots", colour="red")["status"] == "need_more_criteria"     # extra arguments are ignored
    assert call(toolbox, "get_my_appointment", patient="Ananya")["status"] == "none"
    assert call(toolbox, "hold_slot")["status"] == "bad_arguments"                            # a missing one is reported


# ── Identity ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,args", [
    ("search_slots", {"specialty": "Cardiology"}), ("hold_slot", {"slot_id": "slot-1"}), ("get_my_appointment", {}),
    ("request_confirmation", {"action": "book"}), ("book_appointment", {"consent_quote": "yes"}),
    ("cancel_appointment", {"consent_quote": "yes"}), ("save_patient_email", {"email": "a@b.com"}),
])
def test_nothing_about_a_patient_works_before_identity(calls, name, args):
    assert call(box(state_for()), name, **args)["status"] == "identity_required"
    assert not calls.reserved and not calls.booked and not calls.cancelled


def test_verified_patient_unlocks_the_tools(calls):
    state = state_for()
    result = call(box(state), "verify_identity", full_name="ananya rao", date_of_birth="1995-03-12")
    assert result == {"status": "verified", "first_name": "Ananya"}
    assert state["is_verified"] is True and state["patient_id"] == PATIENT["id"]


def test_two_failed_checks_hand_over_and_never_say_which_detail_failed(calls):
    calls.verify_ok = False
    state = state_for()
    toolbox = box(state)
    first = call(toolbox, "verify_identity", full_name="A B", date_of_birth="1990-01-01")
    assert first["status"] == "no_match" and first["attempts_left"] == 1 and not state["handoff_completed"]
    assert "which detail" in first["message"].lower() and "name" not in first["message"].lower().replace("which detail", "")
    second = call(toolbox, "verify_identity", full_name="A B", date_of_birth="1990-01-01")
    assert second["status"] == "failed_final_handed_to_front_desk"
    assert state["handoff_required"] and state["end_outcome"] == "handed_to_front_desk" and calls.alerts
    assert call(toolbox, "search_slots", specialty="Cardiology")["status"] == "conversation_closed"


def test_unreadable_date_of_birth_is_not_counted_as_an_attempt(calls):
    state = state_for()
    result = call(box(state), "verify_identity", full_name="Ananya Rao", date_of_birth="2999-01-01")
    assert result["status"] == "invalid_date_of_birth" and state["verify_attempts"] == 0


def test_registration_needs_a_phone_then_verifies_the_new_patient(calls):
    state = state_for()
    toolbox = box(state)
    assert call(toolbox, "register_patient", full_name="Ravi Kumar", date_of_birth="1990-07-01")["missing"] == ["phone"]
    ok = call(toolbox, "register_patient", full_name="Ravi Kumar", date_of_birth="1990-07-01", phone="9876543210", email="ravi@example.com")
    assert ok["status"] == "registered" and state["is_verified"] is True
    assert calls.registered == [("Ravi Kumar", "1990-07-01", "+919876543210", "ravi@example.com")]


def test_registering_with_someone_elses_phone_does_not_verify_the_stranger(calls):
    calls.registered_name = "Someone Else"      # the profile registration reused belongs to another person
    state = state_for()
    result = call(box(state), "register_patient", full_name="Ravi Kumar", date_of_birth="1990-07-01", phone="9876543210")
    assert result["status"] == "needs_front_desk" and state["is_verified"] is False and state["handoff_required"]


def test_a_phone_call_registers_with_the_number_it_was_made_to(calls):
    state = state_for(channel="outbound_call")
    ok = call(box(state), "register_patient", full_name="Ravi Kumar", date_of_birth="1990-07-01")
    assert ok["status"] == "registered" and calls.registered[0][2] == "+919999999999"


# ── Searching and holding ─────────────────────────────────────────────────────

def test_search_checks_names_dates_and_needs_something_to_search_for(calls, monkeypatch):
    toolbox = box()
    assert call(toolbox, "search_slots")["status"] == "need_more_criteria"
    assert call(toolbox, "search_slots", date_from="2001-01-01")["status"] == "date_in_past"
    assert call(toolbox, "search_slots", date_from="tomorrow")["status"] == "invalid_date"
    monkeypatch.setattr(clinic_directory, "canonical_doctor", lambda v: None)
    unknown = call(toolbox, "search_slots", doctor="Dr. Nobody")
    assert unknown["status"] == "unknown_value" and unknown["field"] == "doctor" and not calls.searches


def test_search_offers_numbered_options_and_remembers_them(calls):
    state = verified_state()
    result = call(box(state), "search_slots", specialty="Cardiology")
    assert result["status"] == "found" and [o["n"] for o in result["options"]] == [1, 2, 3]
    assert [o["slot_id"] for o in state["offered_slots"]] == ["slot-1", "slot-2", "slot-3"]


def test_search_never_offers_the_patients_own_current_time(calls):
    calls.active = active_appointment()
    call(box(), "search_slots", specialty="Cardiology")
    assert calls.searches[0]["exclude_slot_ids"] == [calls.active["slot_id"]]


def test_search_with_no_match_says_what_was_searched(calls):
    calls.slots = []
    result = call(box(), "search_slots", doctor="Dr. Rao", time_from="23:00")
    assert result["status"] == "none_found" and result["searched"]["doctor"] == "Dr. Rao"


def test_only_a_slot_from_the_latest_search_can_be_held(calls):
    state = verified_state()
    toolbox = box(state)
    assert call(toolbox, "hold_slot", slot_id="slot-1")["status"] == "not_offered"
    call(toolbox, "search_slots", specialty="Cardiology")
    assert call(toolbox, "hold_slot", slot_id="slot-99")["status"] == "not_offered"
    held = call(toolbox, "hold_slot", slot_id="slot-2")
    assert held["status"] == "held" and state["target_slot_id"] == "slot-2" and calls.reserved == ["slot-2"]


def test_holding_another_slot_releases_the_first(calls):
    state = verified_state()
    toolbox = box(state)
    call(toolbox, "search_slots", specialty="Cardiology")
    call(toolbox, "hold_slot", slot_id="slot-1")
    call(toolbox, "hold_slot", slot_id="slot-2")
    assert calls.released == ["slot-1"] and state["target_slot_id"] == "slot-2"


def test_a_slot_taken_in_the_meantime_is_reported_and_removed(calls):
    calls.taken = {"slot-1"}
    state = verified_state()
    toolbox = box(state)
    call(toolbox, "search_slots", specialty="Cardiology")
    assert call(toolbox, "hold_slot", slot_id="slot-1")["status"] == "slot_taken"
    assert state["target_slot_id"] is None and "slot-1" not in [o["slot_id"] for o in state["offered_slots"]]


# ── The confirmation rule ─────────────────────────────────────────────────────

def test_request_confirmation_refuses_what_the_rules_forbid(calls):
    assert call(box(held_state()), "request_confirmation", action="book")["status"] == "recorded"
    assert call(box(verified_state()), "request_confirmation", action="book")["reason"] == "no_slot_held"

    calls.active = active_appointment()
    again = call(box(held_state()), "request_confirmation", action="book")
    assert again["status"] == "blocked" and again["reason"] == "already_has_active_appointment"

    calls.active = active_appointment(hours_ahead=3)
    for action in ("cancel", "reschedule"):
        blocked = call(box(held_state()), "request_confirmation", action=action)
        assert blocked["reason"] == "within_cutoff"
    calls.active = None
    assert call(box(verified_state()), "request_confirmation", action="cancel")["reason"] == "no_active_appointment"


def test_a_write_in_the_same_turn_as_the_question_is_refused(calls):
    state = held_state(speech="yes please")
    state["latest_user_speech"] = "yes please"
    toolbox = box(state)
    assert call(toolbox, "request_confirmation", action="book")["status"] == "recorded"
    refused = call(toolbox, "book_appointment", consent_quote="yes")
    assert refused["status"] == "not_confirmed" and not calls.booked


def next_turn_state(action="book", message="yes please book it", **extra):
    state = held_state(**extra)
    state["pending_confirmation"] = {"action": action, "slot_id": state["target_slot_id"]}
    state["latest_user_speech"] = message
    return state


def test_a_booking_needs_the_question_from_last_turn_and_the_patients_own_words(calls):
    state = next_turn_state()
    toolbox = box(state)
    assert call(toolbox, "book_appointment", consent_quote="I agree completely")["status"] == "consent_not_found"
    assert not calls.booked
    result = call(toolbox, "book_appointment", consent_quote="Yes, please", appointment_type="general consultation", visit_reason="fever")
    assert result["status"] == "booked" and calls.booked == [("slot-1", "General Consultation", "fever")]
    assert state["booking_confirmed"] and state["target_slot_id"] is None and state["pending_confirmation"] is None
    assert calls.confirmations and result["confirmation"]["email"] is True


def test_the_confirmation_belongs_to_the_slot_it_was_asked_about(calls):
    state = next_turn_state()
    state["pending_confirmation"]["slot_id"] = "slot-3"
    assert call(box(state), "book_appointment", consent_quote="yes")["status"] == "not_confirmed"
    assert not calls.booked


def test_a_cancel_question_cannot_authorise_a_booking(calls):
    state = next_turn_state(action="cancel")
    assert call(box(state), "book_appointment", consent_quote="yes")["status"] == "not_confirmed"


def test_booking_needs_a_known_visit_type(calls):
    result = call(box(next_turn_state()), "book_appointment", consent_quote="yes", appointment_type="Spa Day")
    assert result["status"] == "unknown_appointment_type" and result["valid_values"] == TYPES and not calls.booked


def test_a_refused_booking_releases_the_slot_and_reports_why(calls):
    calls.book_error = AppointmentServiceError("Slot is already booked.")
    state = next_turn_state()
    result = call(box(state), "book_appointment", consent_quote="yes")
    assert result["status"] == "slot_unavailable" and calls.released == ["slot-1"] and state["target_slot_id"] is None
    calls.book_error = AppointmentServiceError("Patient already has an active appointment.")
    assert call(box(next_turn_state()), "book_appointment", consent_quote="yes")["status"] == "has_active_appointment"


def test_a_question_is_good_for_one_answer_only(calls):
    state = next_turn_state()
    toolbox = box(state)
    assert toolbox.finish_turn() == []          # the model did not ask again this turn
    assert state["pending_confirmation"] is None and state["awaiting"] is None


def test_asking_sets_the_waiting_state_and_yes_no_buttons(calls):
    state = held_state()
    toolbox = box(state)
    call(toolbox, "request_confirmation", action="book")
    buttons = toolbox.finish_turn()
    assert [b["label"] for b in buttons] == ["Yes", "No"] and state["awaiting"] == "booking_confirmation"


def test_reschedule_after_a_yes(calls):
    calls.active = active_appointment()
    state = next_turn_state(action="reschedule", active_appointment_id="appt-1", active_appointment_details=calls.active)
    state["pending_confirmation"]["appointment_id"] = "appt-1"
    result = call(box(state), "reschedule_appointment", consent_quote="yes")
    assert result["status"] == "rescheduled" and calls.rescheduled == [("appt-1", "slot-1")]
    assert result["previous"]["doctor"] == "Dr. Rao" and state["booking_confirmed"]


def test_cancel_after_a_yes_and_never_inside_the_cutoff(calls):
    calls.active = active_appointment()
    state = verified_state(active_appointment_id="appt-1", pending_confirmation={"action": "cancel", "appointment_id": "appt-1"})
    state["latest_user_speech"] = "yes cancel it"
    result = call(box(state), "cancel_appointment", consent_quote="yes")
    assert result["status"] == "cancelled" and calls.cancelled == ["appt-1"] and state["active_appointment_id"] is None

    calls.cancelled.clear()
    calls.active = active_appointment(hours_ahead=3)
    soon = verified_state(active_appointment_id="appt-1", pending_confirmation={"action": "cancel", "appointment_id": "appt-1"})
    soon["latest_user_speech"] = "yes"
    assert call(box(soon), "cancel_appointment", consent_quote="yes")["status"] == "blocked_cutoff" and not calls.cancelled


# ── Hand-over and ending ──────────────────────────────────────────────────────

def test_emergency_hands_over_at_once_without_identity_and_releases_the_hold(calls):
    state = held_state()
    state["is_verified"] = False
    result = call(box(state), "handoff_to_front_desk", reason="chest pain", emergency=True)
    assert result["status"] == "handed_over" and state["is_emergency"] and calls.released == ["slot-1"]
    assert "EMERGENCY" in calls.alerts[0]["reason"] and state["end_outcome"] == "handed_to_front_desk"


def test_a_web_patient_is_asked_for_a_way_to_reach_them_once(calls):
    state = state_for()
    toolbox = box(state)
    ask = call(toolbox, "handoff_to_front_desk", reason="wants a person")
    assert ask["status"] == "need_callback_contact" and not state["handoff_completed"]
    toolbox.finish_turn()
    assert state["awaiting"] == AWAITING_HANDOFF_CONTACT
    again = box(state)
    done = call(again, "handoff_to_front_desk", reason="wants a person", callback_phone="9876543210")
    assert done["status"] == "handed_over" and done["callback_contact_available"] and calls.alerts[0]["call_details"]["patient_phone"] == "+919876543210"
    declined = call(box(state_for()), "handoff_to_front_desk", reason="x", contact_declined=True)
    assert declined["status"] == "handed_over" and declined["callback_contact_available"] is False


def test_a_phone_call_hands_over_straight_away(calls):
    state = state_for(channel="outbound_call")
    assert call(box(state), "handoff_to_front_desk", reason="wants a person")["status"] == "handed_over"


def test_wrong_person_ends_a_phone_call_only(calls):
    phone = state_for(channel="outbound_call")
    call(box(phone), "end_conversation", reason="wrong_person")
    assert phone["end_outcome"] == "wrong_person" and phone["is_completed"]
    web = state_for()
    call(box(web), "end_conversation", reason="wrong_person")
    assert web["end_outcome"] == "ended"


def test_ending_gives_back_the_held_slot(calls):
    state = held_state()
    call(box(state), "end_conversation", reason="goodbye")
    assert calls.released == ["slot-1"] and state["is_completed"] and state["pending_confirmation"] is None


# ── The loop ──────────────────────────────────────────────────────────────────

class ScriptedProvider:
    def __init__(self, *turns):
        self.turns = list(turns)
        self.seen = []

    async def generate_step(self, messages, *, system, tools, temperature, max_tokens, timeout):
        self.seen.append((list(messages), system, tools))
        item = self.turns.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def say(text):
    return ModelTurn(text=text)


def use(*tool_calls, text=""):
    return ModelTurn(text=text, calls=[ToolCall(n, a) for n, a in tool_calls])


def run_agent(monkeypatch, provider, state):
    monkeypatch.setattr(agent_module, "llm_service", LLMService(provider))
    return run(agent_node(state, FakeDb()))


def test_one_sentence_with_symptoms_a_request_name_and_dob_is_handled_in_one_turn(calls, monkeypatch):
    provider = ScriptedProvider(
        use(("verify_identity", {"full_name": "Ananya Rao", "date_of_birth": "1995-03-12"}), ("get_my_appointment", {})),
        use(("search_slots", {"specialty": "Cardiology"})),
        say("Thanks Ananya, sorry about the fever. Dr. Rao has three times open. Which suits you?"),
    )
    state = state_for(speech="I have a high fever, I want to book an appointment, I am Ananya Rao born 12 March 1995")
    out = run_agent(monkeypatch, provider, state)
    assert out["is_verified"] is True and out["latest_agent_speech"].startswith("Thanks Ananya")
    assert len(out["offered_slots"]) == 3 and len(out["choices"]) == 3
    # the tool results were fed back to the model
    last_messages = provider.seen[-1][0]
    assert last_messages[-1]["role"] == "tool" and last_messages[-1]["results"][0]["response"]["status"] == "found"
    assert "high fever" in provider.seen[0][0][0]["text"]


def test_the_model_cannot_book_in_the_turn_it_asks(calls, monkeypatch):
    provider = ScriptedProvider(
        use(("request_confirmation", {"action": "book"}), ("book_appointment", {"consent_quote": "yes"})),
        say("Shall I book Dr. Rao for you? Yes or no?"),
    )
    state = held_state(speech="book the first one yes")
    out = run_agent(monkeypatch, provider, state)
    assert not calls.booked and out["pending_confirmation"]["action"] == "book" and out["awaiting"] == "booking_confirmation"
    assert [c["label"] for c in out["choices"]] == ["Yes", "No"]
    refused = provider.seen[1][0][-1]["results"][1]["response"]
    assert refused["status"] == "not_confirmed"


def test_a_two_turn_booking_writes_only_after_the_answer(calls, monkeypatch):
    first = run_agent(monkeypatch, ScriptedProvider(
        use(("request_confirmation", {"action": "book"})), say("Book Dr. Rao on Monday? Yes or no?")),
        held_state(speech="the first one"))
    assert not calls.booked
    second_state = {**first, "messages": [], "latest_user_speech": "yes go ahead"}
    out = run_agent(monkeypatch, ScriptedProvider(
        use(("book_appointment", {"consent_quote": "yes go ahead"})), say("Booked! A confirmation is on its way.")),
        second_state)
    assert calls.booked and out["booking_confirmed"] is True and out["intent"] == "book" and out["choices"] == []


def test_a_system_event_gets_a_reply_without_a_patient_message(calls, monkeypatch):
    provider = ScriptedProvider(say("Hello, this is Happy calling from City Care Clinic. Could you confirm your full name and date of birth?"))
    state = state_for(channel="outbound_call", speech="")
    state.update(run(gate_node(state, None)))
    out = run_agent(monkeypatch, provider, state)
    assert state["event"] == "call_connected" and "SYSTEM EVENT: call_connected" in provider.seen[0][0][0]["text"]
    assert out["latest_agent_speech"].startswith("Hello")


def test_the_loop_gives_up_after_the_step_limit(calls, monkeypatch):
    monkeypatch.setattr(agent_module.settings, "LLM_AGENT_MAX_STEPS", 3)
    provider = ScriptedProvider(*[use(("get_my_appointment", {})) for _ in range(3)])
    with pytest.raises(LLMError):
        run_agent(monkeypatch, provider, verified_state())


def test_a_model_outage_raises_so_the_turn_is_rolled_back(calls, monkeypatch):
    with pytest.raises(LLMError):
        run_agent(monkeypatch, ScriptedProvider(RuntimeError("down")), state_for())


def test_an_empty_model_answer_is_an_error(calls, monkeypatch):
    with pytest.raises(LLMError):
        run_agent(monkeypatch, ScriptedProvider(ModelTurn()), state_for())


def test_phone_replies_lose_lists_and_formatting():
    assert clean_reply("**Hi**\n1. one\n2. two", "outbound_call") == "Hi one two"
    assert clean_reply("**Hi**\n- one", "chat") == "Hi\n- one"


# ── The prompt and the context ────────────────────────────────────────────────

def test_the_context_tells_the_model_what_it_asked_last_turn_and_what_is_held():
    state = held_state()
    state["pending_confirmation"] = {"action": "book", "slot_id": "slot-1"}
    state["messages"] = [{"role": "agent", "content": "Shall I book it?"}, {"role": "patient", "content": "yes"}]
    state["latest_user_speech"] = "yes"
    text = build_context(state)
    assert "ASKED THE PATIENT TO CONFIRM: book" in text and "TIME CURRENTLY HELD" in text
    assert "assistant: Shall I book it?" in text and "<message>\nyes\n</message>" in text
    assert text.count("yes") >= 2


def test_the_system_prompt_carries_the_rules_and_the_channel_style():
    chat, phone = agent_system("chat"), agent_system("outbound_call")
    assert "request_confirmation" in chat and "112 or 108" in chat and "text chat" in chat
    assert "ONLY when the patient wants to book, reschedule or cancel" in chat and "they only say hello" in chat
    assert "phone call" in phone and str(tbx.settings.RESCHEDULE_CANCEL_CUTOFF_HOURS) in chat


def test_gate_resets_one_turn_state_and_a_finished_booking_starts_clean():
    out = run(gate_node({**state_for(), "booking_confirmed": True, "offered_slots": [{"a": 1}], "intent": "book",
                         "pending_confirmation": {"action": "book"}}, None))
    assert out["offered_slots"] == [] and out["pending_confirmation"] is None and out["booking_confirmed"] is False


def test_gate_starts_clean_after_a_handoff_unless_a_contact_is_awaited():
    done = run(gate_node({**state_for(), "handoff_completed": True, "handoff_required": True}, None))
    assert done["handoff_completed"] is False and done["verify_attempts"] == 0
    waiting = run(gate_node({**state_for(), "handoff_required": True, "awaiting": AWAITING_HANDOFF_CONTACT}, None))
    assert "handoff_completed" not in waiting


def test_gate_names_the_system_events():
    assert run(gate_node(state_for(speech=""), None))["event"] == "session_started"
    later = state_for(speech="")
    later["messages"] = [{"role": "agent", "content": "hi"}]
    assert run(gate_node(later, None))["event"] == "no_speech"
    assert run(gate_node(state_for(speech="hello"), None))["event"] is None


# ── Model gateway ─────────────────────────────────────────────────────────────

def test_the_gateway_wraps_any_provider_failure_in_llmerror(monkeypatch):
    service = LLMService(ScriptedProvider(RuntimeError("quota")))
    with pytest.raises(LLMError):
        run(service.act([{"role": "user", "text": "hi"}], system="s", tools=[]))
    assert service.get_stats()["calls"] == {"fixed.failed": 1, "agent.unavailable": 1}


def test_gemini_messages_are_converted_without_a_network_call():
    pytest.importorskip("google.genai")
    contents = GeminiProvider._contents([
        {"role": "user", "text": "hello"},
        {"role": "model", "text": "", "calls": [ToolCall("search_slots", {"specialty": "Cardiology"})]},
        {"role": "tool", "results": [{"name": "search_slots", "response": {"status": "found"}}]},
    ])
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert contents[1].parts[0].function_call.name == "search_slots"
    assert contents[2].parts[0].function_response.response == {"status": "found"}


# ── State kept between turns ──────────────────────────────────────────────────

def test_state_is_rebuilt_from_the_stored_conversation_every_turn():
    conversation = SimpleNamespace(
        id=uuid.uuid4(), messages=[{"role": "agent", "content": "Hi"}], patient_id=uuid.uuid4(),
        identity_verified_at=None, collected_details={"pending_confirmation": {"action": "book"}, "patient_name": "Ananya Rao"},
    )
    state = build_input_state(conversation, channel="chat", call_sid="s", speech=" yes ")
    assert state["pending_confirmation"] == {"action": "book"} and state["latest_user_speech"] == "yes"
    assert state["is_verified"] is False and state["latest_agent_speech"] == "Hi"      # only the stored verification opens the gate
    assert state["facts"] == [] if "facts" in state else True


def test_conversation_state_is_worked_out_from_the_agent_state():
    state = ConversationTurnService._conversation_state
    assert state({"handoff_required": True}).value == "handed_to_front_desk"
    assert state({"booking_confirmed": True, "intent": "cancel"}).value == "cancelled"
    assert state({"is_completed": True, "is_verified": True}) is None
    assert state({"target_slot_id": "s", "awaiting": "booking_confirmation"}).value == "reconfirming"
    assert state({"target_slot_id": "s"}).value == "slot_reserved"
    assert state({"awaiting": "cancel_confirmation", "is_verified": True}).value == "reconfirming"
    assert state({"offered_slots": [{"a": 1}], "is_verified": True}).value == "suggesting_slots"
    assert state({"is_verified": True}).value == "collecting_details"
    assert state({"verify_attempts": 1}).value == "identifying_patient"


# ── Providers: Groq first for chat and calls, Gemini first for the browser voice ─

def groq_messages():
    return [
        {"role": "user", "text": "context"},
        {"role": "model", "text": "", "calls": [ToolCall("search_slots", {"specialty": "Cardiology"}), ToolCall("get_my_appointment", {})]},
        {"role": "tool", "results": [{"name": "search_slots", "response": {"status": "found"}},
                                     {"name": "get_my_appointment", "response": {"status": "none"}}]},
    ]


def test_groq_messages_pair_every_tool_result_with_its_call():
    from src.core.services.llm_service import GroqProvider
    out = GroqProvider._messages(groq_messages(), "system text")
    assert [m["role"] for m in out] == ["system", "user", "assistant", "tool", "tool"]
    calls = out[2]["tool_calls"]
    assert [c["function"]["name"] for c in calls] == ["search_slots", "get_my_appointment"]
    assert [m["tool_call_id"] for m in out[3:]] == [c["id"] for c in calls] and len({c["id"] for c in calls}) == 2
    assert out[3]["content"] == '{"status": "found"}'


class FakeHttp:
    """Stands in for httpx.AsyncClient; records the request and returns a scripted Groq answer."""
    sent = {}
    answer = {}
    status = 200

    def __init__(self, **_):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def post(self, url, json=None, headers=None):
        FakeHttp.sent = {"url": url, "json": json, "headers": headers}
        import httpx
        return httpx.Response(FakeHttp.status, json=FakeHttp.answer, request=httpx.Request("POST", url))


def test_groq_provider_sends_tools_and_reads_tool_calls(monkeypatch):
    from src.core.services import llm_service as module
    monkeypatch.setattr(module.httpx, "AsyncClient", FakeHttp)
    monkeypatch.setattr(module.settings, "GROQ_API_KEY", "gsk_test")
    FakeHttp.status = 200
    FakeHttp.answer = {"choices": [{"message": {"content": None, "tool_calls": [
        {"id": "abc", "type": "function", "function": {"name": "search_slots", "arguments": '{"specialty": "Cardiology"}'}}]}}]}
    turn = run(module.GroqProvider("test-model").generate_step(
        groq_messages(), system="s", tools=TOOL_SPECS, temperature=0.3, max_tokens=100, timeout=5))
    assert turn.calls == [ToolCall("search_slots", {"specialty": "Cardiology"}, id="abc")]
    body = FakeHttp.sent["json"]
    assert body["model"] == "test-model" and body["tool_choice"] == "auto" and len(body["tools"]) == len(TOOL_SPECS)
    assert FakeHttp.sent["headers"]["Authorization"] == "Bearer gsk_test"
    assert FakeHttp.sent["url"].endswith("/chat/completions")


def test_a_groq_error_is_raised_so_the_next_provider_can_be_tried(monkeypatch):
    import httpx
    from src.core.services import llm_service as module
    monkeypatch.setattr(module.httpx, "AsyncClient", FakeHttp)
    FakeHttp.status, FakeHttp.answer = 429, {"error": "rate limit"}
    with pytest.raises(httpx.HTTPStatusError):
        run(module.GroqProvider().generate_step(groq_messages(), system="s", tools=[], temperature=0, max_tokens=10, timeout=5))


class Named:
    def __init__(self, name, log, fail=False):
        self.name, self.log, self.fail = name, log, fail

    async def generate_step(self, messages, **_):
        self.log.append(self.name)
        if self.fail:
            raise RuntimeError("down")
        return ModelTurn(text=f"from {self.name}")


def routed_service(monkeypatch, log, groq_fails=False, gemini_fails=False):
    from src.core.services import llm_service as module
    monkeypatch.setattr(module.settings, "GROQ_API_KEY", "k1")
    monkeypatch.setattr(module.settings, "GEMINI_API_KEY", "k2")
    service = LLMService()
    service._providers = {"groq": Named("groq", log, groq_fails), "gemini": Named("gemini", log, gemini_fails)}
    return service


def act(service, channel):
    return run(service.act([{"role": "user", "text": "hi"}], system="s", tools=[], channel=channel))


def test_chat_and_calls_try_groq_first_and_the_browser_voice_tries_gemini_first(monkeypatch):
    for channel, first in (("chat", "groq"), ("outbound_call", "groq"), ("voice_assistant", "gemini")):
        log = []
        assert act(routed_service(monkeypatch, log), channel).text == f"from {first}" and log == [first]


def test_the_other_provider_answers_when_the_first_fails_and_is_skipped_for_a_while(monkeypatch):
    log = []
    service = routed_service(monkeypatch, log, groq_fails=True)
    assert act(service, "chat").text == "from gemini" and log == ["groq", "gemini"]
    log.clear()
    assert act(service, "chat").text == "from gemini" and log == ["gemini"]     # groq is resting after its failure
    assert service.get_stats()["calls"]["groq.failed"] == 1


def test_all_providers_failing_or_missing_keys_is_an_llm_error(monkeypatch):
    log = []
    with pytest.raises(LLMError):
        act(routed_service(monkeypatch, log, groq_fails=True, gemini_fails=True), "chat")
    from src.core.services import llm_service as module
    monkeypatch.setattr(module.settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(module.settings, "GEMINI_API_KEY", "")
    with pytest.raises(LLMError):
        act(LLMService(), "chat")


def test_a_provider_without_a_key_is_never_called(monkeypatch):
    log = []
    service = routed_service(monkeypatch, log)
    from src.core.services import llm_service as module
    monkeypatch.setattr(module.settings, "GROQ_API_KEY", "")
    assert act(service, "chat").text == "from gemini" and log == ["gemini"]


def test_groq_tries_the_next_model_and_hides_reasoning_text(monkeypatch):
    from src.core.services import llm_service as module
    tried = []

    class Http(FakeHttp):
        async def post(self, url, json=None, headers=None):
            import httpx
            tried.append(json["model"])
            if json["model"] == "qwen/qwen3-32b" and len(tried) == 1:
                return httpx.Response(500, json={}, request=httpx.Request("POST", url))
            return httpx.Response(200, json={"choices": [{"message": {"content": "<think>secret plan</think>Hello there"}}]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(module.httpx, "AsyncClient", Http)
    turn = run(module.GroqProvider("qwen/qwen3-32b,openai/gpt-oss-120b").generate_step(
        groq_messages(), system="s", tools=[], temperature=0, max_tokens=10, timeout=5))
    assert tried == ["qwen/qwen3-32b", "openai/gpt-oss-120b"] and turn.text == "Hello there"


def test_default_models_are_gemini_3_5_with_3_8_behind_it_and_qwen_then_gpt_oss():
    from src.config.settings import settings as cfg
    assert cfg.GEMINI_MODEL == "gemini-3.5-flash" and cfg.GEMINI_FALLBACK_MODEL == "gemini-3.8-flash"
    assert [m.split("/")[-1] for m in cfg.GROQ_MODELS.split(",")][0].startswith("qwen")
    assert "gpt-oss" in cfg.GROQ_MODELS
