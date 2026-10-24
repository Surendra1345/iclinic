"""Persistence and atomic execution for a confirmed new booking."""
import logging
import uuid
from datetime import date
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.tools.booking_tools import book_appointment
from src.control.agents.tools.slot_tools import release_slot
from src.constants.enums import PatientSource
from src.data.repositories.conversation_repository import ConversationRepository
from src.data.repositories.patient_repository import PatientRepository
from src.observability.metrics import booking_outcomes_total
from src.control.agents.nodes.booking_helpers import _clean_loc, _format_slot_time_str

logger = logging.getLogger(__name__)

async def _execute_booking(
    *,
    target_slot_id: str,
    target_slot: Dict[str, Any],
    patient_id: Optional[str],
    patient_phone: Optional[str],
    patient_name: Optional[str],
    patient_email: Optional[str],
    convo_id: Optional[str],
    appointment_type_name: Optional[str],
    repo: ConversationRepository,
    db: AsyncSession,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        # Ensure patient record exists (registration if not registered)
        if not patient_id:
            patient_repo = PatientRepository(db)
            patient = None
            if patient_phone:
                patient = await patient_repo.lookup_by_phone(patient_phone)
            if not patient:
                patient = await patient_repo.create_patient(
                    full_name=patient_name or "Valued Patient",
                    date_of_birth=date(1990, 1, 1),
                    phone=patient_phone or "+919876543210",
                    email=patient_email,
                    source=PatientSource.ASSISTANT,
                )
            patient_id = str(patient.id)
        else:
            # pyrefly: ignore[missing-import]
            from src.data.models.postgres.patient import Patient
            p_obj = await db.get(Patient, uuid.UUID(patient_id))
            if p_obj:
                if patient_name and patient_name not in ("Clinic Guest", "Valued Patient") and (not p_obj.full_name or p_obj.full_name in ("Clinic Guest", "Valued Patient")):
                    p_obj.full_name = patient_name
                if patient_email and (not p_obj.email or p_obj.email != patient_email):
                    p_obj.email = patient_email
                await db.flush()

        res = await book_appointment(
            patient_id_str=patient_id,
            slot_id_str=target_slot_id,
            conversation_id_str=convo_id,
            db=db,
            appointment_type_name=appointment_type_name,
            reason=reason,
        )
        # Conversation state is persisted by the shared turn service after
        # this action succeeds. Avoid a mid-turn commit so cancellation rolls
        # back the appointment and slot together.
        booking_outcomes_total.labels("book", "success").inc()

        time_str = _format_slot_time_str(target_slot["start_time"])
        appointment_label = appointment_type_name or "General Consultation"
        speech = (
            f"Your {appointment_label} appointment with {target_slot.get('doctor_name')} at our "
            f"{_clean_loc(target_slot.get('location_name'))} branch on {time_str} "
            f"has been booked!"
        )
        return {
            "booking_confirmed": True,
            "active_appointment_id": res["appointment_id"],
            "patient_id": patient_id,
            "patient_name": patient_name,
            "patient_email": patient_email,
            "awaiting_patient_email": False,
            "is_completed": True,
            "latest_agent_speech": speech,
        }
    except Exception as e:
        booking_outcomes_total.labels("book", "failed").inc()
        logger.error(f"Booking execution failed: {e}")
        try:
            await db.rollback()
        except Exception:
            pass
        try:
            await release_slot(target_slot_id, db)
        except Exception:
            pass
        return {
            "handoff_required": True,
            "handoff_reason": f"Booking failure: {str(e)}",
            "latest_agent_speech": "I had trouble securing that slot in our system. Let me transfer you to our receptionist to complete your booking.",
        }
