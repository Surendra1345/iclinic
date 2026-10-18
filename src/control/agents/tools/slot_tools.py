"""Slot discovery and reservation tools."""
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.repositories.slot_repository import SlotRepository
from src.control.agents.tools.appointment_time import format_appointment_time


def _format_slot(slot) -> Dict[str, Any]:
    doctor_name = slot.provider.full_name if slot.provider else "Doctor"
    specialty = slot.provider.specialty if slot.provider else "General"
    location_name = slot.provider.location.name if (slot.provider and slot.provider.location) else "City Care Clinic"
    location_address = slot.provider.location.address if (slot.provider and slot.provider.location) else ""
    start_dt = slot.start_time
    formatted_time = format_appointment_time(start_dt)
    return {
        "slot_id": str(slot.id),
        "doctor_name": doctor_name,
        "specialty": specialty,
        "location_name": location_name,
        "location_address": location_address,
        "start_time": slot.start_time.isoformat(),
        "formatted_speech": f"{doctor_name} at our {location_name} on {formatted_time}",
    }


async def get_available_slots(db: AsyncSession, limit: int = 3) -> List[Dict[str, Any]]:
    """Return available future slots."""
    repo = SlotRepository(db)
    slots = await repo.get_available_slots(limit=limit)
    return [_format_slot(s) for s in slots]


async def get_slots_by_doctor(doctor_name: str, db: AsyncSession, limit: int = 3) -> List[Dict[str, Any]]:
    """Return available future slots for a doctor."""
    repo = SlotRepository(db)
    slots = await repo.get_slots_by_doctor_name(doctor_name=doctor_name, limit=limit)
    return [_format_slot(s) for s in slots]


async def get_slots_by_specialty(specialty: str, db: AsyncSession, limit: int = 3) -> List[Dict[str, Any]]:
    """Return available future slots by specialty."""
    repo = SlotRepository(db)
    slots = await repo.get_slots_by_specialty(specialty=specialty, limit=limit)
    return [_format_slot(s) for s in slots]


async def get_slots_by_location(location_name: str, db: AsyncSession, limit: int = 3) -> List[Dict[str, Any]]:
    """Return available future slots for a specific clinic location/branch."""
    repo = SlotRepository(db)
    slots = await repo.get_slots_by_location(location_name=location_name, limit=limit)
    return [_format_slot(s) for s in slots]


async def get_slots_by_specialty_and_location(specialty: str, location_name: str, db: AsyncSession, limit: int = 3) -> List[Dict[str, Any]]:
    """Return available future slots matching both specialty and location."""
    repo = SlotRepository(db)
    slots = await repo.get_slots_by_specialty_and_location(specialty=specialty, location_name=location_name, limit=limit)
    return [_format_slot(s) for s in slots]


async def get_doctor_options_by_specialty(
    specialty: str,
    db: AsyncSession,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Return distinct doctor/location/time options without reserving a slot."""
    slots = await get_slots_by_specialty(specialty, db, limit=limit)
    options: List[Dict[str, Any]] = []
    seen = set()
    for slot in slots:
        key = (slot["doctor_name"], slot["location_name"], slot["start_time"])
        if key not in seen:
            seen.add(key)
            options.append(slot)
    return options


async def reserve_slot(slot_id_str: str, db: AsyncSession) -> bool:
    """Temporarily reserve a slot for the caller while they confirm."""
    repo = SlotRepository(db)
    slot_id = uuid.UUID(slot_id_str)
    return await repo.reserve_slot(slot_id)


async def release_slot(slot_id_str: str, db: AsyncSession) -> bool:
    """Release a reserved slot back to available."""
    repo = SlotRepository(db)
    slot_id = uuid.UUID(slot_id_str)
    return await repo.release_slot(slot_id)
