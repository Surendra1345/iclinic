"""Start of every turn: reset what belongs to one turn, and spot system events.

A system event is not the patient talking (a call just connected, a session just opened, nothing was heard).
The agent still replies to it, from its instructions for that event.
"""
from typing import Any, Dict

from src.control.agents.state import AWAITING_HANDOFF_CONTACT

_NEW_REQUEST_RESET = {"offered_slots": [], "intent": None, "pending_confirmation": None, "awaiting": None}


async def gate_node(state: Dict[str, Any], db) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "booking_confirmed": False, "is_completed": False, "speech_localized": False,
        "event": None, "choices": [], "end_outcome": None, "end_reason": None,
    }

    # A hand-over ends the conversation; the next message starts clean (unless a callback contact is awaited).
    if (state.get("handoff_completed") or state.get("handoff_required")) and state.get("awaiting") != AWAITING_HANDOFF_CONTACT:
        out.update({
            "handoff_required": False, "handoff_reason": None, "handoff_completed": False, "frontdesk_alert_sent": False,
            "is_emergency": False, "callback_contact_unavailable": False, "verify_attempts": 0, **_NEW_REQUEST_RESET,
        })

    # After a finished booking, change or cancellation the next message is a new request.
    if state.get("booking_confirmed"):
        out.update(_NEW_REQUEST_RESET)

    if not (state.get("latest_user_speech") or "").strip():
        if state.get("channel") == "outbound_call":
            out["event"] = "call_connected"
        elif not state.get("messages"):
            out["event"] = "session_started"
        else:
            out["event"] = "no_speech"
    return out
