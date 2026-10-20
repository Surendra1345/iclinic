from src.data.models.postgres.conversation import Conversation
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, UUID, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants.enums import OutboundCallRequestStatus
from src.data.models.postgres.base import AuditMixin, Base


class OutboundCallRequest(Base, AuditMixin):
    __tablename__ = "outbound_call_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    number_to_call: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[OutboundCallRequestStatus] = mapped_column(
        Enum(
            OutboundCallRequestStatus,
            name="outbound_call_request_status",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=OutboundCallRequestStatus.WAITING,
        server_default=text("'waiting'"),
    )
    status_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    conversation: Mapped["Conversation"] = relationship("Conversation")

    __table_args__ = (
        Index(
            "one_active_request_per_number",
            "number_to_call",
            unique=True,
            postgresql_where=text("status IN ('waiting', 'processing', 'started')"),
        ),
        Index("idx_outbound_requests_status_created", "status", "created_at"),
        Index("idx_outbound_requests_number_status", "number_to_call", "status"),
    )
