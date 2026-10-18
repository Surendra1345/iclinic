"""New patient registration node."""
import uuid
from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.state import CallState
from src.control.agents.tools.registration_tools import register_new_patient, validate_dob
from src.constants.enums import ConversationState
from src.data.repositories.conversation_repository import ConversationRepository


async def register_patient_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    user_speech = state.get("latest_user_speech", "").strip()
    phone = state.get("patient_phone", "")
    convo_id = state.get("conversation_id")
    repo = ConversationRepository(db)

    name = state.get("patient_name")
    dob_str = state.get("patient_dob")

    # If we don't have name yet
    if not name:
        if user_speech:
            return {
                "patient_name": user_speech,
                "latest_agent_speech": f"Thank you, {user_speech}. What is your date of birth?",
            }
        return {
            "latest_agent_speech": "Could you please tell me your full name to start registration?",
        }

    # If we have name, but not DOB
    if not dob_str:
        if user_speech:
            is_valid, parsed_dob, error_msg = validate_dob(user_speech)
            if not is_valid or not parsed_dob:
                return {
                    "latest_agent_speech": f"{error_msg} Could you please state your date of birth again?",
                }

            # Create patient record in DB
            new_patient = await register_new_patient(
                full_name=name,
                dob=parsed_dob,
                phone=phone,
                email=state.get("patient_email"),
                db=db,
            )

            if convo_id:
                await repo.set_patient(uuid.UUID(convo_id), uuid.UUID(new_patient["id"]))
                await repo.mark_identity_verified(uuid.UUID(convo_id))
                await repo.update_state(uuid.UUID(convo_id), ConversationState.COLLECTING_DETAILS)

            return {
                "patient_id": new_patient["id"],
                "patient_name": new_patient["full_name"],
                "patient_dob": new_patient["date_of_birth"],
                "is_verified": True,
                "is_new_patient": False,
                "latest_agent_speech": f"Thank you, {name}. You are now registered with us. How can I assist you with your appointment today?",
            }

        return {
            "latest_agent_speech": "Could you please state your date of birth?",
        }

    return {}
