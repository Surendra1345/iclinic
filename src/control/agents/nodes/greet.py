"""Greet node — speaks opening greeting."""
from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.state import CallState
from src.config.settings import settings
from src.constants.enums import ConversationState
from src.data.repositories.conversation_repository import ConversationRepository


async def greet_patient_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    # Only greet on call connection before caller speaks
    if state.get("latest_user_speech") or state.get("is_verified") or state.get("messages"):
        return {}

    channel = state.get("channel", "outbound_call")

    patient_name = state.get("patient_name")

    if channel == "outbound_call":
        greeting_text = (
            f"Hello! Thank you for answering. This is {settings.AGENT_NAME} calling from {settings.CLINIC_NAME}. "
            f"For your medical privacy and security, could you please confirm your full name and date of birth?"
        )
    else:
        greeting_text = (
            f"Hello! Thank you for calling {settings.CLINIC_NAME}. "
            f"My name is {settings.AGENT_NAME}. For your medical privacy, could you please confirm your full name and date of birth?"
        )

    convo_id = state.get("conversation_id")
    if convo_id:
        import uuid
        repo = ConversationRepository(db)
        await repo.update_state(uuid.UUID(convo_id), ConversationState.IDENTIFYING_PATIENT)
        await repo.append_message(uuid.UUID(convo_id), role="agent", content=greeting_text)

    messages = list(state.get("messages", []))
    messages.append({"role": "assistant", "content": greeting_text})

    return {
        "latest_agent_speech": greeting_text,
        "messages": messages,
    }
