"""Background scheduler — periodically frees expired slot reservations."""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.config.settings import settings
from src.constants.enums import CallStatus, ConversationState, OutcomeType, OutboundCallRequestStatus
from src.data.clients.postgres import AsyncSessionLocal
from src.data.models.postgres.conversation import Conversation
from src.data.models.postgres.outbound_call import OutboundCall
from src.data.models.postgres.outbound_call_request import OutboundCallRequest
from src.data.repositories.outbound_call_repository import OutboundCallRepository
from src.data.repositories.slot_repository import SlotRepository
from src.observability.metrics import (
    scheduler_last_run_timestamp,
    scheduler_released_slots_total,
)

logger = logging.getLogger(__name__)


async def _reconcile_one_stale_outbound_call() -> bool:
    """Recover terminal Twilio statuses when a status callback was missed."""
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(minutes=max(1, settings.OUTBOUND_CALL_STATUS_RECONCILE_MINUTES))
    async with AsyncSessionLocal() as session:
        stmt = (
            select(OutboundCall)
            .join(OutboundCallRequest, OutboundCall.call_request_id == OutboundCallRequest.id)
            .options(selectinload(OutboundCall.call_request))
            .where(
                OutboundCall.status == CallStatus.DIALING,
                OutboundCall.created_at <= stale_before,
                OutboundCall.provider_call_id.is_not(None),
                OutboundCallRequest.status.in_((OutboundCallRequestStatus.PROCESSING, OutboundCallRequestStatus.STARTED)),
                OutboundCall.created_at >= now - timedelta(minutes=30),
            )
            .order_by(OutboundCall.created_at)
            .limit(1)
            .with_for_update(skip_locked=True, of=OutboundCall)
        )
        call = (await session.scalars(stmt)).first()
        if not call:
            return False

        try:
            from src.api.rest.routes.voice import twilio_service

            details = await asyncio.to_thread(twilio_service.get_call_details, call.provider_call_id)
        except Exception:
            logger.exception("Outbound status reconciliation failed: call_id=%s", call.id)
            return False

        provider_status = details.get("status")
        status_map = {
            "no-answer": CallStatus.NO_ANSWER,
            "busy": CallStatus.BUSY,
            "failed": CallStatus.FAILED,
            "canceled": CallStatus.FAILED,
        }
        call_status = status_map.get(provider_status)
        if not call_status:
            return False

        provider_end_time = details.get("end_time") or now
        if provider_end_time.tzinfo is None:
            provider_end_time = provider_end_time.replace(tzinfo=timezone.utc)
        due_at = provider_end_time + timedelta(minutes=max(1, settings.OUTBOUND_CALL_RETRY_DELAY_MINUTES))
        retry_delay_seconds = max(0, int((due_at - now).total_seconds()))
        if (
            call_status in {CallStatus.NO_ANSWER, CallStatus.BUSY}
            and call.attempt_number < max(1, settings.OUTBOUND_CALL_MAX_ATTEMPTS)
            and call.call_request.expires_at <= now
        ):
            # Recover a recently missed callback even if its original request
            # timeout elapsed while the callback/retry worker was unavailable.
            call.call_request.expires_at = now + timedelta(
                minutes=max(1, settings.OUTBOUND_CALL_RETRY_DELAY_MINUTES) + 5
            )
            await session.flush()
        repo = OutboundCallRepository(session)
        recovered_call = await repo.update_status(
            call_sid=call.provider_call_id,
            call_status=call_status,
            event_type=provider_status,
            event_timestamp=provider_end_time,
            provider_response={"call_status": provider_status, "reconciled_from_provider": True},
            retry_delay_seconds=retry_delay_seconds,
        )
        conversation = await session.get(Conversation, call.conversation_id)
        if recovered_call and conversation and conversation.ended_at is None:
            will_retry = bool(recovered_call.next_retry_at)
            next_state = ConversationState.RETRY_SCHEDULED if will_retry else {
                "no-answer": ConversationState.NO_ANSWER,
                "busy": ConversationState.BUSY,
                "failed": ConversationState.FAILED,
                "canceled": ConversationState.ABANDONED,
            }[provider_status]
            history = list(conversation.state_history or [])
            history.append({"state": next_state.value, "at": now.isoformat()})
            conversation.current_state = next_state
            conversation.state_history = history
            if not will_retry:
                conversation.ended_at = now
                conversation.outcome = (
                    OutcomeType.NOT_REACHED
                    if provider_status in {"no-answer", "busy"}
                    else OutcomeType.FAILED
                )
        await session.commit()
        logger.warning(
            "Recovered outbound terminal status from Twilio: call_id=%s provider_status=%s retry_at=%s",
            call.id, provider_status, recovered_call.next_retry_at if recovered_call else None,
        )
        return True


async def _process_one_outbound_retry() -> bool:
    """Start one due retry, keeping retries bounded and serialized per attempt."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        stmt = (
            select(OutboundCall)
            .join(OutboundCallRequest, OutboundCall.call_request_id == OutboundCallRequest.id)
            .options(selectinload(OutboundCall.call_request))
            .where(
                OutboundCall.next_retry_at <= now,
                OutboundCall.status.in_((CallStatus.NO_ANSWER, CallStatus.BUSY)),
                OutboundCall.attempt_number < max(1, settings.OUTBOUND_CALL_MAX_ATTEMPTS),
                OutboundCallRequest.status == OutboundCallRequestStatus.PROCESSING,
                OutboundCallRequest.expires_at > now,
            )
            .order_by(OutboundCall.next_retry_at)
            .limit(1)
            .with_for_update(skip_locked=True, of=OutboundCall)
        )
        call = (await session.scalars(stmt)).first()
        if not call:
            return False

        request = call.call_request
        conversation = await session.get(Conversation, call.conversation_id)
        if not conversation:
            request.status = OutboundCallRequestStatus.FAILED
            request.status_reason = "Conversation for retry was not found."
            request.completed_at = now
            call.next_retry_at = None
            await session.commit()
            return True

        try:
            # Import lazily to keep API route initialization separate from the scheduler.
            from src.api.rest.routes.voice import _get_clean_domain, twilio_service

            domain = _get_clean_domain()
            call_sid = await asyncio.to_thread(
                twilio_service.initiate_outbound_call,
                to_phone=request.number_to_call,
                webhook_url=f"https://{domain}/twilio/voice",
                status_callback_url=f"https://{domain}/twilio/call-status",
            )
            attempt_number = call.attempt_number + 1
            retry_repo = OutboundCallRepository(session)
            await retry_repo.create_call(
                request_id=request.id,
                conversation_id=conversation.id,
                provider_call_id=call_sid,
                phone=request.number_to_call,
                attempt_number=attempt_number,
            )
            call.next_retry_at = None
            details = dict(conversation.collected_details or {})
            details.update({"call_sid": call_sid, "patient_phone": request.number_to_call})
            conversation.collected_details = details
            history = list(conversation.state_history or [])
            history.append({"state": ConversationState.STARTED.value, "at": datetime.now(timezone.utc).isoformat()})
            conversation.current_state = ConversationState.STARTED
            conversation.state_history = history
            await session.commit()
            logger.info(
                "Outbound call retry started: request_id=%s attempt=%s max_attempts=%s",
                request.id, attempt_number, settings.OUTBOUND_CALL_MAX_ATTEMPTS,
            )
        except Exception:
            logger.exception("Outbound call retry failed: request_id=%s", request.id)
            request.status = OutboundCallRequestStatus.FAILED
            request.status_reason = "Automatic retry failed to start."
            request.completed_at = datetime.now(timezone.utc)
            call.next_retry_at = None
            conversation.current_state = ConversationState.FAILED
            conversation.ended_at = datetime.now(timezone.utc)
            conversation.outcome = OutcomeType.FAILED
            await session.commit()
        return True

_cleanup_task: Optional[asyncio.Task] = None
_running: bool = False


def is_scheduler_running() -> bool:
    return _running and _cleanup_task is not None and not _cleanup_task.done()


async def _reservation_cleanup_loop(interval_seconds: int = 60):
    global _running
    while _running:
        try:
            scheduler_last_run_timestamp.set(time.time())
            async with AsyncSessionLocal() as session:
                repo = SlotRepository(session)
                released_count = await repo.cleanup_expired_reservations()
                await session.commit()
                if released_count > 0:
                    logger.info(f"Released {released_count} expired slot reservations.")
                    scheduler_released_slots_total.inc(released_count)
                else:
                    logger.debug("Scheduler cleanup completed; no expired reservations found.")
            await _reconcile_one_stale_outbound_call()
            await _process_one_outbound_retry()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Error during slot reservation cleanup: %s", e)

        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            break


async def start_scheduler():
    """Start background scheduler tasks on app startup."""
    global _cleanup_task, _running
    if not _running:
        _running = True
        _cleanup_task = asyncio.create_task(_reservation_cleanup_loop())
        logger.info("Slot reservation cleanup scheduler started interval_seconds=60")


async def stop_scheduler():
    """Cancel background scheduler tasks on app shutdown."""
    global _cleanup_task, _running
    _running = False
    if _cleanup_task:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
        _cleanup_task = None
        logger.info("Slot reservation cleanup scheduler stopped.")
