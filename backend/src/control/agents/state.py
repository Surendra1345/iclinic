"""Agent state for one conversation, and how it is rebuilt at the start of every turn.

The database row (`conversations.collected_details`) is the single source of truth. Every turn starts
from `build_input_state`, which sets every persisted field explicitly, so nothing stale can survive in
a LangGraph checkpoint after a turn was rolled back.
"""
import copy
from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict

# What the conversation is waiting for, derived from the state after every turn (for the transcript log and
# the front-desk dashboard). The agent itself decides what to say next.
AWAITING_HANDOFF_CONTACT = "handoff_contact"            # callback phone or email for the front desk
AWAITING_BOOKING_CONFIRMATION = "booking_confirmation"
AWAITING_RESCHEDULE_CONFIRMATION = "reschedule_confirmation"
AWAITING_CANCEL_CONFIRMATION = "cancel_confirmation"
CONFIRMATION_STEPS = (AWAITING_BOOKING_CONFIRMATION, AWAITING_RESCHEDULE_CONFIRMATION, AWAITING_CANCEL_CONFIRMATION)
CONFIRMATION_AWAITING = {
    "book": AWAITING_BOOKING_CONFIRMATION, "reschedule": AWAITING_RESCHEDULE_CONFIRMATION, "cancel": AWAITING_CANCEL_CONFIRMATION,
}


class CallState(TypedDict, total=False):
    # ── Session ───────────────────────────────────────────────────────────────
    conversation_id: str
    call_sid: str
    channel: str                      # chat | voice_assistant | outbound_call
    patient_phone: str                # the number on the call, or the callback number the patient gave
    callback_contact_unavailable: bool

    # ── Patient ───────────────────────────────────────────────────────────────
    patient_id: Optional[str]
    patient_name: Optional[str]
    patient_dob: Optional[str]        # ISO date
    patient_email: Optional[str]
    is_verified: bool                 # only name + date of birth match (or registration) sets this
    verify_attempts: int

    # ── Flow ──────────────────────────────────────────────────────────────────
    intent: Optional[str]             # last action worked on: book | reschedule | cancel
    awaiting: Optional[str]           # see AWAITING_* above
    pending_confirmation: Optional[Dict[str, Any]]  # the yes/no question asked last turn: action + what it covers

    # ── Dialogue ──────────────────────────────────────────────────────────────
    messages: List[Dict[str, Any]]
    latest_user_speech: str
    latest_agent_speech: str
    preferred_language: str
    language_confirmed: bool
    language_confidence: float
    speech_localized: bool

    # ── Appointment and slot context ──────────────────────────────────────────
    active_appointment_id: Optional[str]
    active_appointment_details: Optional[Dict[str, Any]]
    target_slot_id: Optional[str]     # the slot currently held for this patient
    target_slot_details: Optional[Dict[str, Any]]
    offered_slots: Optional[List[Dict[str, Any]]]
    booking_confirmed: bool           # a booking, reschedule or cancellation was completed this turn

    # ── Control ───────────────────────────────────────────────────────────────
    handoff_required: bool
    handoff_reason: Optional[str]
    handoff_completed: bool
    frontdesk_alert_sent: bool
    is_emergency: bool
    is_completed: bool
    wrong_person: bool

    # ── Internal to one turn (never stored) ───────────────────────────────────
    event: Optional[str]              # call_connected | session_started | no_speech
    choices: List[Dict[str, str]]     # tap-to-answer buttons for the web chat
    end_outcome: Optional[str]        # wrong_person | abandoned | ended, set when the conversation finishes
    end_reason: Optional[str]


# Stored in conversations.collected_details after every successful turn, with the value a new
# conversation starts with. Mutable defaults are copied on use.
PERSISTED_DEFAULTS: Dict[str, Any] = {
    "patient_phone": "", "callback_contact_unavailable": False,
    "patient_id": None, "patient_name": None, "patient_dob": None, "patient_email": None,
    "verify_attempts": 0,
    "intent": None, "awaiting": None, "pending_confirmation": None,
    "preferred_language": None, "language_confirmed": False, "language_confidence": None,
    "active_appointment_id": None, "active_appointment_details": None,
    "target_slot_id": None, "target_slot_details": None, "offered_slots": [],
    "handoff_required": False, "handoff_reason": None, "handoff_completed": False,
    "frontdesk_alert_sent": False, "is_emergency": False,
    "is_completed": False, "booking_confirmed": False,
}
PERSISTED_FIELDS = tuple(PERSISTED_DEFAULTS) + ("is_verified",)


def build_input_state(
    conversation: Any,
    *,
    channel: str,
    call_sid: str,
    speech: str,
    patient_phone: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Agent input for one turn, rebuilt entirely from the stored conversation.

    `conversation` is a Conversation row (or any object with collected_details, messages,
    identity_verified_at, patient_id and id). `extra` overrides after the stored values, for values only
    the caller knows, such as the language a voice session detected.
    """
    saved = dict(getattr(conversation, "collected_details", None) or {})
    state: Dict[str, Any] = {
        field: copy.deepcopy(saved[field]) if field in saved else copy.deepcopy(default)
        for field, default in PERSISTED_DEFAULTS.items()
    }
    messages = list(getattr(conversation, "messages", None) or [])
    last_agent = next((m.get("content") for m in reversed(messages) if m.get("role") == "agent"), "")
    state.update({
        "conversation_id": str(conversation.id),
        "call_sid": call_sid,
        "channel": channel,
        "patient_phone": patient_phone or saved.get("patient_phone") or "",
        "latest_user_speech": (speech or "").strip(),
        "latest_agent_speech": last_agent or "",
        "messages": messages,
        # A phone number or contact detail is never proof of identity: only the stored
        # verification time (set after name + date of birth matched) opens the gate.
        "is_verified": bool(getattr(conversation, "identity_verified_at", None)),
        # A new turn never inherits last turn's internal results.
        "event": None, "choices": [],
        "end_outcome": None, "end_reason": None,
        "wrong_person": False, "speech_localized": False,
    })
    linked_patient_id = getattr(conversation, "patient_id", None)
    if linked_patient_id and not state.get("patient_id"):
        state["patient_id"] = str(linked_patient_id)
    if extra:
        state.update(extra)
    return state
