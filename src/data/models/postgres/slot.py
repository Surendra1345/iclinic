from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.postgres.base import AuditMixin, Base


class Slot(Base, AuditMixin):
    __tablename__ = "slots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("providers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_ref: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Relationships
    provider: Mapped["Provider"] = relationship("Provider")

    __table_args__ = (
        UniqueConstraint("provider_id", "start_time", name="uq_slots_provider_start_time"),
    )
