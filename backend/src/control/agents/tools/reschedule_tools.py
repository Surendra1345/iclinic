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
    """Execute atomic reschedule."""
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

