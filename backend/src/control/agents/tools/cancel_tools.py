"""Cancel tools for atomic appointment cancellation."""
import uuid
from typing import Any, Dict, Optional
# pyrefly: ignore[missing-import]
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

