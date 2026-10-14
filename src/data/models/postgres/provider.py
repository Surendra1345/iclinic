import uuid
from typing import Optional
from sqlalchemy import Boolean, ForeignKey, Index, String, UUID, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.postgres.base import AuditMixin, Base


class Provider(Base, AuditMixin):
    __tablename__ = "providers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    specialty: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("locations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)

    # Relationships
    location: Mapped["Location"] = relationship("Location")
