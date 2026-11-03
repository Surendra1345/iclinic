"""Cancel tools for atomic appointment cancellation."""
import uuid
from typing import Any, Dict, Optional
# pyrefly: ignore[missing-import]
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.services.appointment_service import AppointmentService


async def cancel_appointment(
    appointment_id_str: str,
    conversation_id_str: str,
    db: AsyncSession,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Cancel a patient's appointment and free its slot.

    WHAT IT DOES: marks the appointment cancelled, releases the slot for others and writes a cancellation
    record, all in one transaction. Only call it after identity is confirmed and the patient answered a
    clear yes to "are you sure you want to cancel?" in the previous turn.
    INPUT: appointment_id_str, conversation_id_str (links the record to the chat or call), reason (optional).
    RETURNS: appointment_id, status and cancellation_id.
    RAISES: AppointmentServiceError if the appointment is not found, is not active, or starts within the
    cutoff window (24 hours); the patient is then sent to the front desk.
    """
    service = AppointmentService(db)
    appointment_id = uuid.UUID(appointment_id_str)
    try:
        conversation_id = uuid.UUID(str(conversation_id_str)) if conversation_id_str else uuid.uuid4()
    except Exception:
        conversation_id = uuid.uuid4()

    appt, log = await service.cancel_appointment_atomic(
        appointment_id=appointment_id,
        conversation_id=conversation_id,
        reason=reason,
    )
    return {
        "appointment_id": str(appt.id),
        "status": appt.status.value,
        "cancellation_id": str(log.id),
    }

