from src.data.models.postgres.conversation import Conversation
from src.data.models.postgres.appointment_type import AppointmentType
from src.data.models.postgres.slot import Slot
from src.data.models.postgres.patient import Patient
import uuid
from typing import Optional
from sqlalchemy import Enum, ForeignKey, Index, Text, UUID, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants.enums import AppointmentStatus, ChannelType
from src.data.models.postgres.base import AuditMixin, Base


class Appointment(Base, AuditMixin):
    __tablename__ = "appointments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    slot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("slots.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    appointment_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("appointment_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    channel: Mapped[ChannelType] = mapped_column(
        Enum(ChannelType, name="channel_type", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        index=True,
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus, name="appointment_status", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=AppointmentStatus.BOOKED,
        server_default=text("'booked'"),
        index=True,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )

    # Relationships
    patient: Mapped["Patient"] = relationship("Patient")
    slot: Mapped["Slot"] = relationship("Slot")
    appointment_type: Mapped["AppointmentType"] = relationship("AppointmentType")
    conversation: Mapped["Conversation"] = relationship("Conversation")

    __table_args__ = (
        Index(
            "uq_active_appointment_slot",
            "slot_id",
            unique=True,
            postgresql_where=text("status = 'booked'"),
        ),
        Index(
            "uq_one_active_per_patient",
            "patient_id",
            unique=True,
            postgresql_where=text("status = 'booked'"),
        ),
        Index("idx_appointments_channel_status_created", "channel", "status", "created_at"),
    )
