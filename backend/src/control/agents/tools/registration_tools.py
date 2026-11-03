"""Patient registration actions and the input checks the code enforces itself.

The model extracts a name, date of birth, email and phone from what the patient said; these helpers
only validate those values and write the patient record. They do no free-text interpretation.
"""
import re
from datetime import date, datetime
from typing import Optional
# pyrefly: ignore[missing-import]
from sqlalchemy import select
# pyrefly: ignore[missing-import]
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.patient import Patient
from src.data.repositories.appointment_repository import AppointmentRepository
from src.data.repositories.patient_repository import PatientRepository

_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def valid_email(value: Optional[str]) -> Optional[str]:
    """The address in canonical form when it looks like an email, otherwise None."""
    cleaned = (value or "").strip().strip(".,;").lower()
    return cleaned if _EMAIL.match(cleaned) else None


def normalise_phone(value: Optional[str]) -> Optional[str]:
    """+91XXXXXXXXXX for a 10-digit Indian mobile or a 12-digit number starting 91, else None."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 10 and digits[0] in "6789":
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return f"+{digits}"
    return None


def validate_dob(dob_str: str) -> tuple[bool, Optional[date], str]:
    """
    Validate patient Date of Birth.
    Must be in the past, and age must be between 0 and 120 years.
    Returns (is_valid, parsed_date, error_message).
    """
    cleaned = dob_str.strip()
    # Remove ordinal suffixes like 14th, 1st, 2nd, 3rd
    cleaned = re.sub(r"(\d+)(?:st|nd|rd|th)\b", r"\1", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace(".", "-").replace("/", "-")

    parsed_date: Optional[date] = None

    date_patterns = [
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%m-%d-%Y",
        "%d %B %Y",
        "%B %d %Y",
        "%d %b %Y",
        "%b %d %Y",
    ]

    # Try exact formats first
    for fmt in date_patterns:
        try:
            parsed_date = datetime.strptime(cleaned, fmt).date()
            break
        except ValueError:
            pass

    # If full text had other words, search for date pattern inside string
    if not parsed_date:
        date_regex = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", dob_str)
        if date_regex:
            d1, d2, yr = int(date_regex.group(1)), int(date_regex.group(2)), int(date_regex.group(3))
            try:
                # Assume day-month-year first
                parsed_date = date(yr, d2, d1)
            except ValueError:
                try:
                    parsed_date = date(yr, d1, d2)
                except ValueError:
                    pass

    # Speech recognition often inserts spaces between spoken year digits
    # (for example, "14 December 2 0 0 3"). Normalize only a clear day,
    # month-name, four-digit-year sequence; never infer a missing/ambiguous year.
    if not parsed_date:
        month_names = (
            r"january|february|march|april|may|june|july|august|september|"
            r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
        )
        spoken_month = re.search(
            rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_names})\s+((?:\d\s*){{3}}\d)\b",
            cleaned,
            flags=re.IGNORECASE,
        )
        if spoken_month:
            day_num = int(spoken_month.group(1))
            month_text = spoken_month.group(2)
            year_text = re.sub(r"\s+", "", spoken_month.group(3))
            for fmt in ("%d %B %Y", "%d %b %Y"):
                try:
                    parsed_date = datetime.strptime(
                        f"{day_num} {month_text} {year_text}", fmt
                    ).date()
                    break
                except ValueError:
                    pass

    if not parsed_date:
        return False, None, "Invalid date format. Please provide date of birth as Day-Month-Year (e.g. 14-08-2004)."

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
    """Reuse a matching patient (by phone or name+dob) or create a new patient record."""
    repo = PatientRepository(db)
    cleaned_phone = phone.strip() if phone else ""
    digits = re.sub(r"\D", "", cleaned_phone)
    if len(digits) == 10:
        cleaned_phone = f"+91{digits}"
    elif len(digits) == 12 and digits.startswith("91"):
        cleaned_phone = f"+{digits}"

    patient = None

    # 1. Search for existing profiles registered under this mobile number
    if cleaned_phone and len(digits) >= 10:
        phone_matches = (
            await db.scalars(
                select(Patient)
                .where(
                    Patient.phone == cleaned_phone,
                    Patient.is_active == True,
                )
                .order_by(Patient.created_at.desc())
            )
        ).all()

        for p in phone_matches:
            p_name = p.full_name.strip().lower()
            req_name = full_name.strip().lower()

            # Check if this profile belongs to the same person (name match or DOB match)
            first_name_match = (
                p_name == req_name
                or (p_name.split() and req_name.split() and p_name.split()[0] == req_name.split()[0])
            )
            dob_match = (p.date_of_birth == dob) if (p.date_of_birth and dob) else False

            # If it's the SAME person (e.g. returning patient), reuse their profile
            if first_name_match or dob_match:
                patient = p
                break

    # 2. If no phone match was the same person, check if this Name + DOB exists across clinic
    if not patient:
        existing_patients = (
            await db.scalars(
                select(Patient)
                .where(
                    Patient.full_name.ilike(full_name.strip()),
                    Patient.date_of_birth == dob,
                    Patient.is_active == True,
                )
                .order_by(Patient.created_at.desc())
            )
        ).all()
        if existing_patients:
            appointment_repo = AppointmentRepository(db)
            for existing_patient in existing_patients:
                if await appointment_repo.get_active_for_patient(existing_patient.id):
                    patient = existing_patient
                    break
            else:
                patient = existing_patients[0]

    # If existing patient was found (same person), update missing/updated details
    if patient:
        updated = False
        if cleaned_phone and (not patient.phone or patient.phone == ""):
            patient.phone = cleaned_phone
            updated = True
        if email and (not patient.email or patient.email != email):
            patient.email = email
            updated = True
        if dob and patient.date_of_birth != dob:
            patient.date_of_birth = dob
            updated = True
        if full_name and patient.full_name.strip().lower() != full_name.strip().lower():
            patient.full_name = full_name.strip()
            updated = True
        if updated:
            await db.flush()

        return {
            "id": str(patient.id),
            "full_name": patient.full_name,
            "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else "",
            "phone": patient.phone,
            "email": patient.email,
        }

    # 3. If no match was found:
    # This is a brand NEW patient (either a new individual or a child/family member sharing the phone!)
    # Create an independent profile so the child gets their own medical records and appointment slot.
    patient = await repo.create_patient(
        full_name=full_name.strip(),
        date_of_birth=dob,
        phone=cleaned_phone,
        email=email,
        source="assistant",
    )
    return {
        "id": str(patient.id),
        "full_name": patient.full_name,
        "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else "",
        "phone": patient.phone,
        "email": patient.email,
    }

