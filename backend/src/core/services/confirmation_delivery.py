"""Sending the SMS and email after a booking, reschedule or cancellation, and the front-desk alert.

Both run after the turn has been saved (see core/services/deferred_tasks.py), each in its own database
session, so the patient never waits on them and a message is never sent for a turn that was rolled back.
"""
import logging
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import ConfirmationStatusType
from src.core.services import deferred_tasks
from src.core.services.notification_service import NotificationService
from src.data.clients.postgres import AsyncSessionLocal
from src.data.models.postgres.appointment import Appointment
from src.data.models.postgres.appointment_type import AppointmentType
from src.data.models.postgres.patient import Patient
from src.data.repositories.conversation_repository import ConversationRepository

logger = logging.getLogger(__name__)


def confirmation_status(sms_tried: bool, sms_sent: bool, email_tried: bool, email_sent: bool) -> ConfirmationStatusType:
    """SENT when every attempted message went out; FLAGGED when any attempted message failed after its retries."""
    failed = (sms_tried and not sms_sent) or (email_tried and not email_sent)
    return ConfirmationStatusType.FLAGGED if failed else ConfirmationStatusType.SENT


async def appointment_type_details(db: AsyncSession, appointment_id: str) -> tuple[Optional[str], Optional[str]]:
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


async def queue_confirmation(
    db: AsyncSession,
    *,
    action: str,                      # booked | rescheduled | cancelled
    appointment_id: str,
    conversation_id: Optional[str],
    patient_id: Optional[str],
    patient_name: Optional[str],
    patient_phone: Optional[str],
    patient_email: Optional[str],
    slot: Dict[str, Any],
) -> Dict[str, Any]:
    """Queue the messages for after the turn is saved. Returns who will be contacted, for the reply."""
    email = None
    if patient_id:
        try:
            patient = await db.get(Patient, uuid.UUID(patient_id))
            email = (patient.email or "").strip() if patient and patient.email else None
        except Exception:
            logger.warning("Could not load patient email for confirmation", exc_info=True)
    email = email or ((patient_email or "").strip() or None)

    type_name, instructions = await appointment_type_details(db, appointment_id)
    common = {
        "patient_name": patient_name or "Valued Patient",
        "doctor_name": slot.get("doctor_name") or "your doctor",
        "start_time_str": slot.get("spoken_time") or slot.get("formatted_speech") or "scheduled time",
        "action": action,
        "location_name": slot.get("location_name"),
        "appointment_type": type_name,
        "instructions": instructions,
    }
    sms = {"to_phone": patient_phone, **common} if patient_phone else None
    mail = {"to_email": email, **common} if email else None
    appointment_uuid = uuid.UUID(appointment_id)

    queued = bool(sms or mail) and deferred_tasks.defer(
        lambda: _deliver(conversation_id, appointment_uuid, sms, mail)
    )
    if (sms or mail) and not queued:
        # Nobody is collecting deferred jobs (a script or test): send now in this session.
        service = NotificationService(db)
        sms_sent = await service.send_confirmation_sms(appointment_id=appointment_uuid, **sms) if sms else False
        email_sent = await service.send_confirmation_email(appointment_id=appointment_uuid, **mail) if mail else False
        if conversation_id:
            await ConversationRepository(db).record_confirmation_result(
                uuid.UUID(conversation_id),
                confirmation_status(bool(sms), sms_sent, bool(mail), email_sent),
                delivered=sms_sent or email_sent,
            )
    return {"sms": bool(sms), "email": bool(mail), "email_address": email}


async def _deliver(
    conversation_id: Optional[str], appointment_id: uuid.UUID, sms: Optional[dict], mail: Optional[dict]
) -> None:
    """Send the text and email in their own session, then record how it went."""
    async with AsyncSessionLocal() as session:
        service = NotificationService(session)
        sms_sent = await service.send_confirmation_sms(appointment_id=appointment_id, **sms) if sms else False
        email_sent = await service.send_confirmation_email(appointment_id=appointment_id, **mail) if mail else False
        await session.commit()
        status = confirmation_status(bool(sms), sms_sent, bool(mail), email_sent)
        if conversation_id:
            await ConversationRepository(session).record_confirmation_result(
                uuid.UUID(conversation_id), status, delivered=sms_sent or email_sent
            )
        if status == ConfirmationStatusType.FLAGGED:
            logger.error(
                "Confirmation for appointment %s was not fully delivered (sms=%s, email=%s); conversation flagged",
                appointment_id, sms_sent, email_sent,
            )


def queue_frontdesk_alert(*, conversation_id: Optional[str], reason: str, call_details: Dict[str, Any]) -> bool:
    """Alert the front desk after the turn is saved. Returns False when it would have to run inline."""
    return deferred_tasks.defer(lambda: _alert(conversation_id, reason, call_details))


async def _alert(conversation_id: Optional[str], reason: str, call_details: Dict[str, Any]) -> None:
    async with AsyncSessionLocal() as session:
        sent = await NotificationService(session).send_frontdesk_alert_email(reason=reason, call_details=call_details)
        if conversation_id:
            await ConversationRepository(session).update_collected_details(
                uuid.UUID(conversation_id), {"frontdesk_alert_sent": bool(sent)}
            )
        if not sent:
            logger.warning("Front desk alert was not delivered for conversation %s", conversation_id)
