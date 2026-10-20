"""Confirmation node — triggers SMS/Email notifications after booking/reschedule/cancel."""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict
# pyrefly: ignore[missing-import]
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.control.agents.state import CallState
from src.control.agents.tools.appointment_time import format_appointment_time
from src.constants.enums import ConfirmationStatusType
from src.data.repositories.conversation_repository import ConversationRepository
from src.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


async def send_confirmation_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    patient_phone = state.get("patient_phone")
    patient_name = state.get("patient_name", "Valued Patient")
    # The patient record is authoritative. Conversation/request state may hold
    # a stale address (or a sender/front-desk address supplied by the UI).
    patient_email = None
    appt_id_str = state.get("active_appointment_id")
    slot_details = state.get("target_slot_details") or state.get("active_appointment_details") or {}
    intent = state.get("intent", "booked")
    convo_id = state.get("conversation_id")

    # If patient_email not in state, look up patient in DB if patient_id is present
    if state.get("patient_id"):
        try:
            # pyrefly: ignore[missing-import]
            from src.data.models.postgres.patient import Patient
            p_obj = await db.get(Patient, uuid.UUID(state["patient_id"]))
            if p_obj and p_obj.email:
                patient_email = p_obj.email
        except Exception:
            pass
    if not patient_email:
        patient_email = state.get("patient_email")

    if appt_id_str:
        try:
            notif_service = NotificationService(db)
            action = "booked"
            if intent == "reschedule":
                action = "rescheduled"
            elif intent == "cancel":
                action = "cancelled"

            sms_sent = False
            email_sent = False

            # 1. Deliver SMS confirmation to patient phone
            if patient_phone:
                sms_sent = await notif_service.send_confirmation_sms(
                    appointment_id=uuid.UUID(appt_id_str),
                    to_phone=patient_phone,
                    patient_name=patient_name,
                    doctor_name=slot_details.get("doctor_name", "your doctor"),
                    start_time_str=slot_details.get("formatted_speech", "scheduled time"),
                    action=action,
                )

            # 2. Deliver Email confirmation strictly to the patient's email
            target_email = patient_email.strip() if patient_email and patient_email.strip() else None
            if target_email:
                res_email = await notif_service.send_confirmation_email(
                    appointment_id=uuid.UUID(appt_id_str),
                    to_email=target_email,
                    patient_name=patient_name,
                    doctor_name=slot_details.get("doctor_name", "your doctor"),
                    start_time_str=slot_details.get("formatted_speech", "scheduled time"),
                    action=action,
                )
                if res_email:
                    email_sent = True

            if convo_id:
                repo = ConversationRepository(db)
                await repo.update_confirmation_status(
                    uuid.UUID(convo_id),
                    ConfirmationStatusType.SENT
                    if (sms_sent or email_sent)
                    else ConfirmationStatusType.FAILED,
                )

            start_iso = slot_details.get("start_time")
            if start_iso:
                try:
                    if isinstance(start_iso, str):
                        dt = datetime.fromisoformat(start_iso)
                    else:
                        dt = start_iso
                    time_formatted = format_appointment_time(dt)
                except Exception:
                    time_formatted = str(start_iso)
            else:
                raw_speech = slot_details.get("formatted_speech") or ""
                time_formatted = raw_speech.split(" on ")[-1] if " on " in raw_speech else (raw_speech or "your scheduled time")

            doctor_name = slot_details.get("doctor_name") or "your doctor"
            location_name = slot_details.get("location_name") or "our clinic"

            if action == "booked":
                if email_sent and sms_sent:
                    detail_channel = f"by text message and to your email ({target_email})"
                elif email_sent:
                    detail_channel = f"to your email ({target_email})"
                elif sms_sent:
                    detail_channel = "to your phone via text message"
                else:
                    detail_channel = "with our front desk"

                speech = (
                    f"Your appointment with {doctor_name} at our {location_name} on {time_formatted} "
                    f"has been booked! We have sent a confirmation {detail_channel}."
                    if (email_sent or sms_sent)
                    else f"Your appointment with {doctor_name} at our {location_name} on {time_formatted} "
                    f"has been booked! Your details are confirmed with our front desk."
                )
            elif action == "rescheduled":
                speech = (
                    f"Your appointment with {doctor_name} has been rescheduled to {time_formatted}."
                )
            else:
                speech = (
                    f"Your appointment with {doctor_name} on {time_formatted} has been cancelled."
                )

            return {
                "is_completed": True,
                "target_slot_id": None,
                "target_slot_details": None,
                "latest_agent_speech": speech,
            }
        except Exception as e:
            logger.error("Failed to send appointment notifications: %s", e)
            return {
                "is_completed": True,
                "latest_agent_speech": (
                    "Your appointment action was completed, but I had trouble delivering the "
                    "confirmation message. Please contact the clinic if you need the details."
                ),
            }

    return {
        "is_completed": True,
    }
