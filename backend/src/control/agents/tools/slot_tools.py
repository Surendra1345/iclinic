"""Slot search and hold actions. Plain database operations: no language handling.

Dates and times arrive already structured (ISO dates, HH:MM), passed by the agent model and
validated by the toolbox.
"""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

# pyrefly: ignore[missing-import]
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.data.repositories.slot_repository import SlotRepository
from src.utils.appointment_time import CLINIC_TIMEZONE, format_appointment_time


def format_slot(slot) -> Dict[str, Any]:
    """The one shape used for offered and held slots everywhere in the agent."""
    provider = slot.provider
    location = provider.location if provider else None
    doctor_name = provider.full_name if provider else "Doctor"
    location_name = location.name if location else settings.CLINIC_NAME
    start = slot.start_time
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    local = start.astimezone(CLINIC_TIMEZONE)
    return {
        "slot_id": str(slot.id),
        "doctor_name": doctor_name,
        "specialty": (provider.specialty if provider else None) or "General",
        "location_name": location_name,
        "location_address": (location.address if location else "") or "",
        "start_time": start.isoformat(),
        "local_date": local.date().isoformat(),
        "local_time": local.strftime("%H:%M"),
        "spoken_time": format_appointment_time(start),
        "formatted_speech": f"{doctor_name} at our {location_name} on {format_appointment_time(start)}",
    }


def parse_iso_date(value: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def parse_hhmm(value: Optional[str]) -> Optional[time]:
    if not value:
        return None
    try:
        hour, minute = str(value).strip()[:5].split(":")
        return time(int(hour), int(minute))
    except (ValueError, TypeError):
        return None


def clinic_today() -> date:
    return datetime.now(CLINIC_TIMEZONE).date()


def day_bounds_utc(first_day: date, last_day: Optional[date] = None) -> tuple[datetime, datetime]:
    """UTC start and end of the clinic-local days first_day..last_day inclusive."""
    last_day = last_day or first_day
    start = datetime.combine(first_day, time.min, tzinfo=CLINIC_TIMEZONE)
    end = datetime.combine(last_day + timedelta(days=1), time.min, tzinfo=CLINIC_TIMEZONE)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc) - timedelta(microseconds=1)


async def search_slots(
    db: AsyncSession,
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    specialty: Optional[str] = None,
    location_name: Optional[str] = None,
    doctor_name: Optional[str] = None,
    time_from: Optional[time] = None,
    time_to: Optional[time] = None,
    exclude_slot_ids: Sequence[str] = (),
    limit: int = 30,
) -> List[Dict[str, Any]]:
    """Find open future appointment times.

    WHAT IT DOES: read-only search, earliest first, that returns only slots matching every filter given.
    INPUT (all optional): date_from and date_to (clinic-local days), specialty, location_name, doctor_name,
    time_from and time_to (clinic-local time of day), exclude_slot_ids (slots already offered or refused),
    limit (default 30).
    RETURNS: a list of slots, each with slot_id, doctor_name, specialty, location_name, start_time and
    spoken_time (the exact wording to say aloud). An empty list means nothing matched; the caller then
    loosens time, then date, then branch, then doctor, and never the specialty.
    CHANGES NOTHING in the database.
    """
    start_utc = end_utc = None
    if date_from:
        start_utc, end_utc = day_bounds_utc(date_from, date_to)
    excluded = set(exclude_slot_ids)
    rows = await SlotRepository(db).get_slots_by_criteria(
        start_time_gte=start_utc,
        start_time_lte=end_utc,
        specialty=specialty,
        location_name=location_name,
        doctor_name=doctor_name,
        clinic_time_gte=time_from,
        clinic_time_lte=time_to,
        limit=limit + len(excluded),
    )
    slots = [format_slot(row) for row in rows if str(row.id) not in excluded]
    return slots[:limit]


async def reserve_slot(slot_id_str: str, db: AsyncSession) -> bool:
    """Hold a slot for the patient while they confirm.

    WHAT IT DOES: marks one available slot as reserved for a few minutes (SLOT_RESERVATION_TIMEOUT_MINUTES)
    so nobody else can take it while the patient decides. Nothing is booked yet.
    RAISES: SlotUnavailableError if the slot was just taken; the patient is then offered other times.
    """
    await SlotRepository(db).reserve_slot(uuid.UUID(slot_id_str))
    return True


async def release_slot(slot_id_str: str, db: AsyncSession) -> bool:
    """Give a held slot back.

    WHAT IT DOES: makes a reserved slot available again, for example when the patient declines the offer,
    picks another time, asks for a person, or ends the conversation. A slot that is not currently reserved
    (for example one already booked) is left untouched.
    """
    await SlotRepository(db).release_slot(uuid.UUID(slot_id_str))
    return True
