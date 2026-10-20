"""Start conversation node — initialize state and database record."""
import uuid
from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.state import CallState
from src.constants.enums import ChannelType, ConversationState
from src.data.repositories.conversation_repository import ConversationRepository


async def start_conversation_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    """Initialize DB conversation and prime state."""
    repo = ConversationRepository(db)
    channel_str = state.get("channel", "outbound_call")
    channel_enum = ChannelType(channel_str) if channel_str in [e.value for e in ChannelType] else ChannelType.OUTBOUND_CALL

    convo_id = state.get("conversation_id")
    if not convo_id:
        convo = await repo.create(
            channel=channel_enum,
            call_sid=state.get("call_sid"),
        )
        convo_id = str(convo.id)
        return {
            "conversation_id": convo_id,
            "silence_count": 0,
            "verify_attempts": 0,
            "is_verified": state.get("is_verified", False),
            "is_new_patient": state.get("is_new_patient", False),
            "booking_confirmed": False,
            "handoff_required": False,
            "is_completed": False,
        }

    # If conversation is already active, preserve all existing state flags
    return {
        "conversation_id": convo_id,
    }

