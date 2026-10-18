"""Reschedule agent node — handles atomic rescheduling with cutoff and same-slot checks."""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.state import CallState
from src.control.agents.tools.booking_tools import check_patient_active_appointment
from src.control.agents.tools.reschedule_tools import reschedule_appointment
from src.control.agents.tools.slot_tools import get_available_slots, release_slot, reserve_slot
from src.config.settings import settings
from src.constants.enums import ConversationState
from src.data.repositories.conversation_repository import ConversationRepository
from src.observability.metrics import booking_outcomes_total

logger = logging.getLogger(__name__)


async def reschedule_agent_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    user_speech = state.get("latest_user_speech", "").strip().lower()
    patient_id = state.get("patient_id")
    convo_id = state.get("conversation_id")
    target_slot = state.get("target_slot_details")
    target_slot_id = state.get("target_slot_id")
    repo = ConversationRepository(db)

    # 1. Fetch current active appointment
    active_appt = state.get("active_appointment_details")
    if not active_appt and patient_id:
        active_appt = await check_patient_active_appointment(patient_id, db)

    if not active_appt:
        return {
            "latest_agent_speech": "I couldn't find an active appointment to reschedule. Would you like to book a new appointment instead?",
        }

    # 2. Check 24-hour cutoff policy
    start_time_iso = active_appt.get("start_time")
    if start_time_iso:
        try:
            start_dt = datetime.fromisoformat(start_time_iso)
            now = datetime.now(start_dt.tzinfo) if start_dt.tzinfo else datetime.utcnow()
            hours_diff = (start_dt - now).total_seconds() / 3600
            if hours_diff < settings.RESCHEDULE_CANCEL_CUTOFF_HOURS:
                return {
                    "handoff_required": True,
                    "handoff_reason": "Reschedule within 24-hour cutoff window",
                    "latest_agent_speech": (
                        f"Your appointment is in less than {settings.RESCHEDULE_CANCEL_CUTOFF_HOURS} hours. "
                        "Our clinic policy requires speaking with the front desk for late changes. Please hold while I connect you."
                    ),
                }
        except Exception as e:
            logger.warning(f"Failed parsing appointment start time: {e}")

    # 3. Check if caller is confirming an offered new slot
    if target_slot and target_slot_id:
        # Check same slot constraint
        if target_slot_id == active_appt.get("slot_id"):
            await release_slot(target_slot_id, db)
            return {
                "target_slot_id": None,
                "target_slot_details": None,
                "latest_agent_speech": "You are already booked for that same appointment slot! Would you like to pick a different date or time?",
            }

        if any(w in user_speech for w in ["yes", "confirm", "sure", "move it", "change it", "please", "okay", "fine"]):
            try:
                res = await reschedule_appointment(
                    appointment_id_str=active_appt["appointment_id"],
                    new_slot_id_str=target_slot_id,
                    conversation_id_str=convo_id,
                    db=db,
                )
                if convo_id:
                    await repo.update_state(uuid.UUID(convo_id), ConversationState.BOOKED)
                booking_outcomes_total.labels("reschedule", "success").inc()

                speech = (
                    f"Your appointment has been rescheduled to {target_slot.get('formatted_speech')}. "
                    "You will receive an updated SMS confirmation."
                )
                return {
                    "booking_confirmed": True,
                    "active_appointment_id": active_appt["appointment_id"],
                    "latest_agent_speech": speech,
                }
            except Exception as e:
                booking_outcomes_total.labels("reschedule", "failed").inc()
                logger.error(f"Reschedule failed: {e}")
                await release_slot(target_slot_id, db)
                return {
                    "handoff_required": True,
                    "handoff_reason": f"Reschedule failure: {str(e)}",
                    "latest_agent_speech": "I encountered an issue updating your appointment. Let me transfer you to our front desk.",
                }
        elif any(w in user_speech for w in ["no", "cancel", "don't", "different", "keep"]):
            await release_slot(target_slot_id, db)
            target_slot = None
            target_slot_id = None

    # 4. Find new available slots
    slots = await get_available_slots(db, limit=3)
    # Filter out current slot
    slots = [s for s in slots if s["slot_id"] != active_appt.get("slot_id")]

    if not slots:
        return {
            "handoff_required": True,
            "handoff_reason": "No alternative slots available to reschedule",
            "latest_agent_speech": "I don't have any other open slots right now. Let me connect you with the front desk to look into additional dates.",
        }

    first_slot = slots[0]
    await reserve_slot(first_slot["slot_id"], db)
    return {
        "active_appointment_details": active_appt,
        "target_slot_id": first_slot["slot_id"],
        "target_slot_details": first_slot,
        "latest_agent_speech": f"I have an opening for {first_slot['formatted_speech']}. Would you like me to move your appointment to that time?",
    }
