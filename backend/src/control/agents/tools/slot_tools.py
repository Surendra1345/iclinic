"""Slot discovery and reservation tools."""
import uuid
from typing import Any, Dict, List, Optional
# pyrefly: ignore[missing-import]
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.repositories.slot_repository import SlotRepository
from src.control.agents.tools.appointment_time import CLINIC_TIMEZONE, format_appointment_time


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


BRANCH_SPECIALTIES = {
    "Anna Nagar": ["General Medicine", "Cardiology", "Dermatology", "Pediatrics"],
    "T. Nagar": ["General Medicine", "Dermatology", "Orthopedics", "Gynecology"],
    "Velachery": ["Cardiology", "Gynecology", "Orthopedics", "Pediatrics"],
    "Tambaram": ["ENT", "General Medicine", "Cardiology", "Dermatology"],
}


def get_specialties_for_branch(branch_name: str) -> List[str]:
    """Returns list of specialties available at a given branch."""
    clean_target = branch_name.lower().replace(".", "").replace(" ", "")
    for b_name, specs in BRANCH_SPECIALTIES.items():
        clean_branch = b_name.lower().replace(".", "").replace(" ", "")
        if clean_branch in clean_target or clean_target in clean_branch:
            return specs
    return []


def get_branches_for_specialty(specialty: str) -> List[str]:
    """Returns list of clinic branches that offer a given specialty."""
    target = specialty.lower().strip()
    res = []
    for b_name, specs in BRANCH_SPECIALTIES.items():
        if any(s.lower() == target or target in s.lower() or s.lower() in target for s in specs):
            res.append(b_name)
    return res


def get_branch_doctors_info(branch_name: str) -> Dict[str, Any]:
    """Returns the doctors and specialties for a specific clinic branch."""
    branch_doctors = {
        "Anna Nagar": [
            {"name": "Dr. Arjun Reddy", "specialty": "General Medicine"},
            {"name": "Dr. Rajesh Kannan", "specialty": "Cardiology"},
            {"name": "Dr. Shalini Sundaram", "specialty": "Dermatology"},
            {"name": "Dr. Meera Krishnan", "specialty": "Pediatrics"},
        ],
        "T. Nagar": [
            {"name": "Dr. Ashwin Balaji", "specialty": "General Medicine"},
            {"name": "Dr. Priya Nair", "specialty": "Dermatology"},
            {"name": "Dr. Karthik Subramanian", "specialty": "Orthopedics"},
            {"name": "Dr. Deepa Venkat", "specialty": "Gynecology"},
        ],
        "Velachery": [
            {"name": "Dr. Sandeep Kumar", "specialty": "Cardiology"},
            {"name": "Dr. Ananya Iyer", "specialty": "Gynecology"},
            {"name": "Dr. Suresh Chandran", "specialty": "Orthopedics"},
            {"name": "Dr. Divya Rangarajan", "specialty": "Pediatrics"},
        ],
        "Tambaram": [
            {"name": "Dr. Vivek Sharma", "specialty": "ENT"},
            {"name": "Dr. Lakshmi Narayanan", "specialty": "General Medicine"},
            {"name": "Dr. Harish Gautham", "specialty": "Cardiology"},
            {"name": "Dr. Nithya Raman", "specialty": "Dermatology"},
        ],
    }
    clean_target = branch_name.lower().replace(".", "").replace(" ", "")
    for b_name, docs in branch_doctors.items():
        clean_branch = b_name.lower().replace(".", "").replace(" ", "")
        if clean_branch in clean_target or clean_target in clean_branch:
            return {"branch": b_name, "doctors": docs}
    return {"branch": "All Branches", "doctors": []}



def parse_date_query_to_range(date_text: str):
    """Parse a requested clinic-local date and return its UTC query boundaries."""
    import re
    from datetime import date, datetime, time, timedelta, timezone
    t = date_text.lower().strip()
    months = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    now_local = datetime.now(CLINIC_TIMEZONE)
    today = now_local.date()
    year = today.year
    month = None
    day = None
    explicit_year = False

    if "tomorrow" in t:
        target = today + timedelta(days=1)
        year, month, day = target.year, target.month, target.day
    elif "today" in t:
        year, month, day = today.year, today.month, today.day

    # ISO date, with optional explicit year in natural language handled below.
    if not month:
        iso_match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
        if iso_match:
            year, month, day = map(int, iso_match.groups())
            explicit_year = True

    # Matches "27 oct", "27th october", and optional year.
    if not month:
        m1 = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s*(?:of\s*)?([a-z]+)(?:\s*,?\s*(\d{4}))?\b", t)
        if m1 and m1.group(2)[:3] in months:
            day = int(m1.group(1))
            month = months[m1.group(2)[:3]]
            if m1.group(3):
                year = int(m1.group(3))
                explicit_year = True

    # Matches "oct 27", "october 27th", and optional year.
    if not month:
        m2 = re.search(r"\b([a-z]+)\s*(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{4}))?\b", t)
        if m2 and m2.group(1)[:3] in months:
            month = months[m2.group(1)[:3]]
            day = int(m2.group(2))
            if m2.group(3):
                year = int(m2.group(3))
                explicit_year = True

    # A bare day is interpreted as the next occurrence in the current month,
    # moving to the next month when that day has already passed.
    if not month:
        m4 = re.search(r"\b(?:on|the)\s+(\d{1,2})(?:st|nd|rd|th)?\b", t)
        if not m4:
            for candidate in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", t):
                before = t[max(0, candidate.start() - 12):candidate.start()].rstrip()
                after = t[candidate.end():].lstrip()
                if re.search(r"(?:\bat|between|from|to|and)\s*$", before):
                    continue
                if re.match(r"(?:am|pm)\b|:|o'?clock\b", after):
                    continue
                m4 = candidate
                break
        if m4:
            requested_day = int(m4.group(1))
            if requested_day < 1 or requested_day > 31:
                day = None
            else:
                year, month = today.year, today.month
                candidate = None
                for _ in range(12):
                    try:
                        candidate = date(year, month, requested_day)
                    except ValueError:
                        candidate = None
                    if candidate is not None and candidate >= today:
                        break
                    next_month = date(year + (month == 12), (month % 12) + 1, 1)
                    year, month = next_month.year, next_month.month
                try:
                    if candidate is None or candidate < today:
                        candidate = date(year, month, requested_day)
                except ValueError:
                    candidate = None
                if candidate is not None:
                    year, month, day = candidate.year, candidate.month, candidate.day

    # Weekday requests resolve to the next future occurrence, not a fixed demo week.
    if not month:
        weekdays = {name: index for index, name in enumerate(
            ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
        )}
        for w_name, weekday in weekdays.items():
            if re.search(rf"\b{w_name}\b", t):
                offset = (weekday - today.weekday()) % 7 or 7
                target = today + timedelta(days=offset)
                year, month, day = target.year, target.month, target.day
                break

    if month and day:
        try:
            requested_date = date(year, month, day)
        except ValueError:
            return None, None
        if not explicit_year and requested_date < today and not any(x in t for x in ("today", "yesterday")):
            try:
                requested_date = date(year + 1, month, day)
            except ValueError:
                return None, None
        local_start = datetime.combine(requested_date, time.min, tzinfo=CLINIC_TIMEZONE)
        local_end = datetime.combine(requested_date + timedelta(days=1), time.min, tzinfo=CLINIC_TIMEZONE)
        return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc) - timedelta(microseconds=1)
    return None, None


def has_date_reference(text: str) -> bool:
    """Detect an attempted date even when the date parser cannot validate it."""
    import re
    lower = (text or "").lower()
    month = r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
    weekday = r"monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    return bool(
        re.search(rf"\b(?:{month})\b", lower)
        or re.search(rf"\b(?:{weekday}|today|tomorrow)\b", lower)
        or re.search(r"\b\d{4}-\d{1,2}-\d{1,2}\b", lower)
        or re.search(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", lower)
        or re.search(r"\b(?:on|the)\s+\d{1,2}(?:st|nd|rd|th)?\b", lower)
    )


def _clock_to_time(clock: Optional[tuple[int, int]]):
    if clock is None:
        return None
    from datetime import time
    return time(clock[0], clock[1])


async def get_slots_by_date_and_criteria(
    db: AsyncSession,
    *,
    date_query: Optional[str] = None,
    specialty: Optional[str] = None,
    location_name: Optional[str] = None,
    doctor_name: Optional[str] = None,
    requested_time: Optional[tuple[int, int]] = None,
    requested_window: Optional[tuple[tuple[int, int], tuple[int, int]]] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Return available future slots filtered by parsed date, specialty, location, and doctor."""
    repo = SlotRepository(db)
    start_dt, end_dt = None, None
    if date_query:
        start_dt, end_dt = parse_date_query_to_range(date_query)
        if start_dt is None or end_dt is None:
            return []

    slots = await repo.get_slots_by_criteria(
        start_time_gte=start_dt,
        start_time_lte=end_dt,
        specialty=specialty,
        location_name=location_name,
        doctor_name=doctor_name,
        clinic_time_gte=_clock_to_time(requested_window[0] if requested_window else requested_time),
        clinic_time_lte=_clock_to_time(requested_window[1] if requested_window else requested_time),
        limit=limit,
    )
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
