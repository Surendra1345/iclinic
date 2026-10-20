from src.data.models.postgres.patient import Patient
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
# pyrefly: ignore[missing-import]
from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text, UUID, text
# pyrefly: ignore[missing-import]
from sqlalchemy.dialects.postgresql import JSONB
# pyrefly: ignore[missing-import]
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants.enums import (
    ChannelType,
    ConfirmationStatusType,
    ConversationState,
    OutcomeType,
)
from src.data.models.postgres.base import AuditMixin, Base


class Conversation(Base, AuditMixin):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    channel: Mapped[ChannelType] = mapped_column(
        Enum(ChannelType, name="channel_type", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        index=True,
    )
    patient_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    identity_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    current_state: Mapped[ConversationState] = mapped_column(
        Enum(ConversationState, name="conversation_state", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        index=True,
    )
    outcome: Mapped[Optional[OutcomeType]] = mapped_column(
        Enum(OutcomeType, name="outcome_type", values_callable=lambda obj: [e.value for e in obj]),
        nullable=True,
    )
    handoff_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confirmation_status: Mapped[ConfirmationStatusType] = mapped_column(
        Enum(ConfirmationStatusType, name="confirmation_status_type", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        index=True,
    )
    collected_details: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False)
    state_history: Mapped[List[Any]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False)
    messages: Mapped[List[Any]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False)
    step_logs: Mapped[List[Any]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False)

    # Relationships
    patient: Mapped[Optional["Patient"]] = relationship("Patient")

    __table_args__ = (
        Index("idx_conversations_channel_state_started", "channel", "current_state", "started_at"),
    )
