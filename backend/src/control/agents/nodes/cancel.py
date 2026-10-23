"""Cancel agent node ??? handles appointment cancellation with cutoff policy."""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.state import CallState
from src.control.agents.tools.booking_tools import check_patient_active_appointment
from src.control.agents.tools.cancel_tools import cancel_appointment
from src.config.settings import settings
from src.constants.enums import ConversationState
from src.data.repositories.conversation_repository import ConversationRepository
from src.observability.metrics import booking_outcomes_total
from src.control.agents.nodes.dialogue_guardrails import is_explicit_confirmation, is_explicit_rejection
from src.control.agents.tools.slot_tools import release_slot

logger = logging.getLogger(__name__)


async def cancel_agent_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    user_speech = state.get("latest_user_speech", "").strip().lower()
    patient_id = state.get("patient_id")
    convo_id = state.get("conversation_id")
    repo = ConversationRepository(db)

    # A patient can cancel after considering a held reschedule option. Release
    # that temporary hold before entering the cancellation confirmation flow.
    held_slot_id = state.get("target_slot_id")
    if held_slot_id:
        try:
            await release_slot(held_slot_id, db)
        except Exception:
            logger.warning("Could not release held slot %s before cancellation", held_slot_id)

    # 1. Fetch active appointment
    active_appt = state.get("active_appointment_details")
    if not active_appt and patient_id:
        active_appt = await check_patient_active_appointment(patient_id, db)

    if not active_appt:
        return {
            "latest_agent_speech": "I couldn't find an active appointment to cancel. Is there anything else I can assist you with?",
        }

    # 2. Check 24-hour cutoff
    start_time_iso = active_appt.get("start_time")
    if start_time_iso:
        try:
            start_dt = datetime.fromisoformat(start_time_iso)
            now = datetime.now(start_dt.tzinfo) if start_dt.tzinfo else datetime.utcnow()
            hours_diff = (start_dt - now).total_seconds() / 3600
            if hours_diff < settings.RESCHEDULE_CANCEL_CUTOFF_HOURS:
                return {
                    "handoff_required": True,
                    "handoff_reason": "Cancellation within 24-hour cutoff window",
                    "latest_agent_speech": (
                        f"Because your appointment is in less than {settings.RESCHEDULE_CANCEL_CUTOFF_HOURS} hours, "
                        "cancellations must be processed by our staff. Let me transfer you to the front desk."
                    ),
                }
        except Exception as e:
            logger.warning(f"Error parsing start time: {e}")

    # 3. Handle confirmation response
    awaiting_cancel_prompt = bool(
        state.get("awaiting_cancel_confirmation")
        or "are you sure you want to cancel" in (state.get("latest_agent_speech") or "").lower()
    )
    if awaiting_cancel_prompt and is_explicit_confirmation(user_speech):
        try:
            await cancel_appointment(
                appointment_id_str=active_appt["appointment_id"],
                conversation_id_str=convo_id,
                db=db,
                reason="Patient requested cancellation via voice call",
            )
            # The shared turn service records cancellation state after this
            # atomic action succeeds, without committing mid-turn.
            booking_outcomes_total.labels("cancel", "success").inc()

            return {
                "booking_confirmed": True,
                "target_slot_id": None,
                "target_slot_details": None,
                "awaiting_cancel_confirmation": False,
                "active_appointment_id": active_appt["appointment_id"],
                "active_appointment_details": active_appt,
                "latest_agent_speech": "Your appointment has been cancelled. We have sent a confirmation to your phone. Have a wonderful day!",
            }
        except Exception as e:
            booking_outcomes_total.labels("cancel", "failed").inc()
            logger.error(f"Cancellation failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass
            return {
                "handoff_required": True,
                "handoff_reason": f"Cancellation error: {str(e)}",
                "latest_agent_speech": "I had trouble processing the cancellation. Connecting you to our front desk team now.",
            }

    if awaiting_cancel_prompt and is_explicit_rejection(user_speech):
        return {
            "awaiting_cancel_confirmation": False,
            "target_slot_id": None,
            "target_slot_details": None,
            "latest_agent_speech": "No problem! I have kept your appointment as scheduled. Is there anything else I can help you with?",
        }

    # Initial prompt for confirmation
    return {
        "awaiting_cancel_confirmation": True,
        "target_slot_id": None,
        "target_slot_details": None,
        "active_appointment_details": active_appt,
        "latest_agent_speech": f"Are you sure you want to cancel your appointment for {active_appt['formatted_speech']}?",
    }

