import uuid
from datetime import date
from typing import Optional
from sqlalchemy import Boolean, Date, Enum, Index, String, UUID, text
from sqlalchemy.orm import Mapped, mapped_column

from src.constants.enums import PatientSource
from src.data.models.postgres.base import AuditMixin, Base


class Patient(Base, AuditMixin):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    phone: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source: Mapped[PatientSource] = mapped_column(
        Enum(PatientSource, name="patient_source", values_callable=lambda obj: [e.value for e in obj]),
        default=PatientSource.ASSISTANT,
        server_default=text("'assistant'"),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)

    __table_args__ = (
        Index("ix_patients_full_name_dob", "full_name", "date_of_birth"),
    )
