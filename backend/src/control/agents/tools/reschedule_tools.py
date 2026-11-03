"""Reschedule tools for atomic appointment rescheduling."""
import uuid
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.services.appointment_service import AppointmentService


async def reschedule_appointment(
    appointment_id_str: str,
    new_slot_id_str: str,
    conversation_id_str: str,
    db: AsyncSession,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Move an appointment to a new held slot and free the old slot.

    WHAT IT DOES: in one transaction, books the new slot, releases the old one and writes a reschedule
    record. Only call it after identity is confirmed, the new slot is held, and the patient answered a clear
    yes to the reschedule question in the previous turn.
    INPUT: appointment_id_str (the current appointment), new_slot_id_str (the held new slot),
    conversation_id_str (links the record to the chat or call), reason (optional).
    RETURNS: appointment_id, status, new_slot_id and reschedule_id.
    RAISES: AppointmentServiceError if the appointment is not found or not active, the new slot is missing,
    in the past or already booked, it is the same slot as before, or the current appointment starts within
    the cutoff window (24 hours); the patient is then sent to the front desk.
    """
    service = AppointmentService(db)
    appointment_id = uuid.UUID(appointment_id_str)
    new_slot_id = uuid.UUID(new_slot_id_str)
    try:
        conversation_id = uuid.UUID(str(conversation_id_str)) if conversation_id_str else uuid.uuid4()
    except Exception:
        conversation_id = uuid.uuid4()

    appt, log = await service.reschedule_appointment_atomic(
        appointment_id=appointment_id,
        new_slot_id=new_slot_id,
        conversation_id=conversation_id,
        reason=reason,
    )
    return {
        "appointment_id": str(appt.id),
        "status": appt.status.value,
        "new_slot_id": str(appt.slot_id),
        "reschedule_id": str(log.id),
    }

