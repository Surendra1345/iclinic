"""End call node — concludes call and records final status in database."""
import logging
import uuid
from typing import Any, Dict
# pyrefly: ignore[missing-import]
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.state import CallState
from src.config.settings import settings
from src.constants.enums import OutcomeType
from src.data.repositories.conversation_repository import ConversationRepository

logger = logging.getLogger(__name__)

_FINAL_OUTCOMES = (
    OutcomeType.BOOKED,
    OutcomeType.RESCHEDULED,
    OutcomeType.CANCELLED,
    OutcomeType.HANDED_TO_FRONT_DESK,
    OutcomeType.WRONG_PERSON,
)


async def end_call_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    convo_id = state.get("conversation_id")
    action_confirmed = state.get("booking_confirmed", False)
    intent = state.get("intent")

    if convo_id:
        try:
            repo = ConversationRepository(db)
            existing = await repo.get(uuid.UUID(convo_id))
            if existing is not None and existing.outcome in _FINAL_OUTCOMES:
                # A booking / reschedule / cancellation / hand-off was already recorded; a later
                # "thank you" must not turn it into "abandoned".
                await repo.mark_ended(uuid.UUID(convo_id))
                outcome = None
            elif state.get("wrong_person"):
                # Outbound call reached someone other than the patient: no booking, logged for follow-up.
                outcome = OutcomeType.WRONG_PERSON
            elif action_confirmed and intent == "reschedule":
                outcome = OutcomeType.RESCHEDULED
            elif action_confirmed and intent == "cancel":
                outcome = OutcomeType.CANCELLED
            elif action_confirmed and intent == "book":
                outcome = OutcomeType.BOOKED
            else:
                outcome = OutcomeType.ABANDONED

            if outcome is not None:
                await repo.close(conversation_id=uuid.UUID(convo_id), outcome=outcome)
        except Exception as e:
            logger.error(f"Error closing conversation in DB: {e}")

    prev_speech = state.get("latest_agent_speech")
    if state.get("wrong_person") and prev_speech:
        speech = prev_speech
    elif prev_speech and any(
        k in prev_speech.lower()
        for k in ["always here to help", "booked", "rescheduled", "cancelled", "confirmed"]
    ):
        speech = prev_speech
    else:
        speech = f"You're very welcome! I am always here to help. Thank you for choosing {settings.CLINIC_NAME}. Have a wonderful day!"

    return {
        "is_completed": True,
        "latest_agent_speech": speech,
    }
