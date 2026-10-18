"""End call node — concludes call and records final status in database."""
import logging
import uuid
from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.state import CallState
from src.config.settings import settings
from src.constants.enums import OutcomeType
from src.data.repositories.conversation_repository import ConversationRepository

logger = logging.getLogger(__name__)


async def end_call_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    convo_id = state.get("conversation_id")
    booking_confirmed = state.get("booking_confirmed", False)
    intent = state.get("intent")

    if convo_id:
        try:
            repo = ConversationRepository(db)
            if booking_confirmed:
                outcome = OutcomeType.BOOKED
            else:
                outcome = OutcomeType.ABANDONED

            await repo.close(conversation_id=uuid.UUID(convo_id), outcome=outcome)
        except Exception as e:
            logger.error(f"Error closing conversation in DB: {e}")

    speech = f"Thank you for calling {settings.CLINIC_NAME}. Have a wonderful day, goodbye!"

    return {
        "is_completed": True,
        "latest_agent_speech": speech,
    }
