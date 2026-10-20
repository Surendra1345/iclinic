"""Notification repository — record sent SMS and Email notifications."""
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import NotificationChannel, NotificationStatus
from src.data.models.postgres.notification import Notification


class NotificationRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_notification(
        self,
        *,
        appointment_id: uuid.UUID,
        channel: NotificationChannel,
        recipient: str,
        status: NotificationStatus = NotificationStatus.PENDING,
        provider_response: Optional[Dict[str, Any]] = None,
        error_detail: Optional[str] = None,
        sent_at: Optional[datetime] = None,
    ) -> Notification:
        notification = Notification(
            id=uuid.uuid4(),
            appointment_id=appointment_id,
            channel=channel,
            recipient=recipient,
            status=status,
            provider_response=provider_response,
            error_detail=error_detail,
            sent_at=sent_at or (datetime.utcnow() if status == NotificationStatus.SENT else None),
        )
        self.db.add(notification)
        await self.db.flush()
        await self.db.refresh(notification)
        return notification

    async def mark_sent(
        self,
        notification_id: uuid.UUID,
        provider_response: Optional[Dict[str, Any]] = None,
    ) -> None:
        await self.db.execute(
            update(Notification)
            .where(Notification.id == notification_id)
            .values(
                status=NotificationStatus.SENT,
                sent_at=datetime.utcnow(),
                provider_response=provider_response,
            )
        )
        await self.db.flush()

    async def mark_failed(
        self,
        notification_id: uuid.UUID,
        error_detail: str,
    ) -> None:
        await self.db.execute(
            update(Notification)
            .where(Notification.id == notification_id)
            .values(
                status=NotificationStatus.FAILED,
                error_detail=error_detail,
            )
        )
        await self.db.flush()
