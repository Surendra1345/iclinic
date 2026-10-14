from datetime import datetime
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.data.clients.postgres import Base


class AuditMixin:
    """Provides common audit tracking fields across all tables."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String(100), server_default="system", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(100), server_default="system", nullable=False)


__all__ = ["Base", "AuditMixin"]
