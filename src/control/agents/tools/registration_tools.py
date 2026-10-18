"""Registration tools — validate DOB and register new patients."""
from datetime import date, datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.repositories.patient_repository import PatientRepository


def validate_dob(dob_str: str) -> tuple[bool, Optional[date], str]:
    """
    Validate patient Date of Birth.
    Must be in the past, and age must be between 0 and 120 years.
    Returns (is_valid, parsed_date, error_message).
    """
    cleaned = dob_str.strip()
    parsed_date: Optional[date] = None

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%B %d, %Y", "%d %B %Y"):
        try:
            parsed_date = datetime.strptime(cleaned, fmt).date()
            break
        except ValueError:
            pass

    if not parsed_date:
        return False, None, "Invalid date format. Please provide date of birth as Day Month Year."

    today = date.today()
    if parsed_date > today:
        return False, None, "Date of birth cannot be in the future."

    age = today.year - parsed_date.year - ((today.month, today.day) < (parsed_date.month, parsed_date.day))
    if age > 120:
        return False, None, "Date of birth is outside valid range (must be less than 120 years ago)."
    if age < 0:
        return False, None, "Date of birth cannot be in the future."

    return True, parsed_date, ""


async def register_new_patient(
    full_name: str,
    dob: date,
    phone: str,
    email: Optional[str],
    db: AsyncSession,
) -> dict:
    """Create a new patient record in the database."""
    repo = PatientRepository(db)
    patient = await repo.create_patient(
        full_name=full_name,
        date_of_birth=dob,
        phone=phone,
        email=email,
        source="assistant",
    )
    return {
        "id": str(patient.id),
        "full_name": patient.full_name,
        "date_of_birth": patient.date_of_birth.isoformat(),
        "phone": patient.phone,
    }
