"""Appointment types (visit reasons) the clinic offers. Read from the database, never hardcoded."""
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.appointment_type import AppointmentType

DEFAULT_VISIT_TYPE = "General Consultation"
FOLLOWUP_VISIT_TYPE = "Follow-up Consultation"


async def active_visit_names(db: AsyncSession) -> List[str]:
    rows = await db.scalars(
        select(AppointmentType.name).where(AppointmentType.is_active.is_(True)).order_by(AppointmentType.name)
    )
    return list(rows.all())


def canonical_visit_type(name: str | None, names: List[str]) -> str | None:
    """The configured type whose name equals `name` ignoring case, or None. Validates model output."""
    wanted = (name or "").strip().casefold()
    return next((n for n in names if n.casefold() == wanted), None) if wanted else None
