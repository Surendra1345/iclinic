from typing import Optional
from sqlalchemy import BigInteger, Enum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants.enums import AppointmentStatus, ChannelType
from src.data.models.postgres.base import AuditMixin, Base


class Appointment(Base, AuditMixin):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    patient_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("patients.id"),
        nullable=False,
    )
    slot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("slots.id"),
        unique=True,
        nullable=False,
    )
    appointment_type_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("appointment_types.id"),
        nullable=False,
    )
    channel: Mapped[ChannelType] = mapped_column(
        Enum(ChannelType, name="channel_type", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus, name="appointment_status", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("conversations.id"),
        unique=True,
        nullable=False,
    )

    # Relationships
    patient: Mapped["Patient"] = relationship("Patient")
    slot: Mapped["Slot"] = relationship("Slot")
    appointment_type: Mapped["AppointmentType"] = relationship("AppointmentType")
    conversation: Mapped["Conversation"] = relationship("Conversation")
