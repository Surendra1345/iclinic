from datetime import datetime
from typing import Any, Dict, Optional
from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants.enums import CallStatus
from src.data.models.postgres.base import AuditMixin, Base


class OutboundCall(Base, AuditMixin):
    __tablename__ = "outbound_calls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    call_request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("outbound_call_requests.id"),
        nullable=False,
    )
    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("conversations.id"),
        nullable=False,
    )
    provider_call_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    number_called: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[CallStatus] = mapped_column(
        Enum(CallStatus, name="call_status"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_event_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_event_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_event_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_response: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    # Relationships
    call_request: Mapped["OutboundCallRequest"] = relationship("OutboundCallRequest")
    conversation: Mapped["Conversation"] = relationship("Conversation")
