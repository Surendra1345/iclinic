"""Routing logic and conditional edges for the LangGraph agent."""
import re
# pyrefly: ignore[missing-import]
from langgraph.graph import END

from src.control.agents.state import CallState
from src.control.agents.tools.registration_tools import is_name_only_candidate


_EXISTING_PATIENT_PHRASES = (
    "old patient", "existing patient", "already a patient", "already registered",
    "i am a patient", "i'm a patient", "i am an existing", "i'm an existing",
)
_NEW_PATIENT_PHRASES = (
    "new patient", "not registered", "first time", "i am new", "i'm new",
    "sign up", "register me", "i want to register",
)


def _contains_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    normalized = " ".join((text or "").lower().split())
    return any(phrase in normalized for phrase in phrases)


def route_after_start(state: CallState) -> str:
    """Decide where to route immediately after start_conversation_node."""
    if state.get("is_emergency") or state.get("awaiting_handoff_contact"):
        return "handoff"
    speech = state.get("latest_user_speech", "")
    if not state.get("is_verified") and _contains_phrase(speech, _NEW_PATIENT_PHRASES):
        return "identity"
    if not state.get("is_verified") and _contains_phrase(speech, _EXISTING_PATIENT_PHRASES):
        return "identity"
    if state.get("is_new_patient"):
        return "register"
    # On initial phone call connection before speech
    if not state.get("latest_user_speech") and not state.get("is_verified") and state.get("channel") in ("outbound_call", "voice", "inbound_call"):
        return "greet"
    return "detect_intent"


def route_after_identity(state: CallState) -> str:
    """Decide next step after identity check."""
    if state.get("handoff_required"):
        return "handoff"
    if state.get("is_new_patient"):
        return "register"
    # When identity is verified or prompt is given, await caller's spoken intent
    return END



def route_after_register(state: CallState) -> str:
    """Decide next step after registration check."""
    if state.get("handoff_required"):
        return "handoff"
    # Registration produces the patient-facing confirmation. Wait for the
    # next turn instead of routing into a new intent/action.
    return END


def route_after_intent(state: CallState) -> str:
    """Route by classified intent."""
    if state.get("handoff_required"):
        return "handoff"

    intent = state.get("intent")
    # Informational FAQ turns (including a branch answer during doctor
    # browsing) do not need identity verification and must not be mistaken for
    # a bare patient name by the privacy guard below.
    if intent == "faq_response":
        return END
    if intent == "faq":
        return "faq"
    # Unknown or absent intents must wait for clarification. Sending them to
    # booking silently assumes the patient wants an appointment.
    if intent in (None, "unknown"):
        return END

    # Defend the privacy gate at routing time as well as in intent detection:
    # a bare name from an unverified patient must never reach booking.
    speech = (state.get("latest_user_speech") or "").strip().lower()
    name_words = speech.rstrip(".!?").split()
    if (
        not state.get("is_verified")
        and not state.get("is_new_patient")
        and is_name_only_candidate(state.get("latest_user_speech") or "")
        and len(name_words) <= 4
        and re.fullmatch(r"[a-z][a-z'’-]*(?:\s+[a-z][a-z'’-]*){0,3}[.!?]?", speech)
    ):
        return "identity"

    if intent == "handoff":
        return "handoff"
    elif intent == "greet":
        return "greet"
    elif intent == "register":
        return "register"
    elif intent == "identity":
        if state.get("is_verified"):
            return "reschedule" if state.get("active_appointment_id") else (state.get("pending_intent") or "booking")
        return "identity"
    # Strict verification gate: Unverified patients requesting book/reschedule/cancel must verify identity first
    elif not state.get("is_verified") and intent in ("book", "reschedule", "cancel"):
        return "identity"
    elif intent == "reschedule":
        return "reschedule"
    elif intent == "cancel":
        return "cancel"
    elif intent == "book":
        return "booking"
    elif intent == "close":
        return "end_call"
    # Unknown/unsupported intents must not turn into an appointment request.
    return END


def route_after_action(state: CallState) -> str:
    """Route after booking, reschedule, or cancel attempt."""
    if state.get("handoff_required"):
        return "handoff"
    if state.get("booking_confirmed"):
        return "confirmation"
    return END
