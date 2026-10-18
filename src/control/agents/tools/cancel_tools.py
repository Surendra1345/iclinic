"""Cancel tools for atomic appointment cancellation."""
import uuid
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.appointment_service import AppointmentService


async def cancel_appointment(
    appointment_id_str: str,
    conversation_id_str: str,
    db: AsyncSession,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute atomic cancellation."""
    service = AppointmentService(db)
    appointment_id = uuid.UUID(appointment_id_str)
    conversation_id = uuid.UUID(conversation_id_str)

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
