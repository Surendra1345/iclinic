from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
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

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    channel: Mapped[ChannelType] = mapped_column(
        Enum(ChannelType, name="channel_type", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    patient_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("patients.id"),
        nullable=True,
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    current_state: Mapped[ConversationState] = mapped_column(
        Enum(ConversationState, name="conversation_state", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    outcome: Mapped[Optional[OutcomeType]] = mapped_column(
        Enum(OutcomeType, name="outcome_type", values_callable=lambda obj: [e.value for e in obj]),
        nullable=True,
    )
    handoff_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confirmation_status: Mapped[ConfirmationStatusType] = mapped_column(
        Enum(ConfirmationStatusType, name="confirmation_status_type", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    collected_details: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    state_history: Mapped[List[Any]] = mapped_column(JSONB, default=list, nullable=False)
    messages: Mapped[List[Any]] = mapped_column(JSONB, default=list, nullable=False)
    step_logs: Mapped[List[Any]] = mapped_column(JSONB, default=list, nullable=False)

    # Relationships
    patient: Mapped[Optional["Patient"]] = relationship("Patient")
