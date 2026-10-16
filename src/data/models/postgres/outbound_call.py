from data.models.postgres.conversation import Conversation
from data.models.postgres.outbound_call_request import OutboundCallRequest
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, UUID, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants.enums import CallStatus
from src.data.models.postgres.base import AuditMixin, Base


class OutboundCall(Base, AuditMixin):
    __tablename__ = "outbound_calls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    call_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbound_call_requests.id", ondelete="RESTRICT"),
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider_call_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, unique=True, index=True)
    number_called: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[CallStatus] = mapped_column(
        Enum(CallStatus, name="call_status", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=CallStatus.DIALING,
        server_default=text("'dialing'"),
    )
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_event_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    last_event_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_event_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_response: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    # Relationships
    call_request: Mapped["OutboundCallRequest"] = relationship("OutboundCallRequest")
    conversation: Mapped["Conversation"] = relationship("Conversation")

    __table_args__ = (
        UniqueConstraint("call_request_id", "attempt_number", name="uq_outbound_calls_request_attempt"),
        Index("idx_outbound_calls_status_retry", "status", "next_retry_at"),
    )
