"""Confirmation node — triggers SMS/Email notifications after booking/reschedule/cancel."""
import logging
import uuid
from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.state import CallState
from src.constants.enums import ConfirmationStatusType
from src.data.repositories.conversation_repository import ConversationRepository
from src.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


async def send_confirmation_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    patient_phone = state.get("patient_phone")
    patient_name = state.get("patient_name", "Valued Patient")
    patient_email = state.get("patient_email")
    appt_id_str = state.get("active_appointment_id")
    slot_details = state.get("target_slot_details") or state.get("active_appointment_details") or {}
    intent = state.get("intent", "booked")
    convo_id = state.get("conversation_id")

    if appt_id_str and patient_phone:
        try:
            notif_service = NotificationService(db)
            action = "booked"
            if intent == "reschedule":
                action = "rescheduled"
            elif intent == "cancel":
                action = "cancelled"

            sms_sent = await notif_service.send_confirmation_sms(
                appointment_id=uuid.UUID(appt_id_str),
                to_phone=patient_phone,
                patient_name=patient_name,
                doctor_name=slot_details.get("doctor_name", "your doctor"),
                start_time_str=slot_details.get("formatted_speech", "scheduled time"),
                action=action,
            )

            email_sent = True
            if patient_email:
                email_sent = await notif_service.send_confirmation_email(
                    appointment_id=uuid.UUID(appt_id_str),
                    to_email=patient_email,
                    patient_name=patient_name,
                    doctor_name=slot_details.get("doctor_name", "your doctor"),
                    start_time_str=slot_details.get("formatted_speech", "scheduled time"),
                    action=action,
                )
            else:
                logger.info(
                    "No email address is stored for patient %s; email confirmation skipped",
                    state.get("patient_id"),
                )

            if convo_id:
                repo = ConversationRepository(db)
                await repo.update_confirmation_status(
                    uuid.UUID(convo_id),
                    ConfirmationStatusType.SENT
                    if sms_sent and email_sent
                    else ConfirmationStatusType.FAILED,
                )

            if not sms_sent or not email_sent:
                failed_channels = []
                if not sms_sent:
                    failed_channels.append("text message")
                if not email_sent:
                    failed_channels.append("email")
                return {
                    "is_completed": True,
                    "latest_agent_speech": (
                        f"Your appointment action was completed, but we could not deliver the "
                        f"confirmation by {' and '.join(failed_channels)}. "
                        "Please contact the clinic if you need the appointment details."
                    ),
                }
        except Exception as e:
            logger.error("Failed to send appointment notifications: %s", e)
            return {
                "is_completed": True,
                "latest_agent_speech": (
                    "Your appointment action was completed, but I could not deliver the "
                    "confirmation message. Please contact the clinic if you need the details."
                ),
            }

    return {
        "is_completed": True,
    }
