"""Booking tools ??? checking active appointments and creating bookings."""
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
    """
    Check if patient already has an active (booked) appointment.
    Returns details if exists, or None.
    """
    repo = AppointmentRepository(db)
    patient_id = uuid.UUID(patient_id_str)
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
    """Execute atomic booking."""
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

