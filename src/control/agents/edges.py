"""Routing logic and conditional edges for the LangGraph agent."""
from langgraph.graph import END

from src.control.agents.state import CallState


def route_after_start(state: CallState) -> str:
    """Decide where to route immediately after start_conversation_node."""
    if state.get("handoff_required"):
        return "handoff"
    if state.get("is_verified"):
        return "detect_intent"
    if state.get("is_new_patient"):
        return "register"
    return "greet"


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
    if state.get("is_verified"):
        return "detect_intent"
    return END


def route_after_intent(state: CallState) -> str:
    """Route by classified intent."""
    if state.get("handoff_required"):
        return "handoff"

    intent = state.get("intent")
    if intent == "handoff":
        return "handoff"
    elif intent == "reschedule":
        return "reschedule"
    elif intent == "cancel":
        return "cancel"
    elif intent == "book":
        return "booking"
    return "booking"


def route_after_action(state: CallState) -> str:
    """Route after booking, reschedule, or cancel attempt."""
    if state.get("handoff_required"):
        return "handoff"
    if state.get("booking_confirmed"):
        return "confirmation"
    return END
