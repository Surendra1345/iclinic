"""Confirmation node — triggers SMS/Email notifications after booking/reschedule/cancel."""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
# pyrefly: ignore[missing-import]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.control.agents.state import CallState
from src.utils.appointment_time import format_appointment_time
from src.constants.enums import ConfirmationStatusType
from src.data.models.postgres.appointment import Appointment
from src.data.models.postgres.appointment_type import AppointmentType
from src.data.repositories.conversation_repository import ConversationRepository
from src.core.services import deferred_tasks
from src.core.services.notification_service import NotificationService
from src.data.clients.postgres import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def _appointment_type_details(db: AsyncSession, appointment_id: str) -> tuple[Optional[str], Optional[str]]:
    """Name and preparation instructions of the visit type booked on this appointment."""
    try:
        row = (
            await db.execute(
                select(AppointmentType.name, AppointmentType.instructions)
                .join(Appointment, Appointment.appointment_type_id == AppointmentType.id)
                .where(Appointment.id == uuid.UUID(appointment_id))
            )
        ).first()
    except Exception:
        logger.warning("Could not load appointment type for %s", appointment_id, exc_info=True)
        return None, None
    return (row[0], row[1]) if row else (None, None)


def _confirmation_status(sms_tried: bool, sms_sent: bool, email_tried: bool, email_sent: bool) -> ConfirmationStatusType:
    """SENT when every attempted message went out; FLAGGED when any attempted message failed after its retries."""
    failed = (sms_tried and not sms_sent) or (email_tried and not email_sent)
    return ConfirmationStatusType.FLAGGED if failed else ConfirmationStatusType.SENT


async def _deliver_confirmations(
    *, convo_id: Optional[str], appointment_id: uuid.UUID, sms: Optional[dict], email: Optional[dict],
) -> None:
    """Send the confirmation text and email in their own session, then record how it went.

    Runs after the turn is saved, so the patient is not kept waiting on SMS and SMTP. Each channel is retried;
    if nothing reaches the patient the conversation is flagged so the front desk can follow up.
    """
    async with AsyncSessionLocal() as session:
        service = NotificationService(session)
        sms_sent = await service.send_confirmation_sms(appointment_id=appointment_id, **sms) if sms else False
        email_sent = await service.send_confirmation_email(appointment_id=appointment_id, **email) if email else False
        await session.commit()
        status = _confirmation_status(bool(sms), sms_sent, bool(email), email_sent)
        if convo_id:
            await ConversationRepository(session).record_confirmation_result(
                uuid.UUID(convo_id), status, delivered=sms_sent or email_sent
            )
        if status == ConfirmationStatusType.FLAGGED:
            logger.error(
                "Confirmation for appointment %s was not fully delivered (sms=%s, email=%s); conversation flagged",
                appointment_id, sms_sent, email_sent,
            )


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

            # What the patient needs to know beyond the time: the branch, the visit type and any preparation.
            appt_type_name, appt_instructions = await _appointment_type_details(db, appt_id_str)
            visit_details = {
                "location_name": slot_details.get("location_name"),
                "appointment_type": appt_type_name,
                "instructions": appt_instructions,
            }

            doctor_for_msg = slot_details.get("doctor_name", "your doctor")
            when_for_msg = slot_details.get("formatted_speech", "scheduled time")
            target_email = patient_email.strip() if patient_email and patient_email.strip() else None
            sms_kwargs = {
                "to_phone": patient_phone, "patient_name": patient_name, "doctor_name": doctor_for_msg,
                "start_time_str": when_for_msg, "action": action, **visit_details,
            } if patient_phone else None
            email_kwargs = {
                "to_email": target_email, "patient_name": patient_name, "doctor_name": doctor_for_msg,
                "start_time_str": when_for_msg, "action": action, **visit_details,
            } if target_email else None

            # Prefer sending after the turn is saved so the patient is not kept waiting.
            appointment_uuid = uuid.UUID(appt_id_str)
            sending_in_background = bool(sms_kwargs or email_kwargs) and deferred_tasks.defer(
                lambda: _deliver_confirmations(
                    convo_id=convo_id, appointment_id=appointment_uuid, sms=sms_kwargs, email=email_kwargs,
                )
            )
            if not sending_in_background:
                if sms_kwargs:
                    sms_sent = await notif_service.send_confirmation_sms(appointment_id=appointment_uuid, **sms_kwargs)
                if email_kwargs:
                    email_sent = await notif_service.send_confirmation_email(appointment_id=appointment_uuid, **email_kwargs)
                if convo_id:
                    await ConversationRepository(db).record_confirmation_result(
                        uuid.UUID(convo_id),
                        _confirmation_status(bool(sms_kwargs), sms_sent, bool(email_kwargs), email_sent),
                        delivered=sms_sent or email_sent,
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

            if action == "booked" and sending_in_background:
                if email_kwargs and sms_kwargs:
                    sent_to = f"by text message and to your email ({target_email})"
                elif email_kwargs:
                    sent_to = f"to your email ({target_email})"
                else:
                    sent_to = "to your phone by text message"
                speech = (
                    f"Your appointment with {doctor_name} at our {location_name} on {time_formatted} "
                    f"has been booked! I am sending a confirmation {sent_to}."
                )
            elif action == "booked":
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
                    f"has been booked, but I could not send the confirmation message. "
                    f"Our front desk will follow up with the details."
                    if (patient_phone or target_email)
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
