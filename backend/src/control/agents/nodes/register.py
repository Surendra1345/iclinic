"""New patient registration node — collects Name, DOB, Email, and Phone."""
import re
import uuid
from src.config.settings import settings
from typing import Any, Dict
# pyrefly: ignore[missing-import]
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.state import CallState
from src.control.agents.tools.registration_tools import (
    extract_email,
    extract_phone,
    is_closing_or_thanks,
    is_greeting,
    register_new_patient,
    dob_retry_message,
    validate_dob,
)
from src.control.agents.tools.booking_tools import check_patient_active_appointment
from src.constants.enums import ConversationState
from src.data.repositories.conversation_repository import ConversationRepository


def _clean_name(text: str) -> str:
    cleaned = re.sub(
        r"^(?:my name is|i am|name is|this is|i'm|call me)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(r"[,;:\(\)]", " ", cleaned).strip()
    # Remove email or phone digits if present in text
    cleaned = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b", "", cleaned)
    cleaned = re.sub(r"\b(?:\+91[\-\s]?)?[6-9]\d{9}\b", "", cleaned)
    cleaned = re.sub(r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b", "", cleaned)
    words = [w for w in cleaned.split() if w.isalpha()]
    return " ".join(words).title() if words else cleaned.title()


async def register_patient_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    user_speech = state.get("latest_user_speech", "").strip()
    channel = state.get("channel", "chat")
    is_phone_call = channel in ("outbound_call", "voice", "inbound_call")
    convo_id = state.get("conversation_id")
    repo = ConversationRepository(db)

    # Current collected state
    name = state.get("patient_name")
    dob_str = state.get("patient_dob")
    email = state.get("patient_email")
    phone = state.get("patient_phone", "")

    # Clean existing dummy/filler names
    from src.control.agents.tools.registration_tools import is_invalid_name
    if name and is_invalid_name(name):
        name = None

    # Acknowledgements must not be stored as the patient's name during signup.
    if is_closing_or_thanks(user_speech):
        if not name:
            prompt = "You're welcome. Could you please tell me your full name to continue registration?"
        elif not dob_str:
            prompt = f"You're welcome, {name}. Please provide your date of birth (Day-Month-Year)."
        elif not email:
            prompt = f"You're welcome, {name}. Please provide your email address for appointment confirmations."
        elif not phone and not is_phone_call:
            prompt = "You're welcome. Please provide your 10-digit mobile number to finish registration."
        else:
            prompt = None
        if prompt:
            return {
                "is_new_patient": True,
                "patient_name": name,
                "patient_dob": dob_str,
                "patient_email": email,
                "patient_phone": phone,
                "latest_agent_speech": prompt,
            }

    # 1. Opportunistic extraction: Extract any newly provided details from user_speech
    parsed_email = extract_email(user_speech)
    if parsed_email and not email:
        email = parsed_email

    parsed_phone = extract_phone(user_speech)
    if parsed_phone and not phone:
        phone = parsed_phone

    is_valid_dob, parsed_dob, _ = validate_dob(user_speech)
    if is_valid_dob and parsed_dob and not dob_str:
        dob_str = parsed_dob.isoformat()

    is_reg_keyword = any(
        w in user_speech.lower()
        for w in ["register", "registration", "new patient", "sign up", "first time", "how do i register", "i want to register"]
    )

    # If we don't have name yet, and user speech is not just a greeting or registration trigger:
    if not name and user_speech and not is_greeting(user_speech) and not is_reg_keyword and not is_invalid_name(user_speech):
        # If user speech is not just a DOB or email or phone
        if not is_valid_dob and not parsed_email and not parsed_phone:
            candidate = _clean_name(user_speech)
            if candidate and not is_invalid_name(candidate):
                name = candidate

    # 2. Check which basic detail is still missing (Name -> DOB -> Email -> Phone)

    # Step A: Missing Full Name
    if not name:
        return {
            "is_new_patient": True,
            "patient_name": None,
            "latest_agent_speech": f"Welcome to {settings.CLINIC_NAME}! Could you please tell me your full name to start registration?",
        }

    # Step B: Missing Date of Birth
    if not dob_str:
        # Check if user just provided DOB in this turn
        if is_valid_dob and parsed_dob:
            dob_str = parsed_dob.isoformat()
        else:
            return {
                "patient_name": name,
                "is_new_patient": True,
                "latest_agent_speech": dob_retry_message(user_speech)
                or f"Thank you, {name}. What is your date of birth? (Please state as Day-Month-Year)",
            }

    # Step C: Missing Email
    if not email:
        if parsed_email:
            email = parsed_email
        else:
            return {
                "patient_name": name,
                "patient_dob": dob_str,
                "is_new_patient": True,
                "latest_agent_speech": f"Thank you, {name}. Could you please provide your email address so we can send your appointment confirmations?",
            }

    # Step D: Missing Phone Number (only required if not a phone call where caller ID is known)
    if not is_phone_call and not phone:
        if parsed_phone:
            phone = parsed_phone
        else:
            return {
                "patient_name": name,
                "patient_dob": dob_str,
                "patient_email": email,
                "is_new_patient": True,
                "latest_agent_speech": "Thank you. And lastly, what is your 10-digit mobile number?",
            }

    # If phone is still blank in phone call, default to caller ID if available
    if not phone:
        phone = state.get("caller_number") or "+910000000000"

    # Step E: All basic details are collected! Save patient in PostgreSQL DB
    from datetime import date as dt_date
    dob_obj = dt_date.fromisoformat(dob_str) if isinstance(dob_str, str) else dob_str

    new_patient = await register_new_patient(
        full_name=name,
        dob=dob_obj,
        phone=phone,
        email=email,
        db=db,
    )

    if convo_id:
        await repo.update_collected_details(
            uuid.UUID(convo_id),
            {
                "registration_name": name,
                "registration_dob": dob_str,
                "patient_email": email,
                "patient_phone": phone,
                "is_new_patient": False,
                "is_verified": True,
            },
        )
        await repo.set_patient(uuid.UUID(convo_id), uuid.UUID(new_patient["id"]))
        await repo.mark_identity_verified(uuid.UUID(convo_id))
        await repo.update_state(uuid.UUID(convo_id), ConversationState.COLLECTING_DETAILS)

    active_appointment = await check_patient_active_appointment(
        new_patient["id"],
        db,
    )
    if active_appointment:
        latest_agent_speech = (
            f"You already have an active appointment scheduled for "
            f"{active_appointment['formatted_speech']}. "
            "Our clinic allows one active appointment per patient. "
            "Would you like to reschedule that appointment instead?"
        )
    else:
        latest_agent_speech = (
            f"Thank you, {name}. You are now registered and verified with {settings.CLINIC_NAME}. "
            "How can I assist you with your appointment today?"
        )

    result = {
        "patient_id": new_patient["id"],
        "patient_name": new_patient["full_name"],
        "patient_dob": new_patient["date_of_birth"],
        "patient_phone": new_patient["phone"],
        "patient_email": new_patient.get("email") or email,
        "is_verified": True,
        "is_new_patient": False,
        "awaiting_identity_verification": False,
        "latest_agent_speech": latest_agent_speech,
    }
    if active_appointment:
        result["active_appointment_id"] = active_appointment["appointment_id"]
        result["active_appointment_details"] = active_appointment
    return result
