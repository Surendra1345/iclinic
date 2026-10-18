from src.data.models.postgres.provider import Provider
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, String, UUID, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants.enums import SlotStatus
from src.data.models.postgres.base import AuditMixin, Base


class Slot(Base, AuditMixin):
    __tablename__ = "slots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("providers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[SlotStatus] = mapped_column(
        Enum(SlotStatus, name="slot_status", values_callable=lambda obj: [e.value for e in obj]),
        default=SlotStatus.AVAILABLE,
        server_default=text("'available'"),
        nullable=False,
        index=True,
    )
    reserved_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    source_ref: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Relationships
    provider: Mapped["Provider"] = relationship("Provider")

    __table_args__ = (
        UniqueConstraint("provider_id", "start_time", name="uq_slots_provider_start_time"),
        CheckConstraint("end_time > start_time", name="slots_end_after_start"),
        Index("idx_slots_start_provider", "start_time", "provider_id"),
    )
