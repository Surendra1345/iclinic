"""Identity verification tools for the agent."""
from datetime import date, datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.repositories.patient_repository import PatientRepository


async def lookup_by_phone(phone: str, db: AsyncSession) -> Optional[dict]:
    """Look up active patient by phone number."""
    repo = PatientRepository(db)
    patient = await repo.lookup_by_phone(phone)
    if not patient:
        return None
    return {
        "id": str(patient.id),
        "full_name": patient.full_name,
        "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else None,
        "phone": patient.phone,
        "email": patient.email,
    }


async def verify_patient_by_name_and_dob(
    full_name: str,
    dob_str: str,
    db: AsyncSession,
) -> tuple[bool, Optional[dict]]:
    """
    Verify identity using name and date of birth.
    Accepts ISO (YYYY-MM-DD) or common date formats.
    Uses exact match first, then pg_trgm fuzzy match if exact match fails.
    """
    repo = PatientRepository(db)
    parsed_dob: Optional[date] = None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            parsed_dob = datetime.strptime(dob_str.strip(), fmt).date()
            break
        except ValueError:
            pass

    if not parsed_dob:
        return False, None

    # 1. Exact match
    patient = await repo.lookup_by_name_dob(full_name, parsed_dob)
    if patient:
        return True, {
            "id": str(patient.id),
            "full_name": patient.full_name,
            "date_of_birth": patient.date_of_birth.isoformat(),
            "phone": patient.phone,
        }

    # 2. Fuzzy match with pg_trgm
    patient = await repo.lookup_by_name_dob_fuzzy(full_name, parsed_dob, threshold=0.3)
    if patient:
        return True, {
            "id": str(patient.id),
            "full_name": patient.full_name,
            "date_of_birth": patient.date_of_birth.isoformat(),
            "phone": patient.phone,
        }

    return False, None
