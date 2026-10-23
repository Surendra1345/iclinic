"""Start conversation node — initialize state and database record."""
import uuid
from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.state import CallState
from src.constants.enums import ChannelType, ConversationState
from src.data.repositories.conversation_repository import ConversationRepository


async def start_conversation_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    """Initialize DB conversation and prime state."""
    repo = ConversationRepository(db)
    channel_str = state.get("channel", "outbound_call")
    channel_enum = ChannelType(channel_str) if channel_str in [e.value for e in ChannelType] else ChannelType.OUTBOUND_CALL

    convo_id = state.get("conversation_id")
    if not convo_id:
        convo = await repo.create(
            channel=channel_enum,
            call_sid=state.get("call_sid"),
        )
        convo_id = str(convo.id)
        return {
            "conversation_id": convo_id,
            "silence_count": 0,
            "verify_attempts": 0,
            "is_verified": state.get("is_verified", False),
            "is_new_patient": state.get("is_new_patient", False),
            "booking_confirmed": False,
            "handoff_required": False,
            "is_completed": False,
        }

    # A completed handoff is historical. Clear its routing flags before handling
    # a later message in the same chat so it cannot trigger duplicate alerts.
    if (
        (state.get("handoff_completed") or state.get("handoff_required"))
        and not state.get("awaiting_handoff_contact")
    ):
        return {
            "conversation_id": convo_id,
            "handoff_required": False,
            "handoff_reason": None,
            "awaiting_handoff_contact": False,
            "handoff_completed": False,
            "frontdesk_alert_sent": False,
            "patient_name": state.get("patient_name") if state.get("is_verified") else None,
            "awaiting_identity_verification": False,
            "is_new_patient": False,
            "is_emergency": False,
            "pending_intent": None,
            "intent": None,
            "is_completed": False,
        }

    # The checkpointer carries state between turns, so per-turn outcome flags must be
    # reset here. Otherwise a past booking/cancel keeps routing later turns to the
    # confirmation step with stale data. All other state is preserved.
    turn_reset: Dict[str, Any] = {
        "conversation_id": convo_id,
        "booking_confirmed": False,
        "is_completed": False,
    }
    if state.get("booking_confirmed") and state.get("intent") == "cancel":
        # The cancelled appointment is no longer active; later turns must not act on it.
        turn_reset.update({
            "active_appointment_id": None,
            "active_appointment_details": None,
            "awaiting_cancel_confirmation": False,
            "awaiting_change_action_choice": False,
            "target_slot_id": None,
            "target_slot_details": None,
            "offered_slots": [],
            "intent": None,
            "pending_intent": None,
        })
    return turn_reset

