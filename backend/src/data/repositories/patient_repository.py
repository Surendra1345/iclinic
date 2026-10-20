"""Patient repository — DB read/write operations for the patients table."""
import uuid
from datetime import date
from typing import Optional

from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.patient import Patient


class PatientRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def lookup_by_phone(self, phone: str) -> Optional[Patient]:
        """Exact phone match. Returns None if not found."""
        result = await self.db.scalars(
            select(Patient).where(Patient.phone == phone, Patient.is_active == True)
        )
        return result.one_or_none()

    async def get_by_phone(self, phone: str) -> Optional[Patient]:
        """Alias for lookup_by_phone."""
        return await self.lookup_by_phone(phone)

    async def lookup_by_name_dob(
        self, full_name: str, dob: date
    ) -> Optional[Patient]:
        """Exact (case-insensitive) name + DOB match."""
        result = await self.db.scalars(
            select(Patient).where(
                func.lower(Patient.full_name) == full_name.lower().strip(),
                Patient.date_of_birth == dob,
                Patient.is_active == True,
            )
        )
        return result.one_or_none()

    async def lookup_by_name_dob_fuzzy(
        self, full_name: str, dob: date, threshold: float = 0.3
    ) -> Optional[Patient]:
        """
        Fuzzy name match using pg_trgm similarity.
        Returns best match above threshold, or None.
        Requires: CREATE EXTENSION IF NOT EXISTS pg_trgm;
        """
        result = await self.db.execute(
            text(
                """
                SELECT *, similarity(full_name, :name) AS score
                FROM patients
                WHERE date_of_birth = :dob
                  AND is_active = true
                  AND similarity(full_name, :name) > :threshold
                ORDER BY score DESC
                LIMIT 1
                """
            ),
            {"name": full_name.strip(), "dob": dob, "threshold": threshold},
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        # Re-fetch as ORM object for consistency
        return await self.db.get(Patient, row["id"])

    async def get_fuzzy_score(self, full_name: str, patient_id: uuid.UUID) -> float:
        """Get similarity score between a given name and a patient's stored name."""
        result = await self.db.execute(
            text(
                "SELECT similarity(full_name, :name) AS score FROM patients WHERE id = :id"
            ),
            {"name": full_name.strip(), "id": patient_id},
        )
        row = result.one_or_none()
        return float(row.score) if row else 0.0

    async def create_patient(
        self,
        *,
        full_name: str,
        date_of_birth: date,
        phone: str,
        email: Optional[str] = None,
        source: str = "assistant",
    ) -> Patient:
        """Insert a new patient record and return it."""
        patient = Patient(
            id=uuid.uuid4(),
            full_name=full_name.strip(),
            date_of_birth=date_of_birth,
            phone=phone,
            email=email,
            source=source,
            is_active=True,
        )
        self.db.add(patient)
        await self.db.flush()
        await self.db.refresh(patient)
        return patient
