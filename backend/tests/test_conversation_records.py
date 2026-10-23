import asyncio
import difflib
import uuid
from types import SimpleNamespace

from src.constants.enums import ChannelType, OutcomeType
from src.control.agents.nodes import end_call
from src.control.agents.tools import booking_tools
from src.core.services.conversation_turn_service import ConversationTurnService


# ---- the appointment keeps the channel of the conversation it was booked in -------------------

def _book(channel):
    seen = {}

    class _Service:
        def __init__(self, db):
            pass

        async def book_appointment_atomic(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(id=uuid.uuid4(), slot_id=kwargs["slot_id"], status=SimpleNamespace(value="booked"))

    class _Result:
        def scalars(self):
            return self

        def first(self):
            return SimpleNamespace(id=uuid.uuid4())

    class _Db:
        async def get(self, model, key):
            return SimpleNamespace(channel=channel) if channel else None

        async def execute(self, _query):
            return _Result()

    original = booking_tools.AppointmentService
    booking_tools.AppointmentService = _Service
    try:
        asyncio.run(booking_tools.book_appointment(
            patient_id_str=str(uuid.uuid4()), slot_id_str=str(uuid.uuid4()),
            conversation_id_str=str(uuid.uuid4()), db=_Db(),
        ))
    finally:
        booking_tools.AppointmentService = original
    return seen["channel"]


def test_chat_booking_is_recorded_as_chat():
    assert _book(ChannelType.CHAT) == ChannelType.CHAT


def test_voice_booking_is_recorded_as_voice():
    assert _book(ChannelType.VOICE) == ChannelType.VOICE


def test_outbound_call_booking_is_still_outbound_call():
    assert _book(ChannelType.OUTBOUND_CALL) == ChannelType.OUTBOUND_CALL


# ---- saying thank you after a booking must not turn it into "abandoned" -----------------------

def _end_call(existing_outcome, **state):
    calls = []

    class _Repo:
        def __init__(self, db):
            pass

        async def get(self, conversation_id):
            return SimpleNamespace(outcome=existing_outcome)

        async def mark_ended(self, conversation_id):
            calls.append(("mark_ended", None))

        async def close(self, conversation_id, outcome, **_):
            calls.append(("close", outcome))

    original = end_call.ConversationRepository
    end_call.ConversationRepository = _Repo
    try:
        asyncio.run(end_call.end_call_node({"conversation_id": str(uuid.uuid4()), "intent": "close", **state}, None))
    finally:
        end_call.ConversationRepository = original
    return calls


def test_thank_you_after_a_booking_keeps_the_booked_outcome():
    assert _end_call(OutcomeType.BOOKED) == [("mark_ended", None)]


def test_thank_you_after_cancel_reschedule_or_handoff_keeps_the_outcome():
    for outcome in (OutcomeType.CANCELLED, OutcomeType.RESCHEDULED, OutcomeType.HANDED_TO_FRONT_DESK):
        assert _end_call(outcome) == [("mark_ended", None)]


def test_thank_you_with_nothing_done_is_still_abandoned():
    assert _end_call(None) == [("close", OutcomeType.ABANDONED)]


def test_closing_turn_does_not_reset_the_state_to_collecting_details():
    assert ConversationTurnService._conversation_state({"intent": "close", "is_verified": True}) is None
    assert ConversationTurnService._conversation_state({"intent": "faq_response", "is_verified": True}) is not None


# ---- misspelt specialties still match, ordinary words do not ----------------------------------

SPECIALTIES = ["cardiology", "dermatology", "ent", "general medicine", "gynecology", "orthopedics", "pediatrics"]


def _match(word):
    return difflib.get_close_matches(word, SPECIALTIES, n=1, cutoff=0.75)


def test_misspelt_specialties_are_matched():
    assert _match("cordiologu") == ["cardiology"]
    assert _match("dermatolgy") == ["dermatology"]
    assert _match("orthopedic") == ["orthopedics"]


def test_ordinary_words_are_not_mistaken_for_specialties():
    for word in ("appointment", "afternoon", "morning", "branch", "doctor", "available", "tambaram", "reschedule"):
        assert not _match(word), word
