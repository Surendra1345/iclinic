"""Persistence helpers for outbound call requests and Twilio call attempts."""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config.settings import settings
from src.constants.enums import CallStatus, OutboundCallRequestStatus
from src.data.models.postgres.outbound_call import OutboundCall
from src.data.models.postgres.outbound_call_request import OutboundCallRequest


class OutboundCallRepository:
    """Keeps Twilio identifiers and call lifecycle state durable in PostgreSQL."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_active_request(self, phone: str) -> Optional[OutboundCallRequest]:
        now = datetime.now(timezone.utc)
        await self.db.execute(
            update(OutboundCallRequest)
            .where(
                OutboundCallRequest.number_to_call == phone,
                OutboundCallRequest.status.in_(
                    (
                        OutboundCallRequestStatus.WAITING,
                        OutboundCallRequestStatus.PROCESSING,
                        OutboundCallRequestStatus.STARTED,
                    )
                ),
                OutboundCallRequest.expires_at <= now,
            )
            .values(
                status=OutboundCallRequestStatus.EXPIRED,
                status_reason="Outbound request expired before completion.",
                completed_at=now,
            )
        )
        result = await self.db.scalars(
            select(OutboundCallRequest)
            .where(
                OutboundCallRequest.number_to_call == phone,
                OutboundCallRequest.status.in_(
                    (
                        OutboundCallRequestStatus.WAITING,
                        OutboundCallRequestStatus.PROCESSING,
                        OutboundCallRequestStatus.STARTED,
                    )
                ),
            )
            .limit(1)
        )
        return result.first()

    async def create_request(
        self,
        *,
        conversation_id: uuid.UUID,
        phone: str,
        expires_at: datetime,
    ) -> OutboundCallRequest:
        request = OutboundCallRequest(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            number_to_call=phone,
            status=OutboundCallRequestStatus.PROCESSING,
            expires_at=expires_at,
            claimed_at=datetime.now(timezone.utc),
        )
        self.db.add(request)
        await self.db.flush()
        return request

    async def create_call(
        self,
        *,
        request_id: uuid.UUID,
        conversation_id: uuid.UUID,
        provider_call_id: str,
        phone: str,
        attempt_number: int = 1,
    ) -> OutboundCall:
        call = OutboundCall(
            id=uuid.uuid4(),
            call_request_id=request_id,
            conversation_id=conversation_id,
            provider_call_id=provider_call_id,
            number_called=phone,
            status=CallStatus.DIALING,
            attempt_number=attempt_number,
        )
        self.db.add(call)
        await self.db.flush()
        return call

    async def get_by_provider_call_id(self, call_sid: str) -> Optional[OutboundCall]:
        result = await self.db.scalars(
            select(OutboundCall)
            .options(
                selectinload(OutboundCall.call_request),
                selectinload(OutboundCall.conversation),
            )
            .where(OutboundCall.provider_call_id == call_sid)
            .limit(1)
        )
        return result.first()

    async def get_by_request_id(self, request_id: uuid.UUID) -> Optional[OutboundCall]:
        result = await self.db.scalars(
            select(OutboundCall)
            .where(OutboundCall.call_request_id == request_id)
            .order_by(OutboundCall.attempt_number.desc())
            .limit(1)
        )
        return result.first()

    async def update_status(
        self,
        *,
        call_sid: str,
        call_status: CallStatus,
        event_type: str,
        event_id: Optional[str] = None,
        event_timestamp: Optional[datetime] = None,
        duration_seconds: Optional[int] = None,
        provider_response: Optional[dict] = None,
        retry_delay_seconds: Optional[int] = None,
    ) -> Optional[OutboundCall]:
        call = await self.get_by_provider_call_id(call_sid)
        if not call:
            return None

        now = datetime.now(timezone.utc)
        values = {
            "status": call_status,
            "last_event_id": event_id,
            "last_event_type": event_type,
            "last_event_timestamp": event_timestamp or now,
        }
        if duration_seconds is not None:
            values["provider_response"] = {
                **(call.provider_response or {}),
                "duration_seconds": duration_seconds,
            }
        if provider_response:
            values["provider_response"] = {
                **(call.provider_response or {}),
                **provider_response,
            }
        if call_status == CallStatus.ANSWERED and call.started_at is None:
            values["started_at"] = now
        if call_status in {
            CallStatus.NO_ANSWER,
            CallStatus.BUSY,
            CallStatus.FAILED,
        } or event_type in {"completed", "canceled"}:
            values["ended_at"] = now

        retry_at = None
        retryable_miss = call_status in {CallStatus.NO_ANSWER, CallStatus.BUSY}
        request_is_open = call.call_request.expires_at > now
        if retryable_miss and call.attempt_number < max(1, settings.OUTBOUND_CALL_MAX_ATTEMPTS) and request_is_open:
            delay = (
                max(0, retry_delay_seconds)
                if retry_delay_seconds is not None
                else max(1, settings.OUTBOUND_CALL_RETRY_DELAY_MINUTES) * 60
            )
            retry_at = now + timedelta(seconds=delay)
        values["next_retry_at"] = retry_at

        await self.db.execute(
            update(OutboundCall)
            .where(OutboundCall.id == call.id)
            .values(**values)
        )

        request_status = {
            CallStatus.DIALING: OutboundCallRequestStatus.PROCESSING,
            CallStatus.ANSWERED: OutboundCallRequestStatus.STARTED,
            CallStatus.NO_ANSWER: OutboundCallRequestStatus.PROCESSING if retry_at else OutboundCallRequestStatus.COMPLETED,
            CallStatus.BUSY: OutboundCallRequestStatus.PROCESSING if retry_at else OutboundCallRequestStatus.COMPLETED,
            CallStatus.FAILED: OutboundCallRequestStatus.FAILED,
        }[call_status]
        if event_type in {"completed", "canceled"}:
            request_status = (
                OutboundCallRequestStatus.COMPLETED
                if event_type == "completed"
                else OutboundCallRequestStatus.CANCELLED
            )
        request_values = {"status": request_status}
        if call_status in {CallStatus.NO_ANSWER, CallStatus.BUSY}:
            request_values["status_reason"] = event_type
        if request_status == OutboundCallRequestStatus.STARTED:
            request_values["started_at"] = now
        elif request_status == OutboundCallRequestStatus.CANCELLED:
            request_values["cancelled_at"] = now
        elif request_status in {
            OutboundCallRequestStatus.COMPLETED,
            OutboundCallRequestStatus.FAILED,
        }:
            request_values["completed_at"] = now
            if call_status in {CallStatus.NO_ANSWER, CallStatus.BUSY}:
                request_values["status_reason"] = event_type

        await self.db.execute(
            update(OutboundCallRequest)
            .where(OutboundCallRequest.id == call.call_request_id)
            .values(**request_values)
        )
        call.next_retry_at = retry_at
        await self.db.flush()
        return call
