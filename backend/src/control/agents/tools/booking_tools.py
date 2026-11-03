"""Booking tools: look up a patient's active appointment, and create a booking."""
import uuid
from src.config.settings import settings
from typing import Any, Dict, Optional
# pyrefly: ignore[missing-import]
from sqlalchemy import select
# pyrefly: ignore[missing-import]
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import ChannelType
from src.data.models.postgres.conversation import Conversation
from src.data.models.postgres.appointment_type import AppointmentType
from src.data.repositories.appointment_repository import AppointmentRepository
from src.utils.appointment_time import format_appointment_time
from src.core.services.appointment_service import AppointmentService


async def check_patient_active_appointment(patient_id_str: str, db: AsyncSession) -> Optional[Dict[str, Any]]:
    """Find the patient's one active (booked) appointment.

    WHAT IT DOES: read-only lookup. Used before booking (a patient may hold only one active
    appointment) and before rescheduling or cancelling (to know which appointment is meant).
    INPUT: patient_id_str, the patient's id.
    RETURNS: None when the patient has no active appointment. Otherwise appointment_id, slot_id,
    status, doctor_name, specialty, location_name, start_time (ISO) and formatted_speech.
    CHANGES NOTHING except that an appointment whose time has already passed is marked completed first,
    so it never counts as active.
    """
    repo = AppointmentRepository(db)
    patient_id = uuid.UUID(patient_id_str)
    # An appointment whose time has passed is no longer active; it is completed here.
    await repo.complete_past_for_patient(patient_id)
    appt = await repo.get_active_for_patient(patient_id)
    if not appt:
        return None

    slot_time = format_appointment_time(appt.slot.start_time) if appt.slot else "Scheduled time"
    doctor_name = appt.slot.provider.full_name if appt.slot and appt.slot.provider else "Doctor"
    specialty = appt.slot.provider.specialty if appt.slot and appt.slot.provider else "General Medicine"
    location_name = (
        appt.slot.provider.location.name
        if appt.slot and appt.slot.provider and appt.slot.provider.location
        else settings.CLINIC_NAME
    )
    return {
        "appointment_id": str(appt.id),
        "slot_id": str(appt.slot_id),
        "status": appt.status.value,
        "doctor_name": doctor_name,
        "specialty": specialty,
        "location_name": location_name,
        "start_time": appt.slot.start_time.isoformat() if appt.slot else "",
        "formatted_speech": f"{doctor_name} at our {location_name} on {slot_time}",
    }


async def book_appointment(
    patient_id_str: str,
    slot_id_str: str,
    conversation_id_str: str,
    db: AsyncSession,
    reason: Optional[str] = None,
    appointment_type_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Book a slot that is already held for this patient.

    WHAT IT DOES: turns a held slot into a confirmed appointment in one transaction. Only call it after
    identity is confirmed, a slot is held, and the patient answered a clear yes to the confirmation
    question asked in the previous turn.
    INPUT: patient_id_str, slot_id_str (the held slot), conversation_id_str (links the appointment to the
    chat or call), reason (short visit reason, optional), appointment_type_name (must be an active type;
    "General Consultation" is used when none is given).
    RETURNS: appointment_id, status and slot_id of the new appointment.
    RAISES: ValueError if the appointment type is not configured; AppointmentServiceError if the slot does
    not exist, is in the past, is already booked, or the patient already has an active appointment.
    """
    service = AppointmentService(db)
    patient_id = uuid.UUID(patient_id_str)
    slot_id = uuid.UUID(slot_id_str)
    try:
        conversation_id = uuid.UUID(str(conversation_id_str)) if conversation_id_str else uuid.uuid4()
    except Exception:
        conversation_id = uuid.uuid4()

    # The appointment belongs to the channel (chat / voice / outbound_call) of its conversation.
    conversation = await db.get(Conversation, conversation_id)
    channel = conversation.channel if conversation is not None else ChannelType.OUTBOUND_CALL

    requested_type = (appointment_type_name or "General Consultation").strip()
    type_result = await db.execute(
        select(AppointmentType)
        .where(
            AppointmentType.is_active.is_(True),
            AppointmentType.name.ilike(requested_type),
        )
        .order_by(AppointmentType.name)
        .limit(1)
    )
    appt_type = type_result.scalars().first()
    if not appt_type:
        if requested_type.casefold() != "general consultation":
            raise ValueError(f"Active appointment type '{requested_type}' is not configured.")
        appt_type = AppointmentType(
            id=uuid.uuid4(),
            name="General Consultation",
            duration_minutes=30,
            is_active=True,
        )
        db.add(appt_type)
        await db.flush()

    appt = await service.book_appointment_atomic(
        patient_id=patient_id,
        slot_id=slot_id,
        appointment_type_id=appt_type.id,
        conversation_id=conversation_id,
        channel=channel,
        reason=reason,
    )
    return {
        "appointment_id": str(appt.id),
        "status": appt.status.value,
        "slot_id": str(appt.slot_id),
    }

