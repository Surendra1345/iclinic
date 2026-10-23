"""Appointment-history helpers for follow-up consultation booking."""
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.utils.appointment_time import CLINIC_TIMEZONE, format_appointment_time
from src.data.repositories.appointment_repository import AppointmentRepository


async def get_followup_candidates(patient_id: str, db: AsyncSession) -> list[dict[str, Any]]:
    """Return recent completed visits with enough detail to select the follow-up context."""
    appointments = await AppointmentRepository(db).get_recent_completed_for_patient(
        uuid.UUID(str(patient_id)), limit=5
    )
    candidates = []
    for appointment in appointments:
        slot = appointment.slot
        provider = slot.provider if slot else None
        location = provider.location if provider else None
        if not slot or not provider:
            continue
        local_start = slot.start_time
        if local_start.tzinfo is None:
            local_start = local_start.replace(tzinfo=CLINIC_TIMEZONE)
        else:
            local_start = local_start.astimezone(CLINIC_TIMEZONE)
        candidates.append({
            "appointment_id": str(appointment.id),
            "doctor_name": provider.full_name,
            "specialty": provider.specialty,
            "location_name": location.name if location else None,
            "start_time": slot.start_time.isoformat(),
            "visit_date": local_start.date().isoformat(),
            "formatted_date": format_appointment_time(slot.start_time),
        })
    return candidates


def followup_candidate_prompt(candidates: list[dict[str, Any]]) -> str:
    if len(candidates) == 1:
        visit = candidates[0]
        branch = f" at {visit['location_name']}" if visit.get("location_name") else ""
        return (
            f"I found your previous visit with {visit['doctor_name']} ({visit['specialty']})"
            f"{branch} on {visit['formatted_date']}. What date and time would you prefer for your follow-up?"
        )
    options = "; ".join(
        f"{index}. {visit['doctor_name']} ({visit['specialty']}) on {visit['formatted_date']}"
        for index, visit in enumerate(candidates, start=1)
    )
    return f"I found several previous visits: {options}. Which visit is this follow-up for?"
