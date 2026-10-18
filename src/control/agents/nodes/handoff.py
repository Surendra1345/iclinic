"""Handoff node — escalates call to front desk and notifies staff."""
import logging
import uuid
from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.state import CallState
from src.config.settings import settings
from src.constants.enums import OutcomeType
from src.data.repositories.conversation_repository import ConversationRepository
from src.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


async def handoff_to_front_desk_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    reason = state.get("handoff_reason", "Patient requested representative")
    convo_id = state.get("conversation_id")
    call_sid = state.get("call_sid")

    if convo_id:
        try:
            repo = ConversationRepository(db)
            await repo.close(
                conversation_id=uuid.UUID(convo_id),
                outcome=OutcomeType.HANDED_TO_FRONT_DESK,
                handoff_reason=reason,
            )

            notif_service = NotificationService(db)
            await notif_service.send_frontdesk_alert_email(
                reason=reason,
                call_details={
                    "call_sid": call_sid,
                    "patient_phone": state.get("patient_phone"),
                    "patient_name": state.get("patient_name"),
                    "patient_id": state.get("patient_id"),
                },
            )
        except Exception as e:
            logger.error(f"Error executing handoff DB operations: {e}")

    speech = state.get("latest_agent_speech")
    if not speech or "transfer" not in speech:
        speech = (
            "I want to make sure you get the best assistance with this. "
            "Please hold for just a moment while I transfer you to our front desk team."
        )

    return {
        "handoff_required": True,
        "is_completed": True,
        "latest_agent_speech": speech,
    }
