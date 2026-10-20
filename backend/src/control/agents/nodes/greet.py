"""Greet node — speaks opening greeting."""
from typing import Any, Dict
# pyrefly: ignore[missing-import]
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.state import CallState
from src.config.settings import settings
from src.constants.enums import ConversationState
from src.data.repositories.conversation_repository import ConversationRepository


async def greet_patient_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    user_speech = state.get("latest_user_speech", "").strip()
    is_verified = state.get("is_verified", False)
    patient_name = state.get("patient_name")
    channel = state.get("channel", "outbound_call")

    first_name = (
        patient_name.split()[0]
        if patient_name and patient_name not in ("Clinic Guest", "Valued Patient")
        else None
    )

    if user_speech:
        # Conversational greeting response (e.g. Patient says "Hii", "Hello")
        if is_verified and first_name:
            greeting_text = (
                f"Hello, {first_name}! Welcome to {settings.CLINIC_NAME}. "
                "How can I assist you with your appointment today?"
            )
        else:
            greeting_text = (
                f"Hello! Welcome to {settings.CLINIC_NAME}. How can I assist you today? "
                "If you would like to book, reschedule, or cancel an appointment, please let me know or share your full name and date of birth to get started."
            )
    else:
        # Initial call connect greeting (before caller speaks)
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
