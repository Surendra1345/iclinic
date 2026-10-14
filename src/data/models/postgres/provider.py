from typing import Optional
from sqlalchemy import BigInteger, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.postgres.base import AuditMixin, Base


class Provider(Base, AuditMixin):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    specialty: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    location_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("locations.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)

    # Relationships
    location: Mapped["Location"] = relationship("Location")
