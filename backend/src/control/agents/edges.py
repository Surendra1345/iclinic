"""Routing logic and conditional edges for the LangGraph agent."""
import re
# pyrefly: ignore[missing-import]
from langgraph.graph import END

from src.control.agents.state import CallState


def route_after_start(state: CallState) -> str:
    """Decide where to route immediately after start_conversation_node."""
    if state.get("handoff_required"):
        return "handoff"
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

    # Defend the privacy gate at routing time as well as in intent detection:
    # a bare name from an unverified patient must never reach booking.
    speech = (state.get("latest_user_speech") or "").strip().lower()
    name_words = speech.rstrip(".!?").split()
    non_name_terms = {
        "book", "appointment", "schedule", "doctor", "cancel", "reschedule",
        "change", "help", "yes", "no", "hello", "hi",
    }
    if (
        not state.get("is_verified")
        and not state.get("is_new_patient")
        and len(name_words) <= 4
        and not any(word in non_name_terms for word in name_words)
        and re.fullmatch(r"[a-z][a-z'’-]*(?:\s+[a-z][a-z'’-]*){0,3}[.!?]?", speech)
    ):
        return "identity"

    intent = state.get("intent")
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
    elif intent == "faq_response":
        # These FAQ responses are composed directly by intent detection.
        return END
    return "booking"


def route_after_action(state: CallState) -> str:
    """Route after booking, reschedule, or cancel attempt."""
    if state.get("handoff_required"):
        return "handoff"
    if state.get("booking_confirmed"):
        return "confirmation"
    return END
