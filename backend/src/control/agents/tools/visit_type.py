"""Choosing the appointment type (visit reason) for a booking made in the web chat.

Active types come from the database, so the question, the matching and the confirmation all
follow whatever types the clinic has configured. A reply that names no type is kept as the
visit reason and booked under the default type.
"""
import re
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.appointment_type import AppointmentType

DEFAULT_VISIT_TYPE = "General Consultation"

# Words every type shares, so they say nothing about which type was meant.
_GENERIC_WORDS = {"consultation", "visit", "appointment", "check", "health"}
_MIN_PREFIX = 5


async def active_visit_names(db: AsyncSession) -> List[str]:
    rows = await db.scalars(
        select(AppointmentType.name).where(AppointmentType.is_active.is_(True)).order_by(AppointmentType.name)
    )
    return list(rows.all())


def visit_type_question(names: List[str]) -> str:
    listed = ", ".join(names[:-1]) + f" or {names[-1]}" if len(names) > 1 else "".join(names)
    return (
        f"Before I confirm, what is the reason for your visit? I can book it as a {listed}. "
        f"If you are not sure, just tell me the reason and I will book a {DEFAULT_VISIT_TYPE}."
    )


def _words(text: str) -> List[str]:
    return re.findall(r"[a-z]+", (text or "").lower())


def resolve_visit_type(speech: str, names: List[str]) -> Optional[str]:
    """The configured type the patient named, or None when they only gave a reason."""
    lower = " ".join(_words(speech))
    if not lower:
        return None
    for name in names:
        if " ".join(_words(name)) in lower:
            return name
    spoken = _words(speech)
    for name in names:
        distinct = [w for w in _words(name) if w not in _GENERIC_WORDS and len(w) >= _MIN_PREFIX]
        for word in distinct:
            stem = word[: max(_MIN_PREFIX, len(word) - 2)]
            if any(token.startswith(stem) or word.startswith(token) and len(token) >= _MIN_PREFIX for token in spoken):
                return name
    if re.search(r"\bcheck[\s-]?ups?\b|\bhealth\s+check\b|\bscreening\b", speech or "", re.IGNORECASE):
        for name in names:
            if {"preventive", "check"} & set(_words(name)):
                return name
    return None
