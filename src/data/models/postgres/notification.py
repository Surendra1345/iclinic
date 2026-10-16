from data.models.postgres.appointment import Appointment
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UUID, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants.enums import NotificationChannel, NotificationStatus
from src.data.models.postgres.base import AuditMixin, Base


class Notification(Base, AuditMixin):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("appointments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notification_channel", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    recipient: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, name="notification_status", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=NotificationStatus.PENDING,
        server_default=text("'pending'"),
        index=True,
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider_response: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    flagged_for_staff: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    appointment: Mapped["Appointment"] = relationship("Appointment")

    __table_args__ = (
        UniqueConstraint("appointment_id", "channel", "recipient", name="uq_notifications_app_channel_recip"),
    )
