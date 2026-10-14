import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, UUID, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.clients.postgres import Base


class AppointmentReschedule(Base):
    __tablename__ = "appointment_reschedules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    old_appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("appointments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    new_appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("appointments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    # Relationships
    old_appointment: Mapped["Appointment"] = relationship("Appointment", foreign_keys=[old_appointment_id])
    new_appointment: Mapped["Appointment"] = relationship("Appointment", foreign_keys=[new_appointment_id])
    conversation: Mapped["Conversation"] = relationship("Conversation")

    __table_args__ = (
        UniqueConstraint("old_appointment_id", "new_appointment_id", name="uq_reschedules_old_new"),
        CheckConstraint("old_appointment_id <> new_appointment_id", name="check_reschedule_different_appointments"),
    )
