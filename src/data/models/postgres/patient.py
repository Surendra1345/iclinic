from datetime import date
from typing import Optional
from sqlalchemy import BigInteger, Boolean, Date, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.data.models.postgres.base import AuditMixin, Base


class Patient(Base, AuditMixin):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    phone: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)

    __table_args__ = (
        Index("ix_patients_full_name_dob", "full_name", "date_of_birth"),
    )
