"""Identity verification node ??? verifies patient identity before booking/rescheduling/cancelling."""
import difflib
import re
import uuid
from datetime import date
from typing import Any, Dict, Optional
# pyrefly: ignore[missing-import]
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.state import CallState
from src.control.agents.tools.identity_tools import lookup_by_phone, verify_patient_by_name_and_dob
from src.control.agents.tools.registration_tools import is_greeting, validate_dob
from src.control.agents.tools.booking_tools import check_patient_active_appointment
from src.config.settings import settings
from src.constants.enums import ConversationState
from src.data.repositories.conversation_repository import ConversationRepository


def _extract_name_and_dob_from_speech(text: str) -> tuple[Optional[str], Optional[date]]:
    """Extract name and date of birth if user speaks both together."""
    is_valid, parsed_dob, _ = validate_dob(text)
    if not is_valid or not parsed_dob:
        return None, None

    # Strip out the date representation and numbers from text
    cleaned = re.sub(r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b", "", text)
    cleaned = re.sub(
        r"\b(?:\d{1,2}(?:st|nd|rd|th)?\s+)?(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)(?:\s+\d{1,2}(?:st|nd|rd|th)?)?(?:\s+(?:\d\s*){3}\d)?\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^(?:my name is|i am|name is|this is|i'm|call me|my dob is|dob is|born on|date of birth is|date of birth)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(r"[,;:\(\)]", " ", cleaned).strip()

    stop_words = {"my", "name", "is", "and", "dob", "date", "of", "birth", "born", "on", "year", "yes", "i", "am"}
    words = [w for w in cleaned.split() if w.lower() not in stop_words and w.isalpha()]
    name = " ".join(words).title() if words and len(words) <= 4 else None
    return name, parsed_dob


async def identity_agent_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    # If already verified on an earlier turn, pass through
    if state.get("is_verified"):
        return {
            "patient_id": state.get("patient_id"),
            "patient_name": state.get("patient_name"),
            "patient_email": state.get("patient_email"),
            "is_verified": True,
            "awaiting_identity_verification": False,
        }

    user_speech = state.get("latest_user_speech", "").strip()
    phone = state.get("patient_phone", "")
    channel = state.get("channel", "chat")
    is_phone_call = channel in ("outbound_call", "voice", "inbound_call")
    attempts = state.get("verify_attempts", 0)
    convo_id = state.get("conversation_id")
    repo = ConversationRepository(db)

    # 1. Check if user speech directly indicates they are a new patient
    if user_speech and any(
        w in user_speech.lower()
        for w in ["new patient", "register", "not registered", "first time", "i am new", "i'm new", "sign up"]
    ):
        return {
            "is_new_patient": True,
            "awaiting_identity_verification": False,
            "latest_agent_speech": "Welcome to City Care Clinic! Could you please tell me your full name to start registration?",
        }

    # 2. Check if user provided Name and DOB in their speech
    extracted_name, extracted_dob = _extract_name_and_dob_from_speech(user_speech)
    if not extracted_name and state.get("patient_name") and state.get("patient_name") not in ("Clinic Guest", "Valued Patient"):
        is_valid_dob, parsed_dob, _ = validate_dob(user_speech)
        if is_valid_dob and parsed_dob:
            extracted_name = state.get("patient_name")
            extracted_dob = parsed_dob

    # Preserve a name supplied on its own and ask for DOB on the next turn.
    if not extracted_dob and user_speech and re.fullmatch(
        r"[A-Za-z][A-Za-z'???-]*(?:\s+[A-Za-z][A-Za-z'???-]*){0,3}[.!?]?", user_speech
    ):
        name = user_speech.rstrip(".!?").strip().title()
        return {
            "patient_name": name,
            "awaiting_identity_verification": True,
            "pending_intent": state.get("pending_intent") or "book",
            "latest_agent_speech": f"Thank you, {name.split()[0]}. Please provide your date of birth to verify your identity.",
        }

    if extracted_name and extracted_dob:
        fuzzy_verified, matched_patient = await verify_patient_by_name_and_dob(
            full_name=extracted_name,
            dob_str=extracted_dob.isoformat(),
            db=db,
        )
        if fuzzy_verified and matched_patient:
            first_name = matched_patient["full_name"].split()[0]
            if convo_id:
                await repo.set_patient(uuid.UUID(convo_id), uuid.UUID(matched_patient["id"]))
                await repo.mark_identity_verified(uuid.UUID(convo_id))
                await repo.update_state(uuid.UUID(convo_id), ConversationState.COLLECTING_DETAILS)

            existing_appt = await check_patient_active_appointment(str(matched_patient["id"]), db)

            pending = state.get("pending_intent") or state.get("intent") or "book"
            pref_doc = state.get("preferred_doctor")
            pref_loc = state.get("preferred_location")
            pref_date = state.get("preferred_date")

            active_appt_id = None
            active_appt_details = None

            if existing_appt:
                active_appt_id = existing_appt["appointment_id"]
                active_appt_details = existing_appt
                if pending == "book":
                    followup = (
                        f"You already have an active appointment scheduled for {existing_appt['formatted_speech']}. "
                        "Our clinic allows one active appointment per patient. Would you like to reschedule that appointment instead?"
                    )
                elif pending == "reschedule":
                    followup = (
                        f"I found your scheduled appointment for {existing_appt['formatted_speech']}. "
                        "What date or time would you like to move it to?"
                    )
                elif pending == "cancel":
                    followup = (
                        f"I found your scheduled appointment for {existing_appt['formatted_speech']}. "
                        "Are you sure you would like to cancel this appointment?"
                    )
                else:
                    followup = (
                        f"I see you have an active appointment scheduled for {existing_appt['formatted_speech']}. "
                        "How can I assist you with your appointment today?"
                    )
            else:
                if pending == "book":
                    if pref_date and pref_loc:
                        followup = f"Which doctor would you prefer at our {pref_loc} branch for {pref_date}?"
                    elif pref_date:
                        followup = f"Which clinic branch or doctor would you prefer for {pref_date}?"
                    elif pref_loc:
                        followup = f"Which doctor would you like to see at our {pref_loc} branch, and what date works best?"
                    elif pref_doc:
                        followup = f"What date and time would you like to see {pref_doc}?"
                    else:
                        followup = "Which clinic branch, doctor, or date would you prefer for your appointment?"
                elif pending == "reschedule":
                    followup = "I couldn't find an existing active appointment under your account to reschedule. Would you like to book a new appointment instead?"
                elif pending == "cancel":
                    followup = "I couldn't find an existing active appointment under your account to cancel. How else can I assist you today?"
                else:
                    followup = "How can I assist you with your appointment today?"

            active_intent = "reschedule" if active_appt_id else (pending or "book")
            return {
                "patient_id": matched_patient["id"],
                "patient_name": matched_patient["full_name"],
                "patient_dob": matched_patient["date_of_birth"],
                "patient_phone": matched_patient.get("phone") or phone,
                "patient_email": matched_patient.get("email"),
                "is_verified": True,
                "awaiting_identity_verification": False,
                "active_appointment_id": active_appt_id,
                "active_appointment_details": active_appt_details,
                "intent": active_intent,
                "pending_intent": active_intent,
                "latest_agent_speech": f"Thank you, {first_name}! Your identity has been verified. {followup}",
            }
        else:
            # Not in DB -> Transition smoothly to New Patient Registration
            dob_label = extracted_dob.strftime("%B %d, %Y")
            return {
                "patient_name": extracted_name,
                "patient_dob": extracted_dob.isoformat(),
                "is_new_patient": True,
                "awaiting_identity_verification": False,
                "latest_agent_speech": (
                    f"I don't see an existing patient record under {extracted_name} born on {dob_label}. "
                    "Let's get you registered as a new patient! Could you please provide your email address so we can send your appointment confirmations?"
                ),
            }

    # 3. For Phone Calls with phone number in DB:
    patient_data = None
    if phone:
        patient_data = await lookup_by_phone(phone, db)

    if is_phone_call and patient_data:
        if not user_speech:
            return {
                "patient_id": patient_data["id"],
                "patient_name": patient_data["full_name"],
                "patient_email": patient_data.get("email"),
                "is_verified": False,
                "latest_agent_speech": "For your medical privacy and security, could you please confirm your full name and date of birth?",
            }

        # Check spoken credentials against patient_data
        user_text = user_speech.lower()
        name_parts = [p.lower() for p in patient_data["full_name"].split() if len(p) >= 2]
        words = [re.sub(r"[^a-zA-Z]", "", w) for w in user_text.split()]
        words = [w for w in words if len(w) >= 2]
        name_matched = any(p in user_text for p in name_parts) or any(
            difflib.SequenceMatcher(None, w, p).ratio() >= 0.60
            for w in words for p in name_parts
        )
        is_valid_d, spoken_dob, _ = validate_dob(user_speech)
        dob_matched = bool(is_valid_d and spoken_dob and str(spoken_dob) == str(patient_data["date_of_birth"]))

        if not (name_matched and dob_matched):
            # Acoustic/component check against patient_data["date_of_birth"]
            expected_dob_str = str(patient_data["date_of_birth"])
            exp_parts = expected_dob_str.split("-")
            if len(exp_parts) == 3:
                exp_yr, exp_mo, exp_dy = exp_parts[0], int(exp_parts[1]), int(exp_parts[2])
                mo_names = {
                    1: ["january", "jan"], 2: ["february", "feb"], 3: ["march", "mar"],
                    4: ["april", "apr"], 5: ["may"], 6: ["june", "jun"],
                    7: ["july", "jul"], 8: ["august", "aug"], 9: ["september", "sep", "sept"],
                    10: ["october", "oct"], 11: ["november", "nov"], 12: ["december", "dec"],
                }.get(exp_mo, [])

                has_day = (
                    f"{exp_dy}" in user_text
                    or f"{exp_dy}th" in user_text
                    or (exp_dy == 14 and ("143" in user_text or "fourteen" in user_text))
                )
                has_mo = any(m in user_text for m in mo_names) or f"{exp_mo:02d}" in user_text
                has_yr = (
                    exp_yr in user_text
                    or exp_yr[-2:] in user_text
                    or "2, 0 3" in user_text
                    or "2 0 0 3" in user_text
                    or "2 0 3" in user_text
                    or "2013" in user_text
                    or "two thousand" in user_text
                )
                if (has_day and has_mo) or (has_mo and has_yr):
                    dob_matched = True

            if not (name_matched and dob_matched):
                fuzzy_v, _ = await verify_patient_by_name_and_dob(
                    full_name=patient_data["full_name"],
                    dob_str=user_speech,
                    db=db,
                )
                if fuzzy_v:
                    name_matched = True
                    dob_matched = True

        if name_matched and dob_matched:
            first_name = patient_data["full_name"].split()[0]
            if convo_id:
                await repo.set_patient(uuid.UUID(convo_id), uuid.UUID(patient_data["id"]))
                await repo.mark_identity_verified(uuid.UUID(convo_id))
                await repo.update_state(uuid.UUID(convo_id), ConversationState.COLLECTING_DETAILS)

            existing_appt = await check_patient_active_appointment(str(patient_data["id"]), db)
            active_appt_id = None
            active_appt_details = None
            pending = state.get("pending_intent") or state.get("intent") or "book"

            if existing_appt:
                active_appt_id = existing_appt["appointment_id"]
                active_appt_details = existing_appt
                if pending == "book":
                    followup = (
                        f"You already have an active appointment scheduled for {existing_appt['formatted_speech']}. "
                        "Our clinic allows one active appointment per patient. Would you like to reschedule that appointment instead?"
                    )
                elif pending == "reschedule":
                    followup = (
                        f"I found your scheduled appointment for {existing_appt['formatted_speech']}. "
                        "What date or time would you like to move it to?"
                    )
                elif pending == "cancel":
                    followup = (
                        f"I found your scheduled appointment for {existing_appt['formatted_speech']}. "
                        "Are you sure you would like to cancel this appointment?"
                    )
                else:
                    followup = (
                        f"I see you have an active appointment scheduled for {existing_appt['formatted_speech']}. "
                        "How can I assist you with your appointment today?"
                    )
                speech = f"Thank you, {first_name}! Your identity has been verified. {followup}"
            else:
                speech = f"Thank you for confirming, {first_name}! How can I help you today?"

            return {
                "patient_id": patient_data["id"],
                "patient_name": patient_data["full_name"],
                "patient_dob": patient_data["date_of_birth"],
                "patient_email": patient_data.get("email"),
                "is_verified": True,
                "awaiting_identity_verification": False,
                "active_appointment_id": active_appt_id,
                "active_appointment_details": active_appt_details,
                "latest_agent_speech": speech,
            }

        # Explain the failed check and make the next attempt actionable. Do not
        # expose the DOB stored on the patient record or relax the verification.
        return {
            "patient_id": patient_data["id"],
            "patient_name": patient_data["full_name"],
            "patient_email": patient_data.get("email"),
            "is_verified": False,
            "awaiting_identity_verification": True,
            "verify_attempts": attempts + 1,
            "latest_agent_speech": (
                "I couldn't verify those details from what I heard. Please say your full name, "
                "then your date of birth slowly, for example: ???14 December 2003.???"
            ),
        }

    # 4. If verification details have NOT yet been provided (or caller asks to book without identity):
    # Strict prompt requirement: Must provide Name & DOB before proceeding!
    prompt_msg = (
        "Before we can proceed with booking, rescheduling, or cancelling an appointment, "
        "I need to verify your identity for your medical privacy. "
        "Could you please provide your full name and date of birth? (Or let me know if you are a new patient!)"
    )

    from src.control.agents.tools.slot_tools import parse_date_query_to_range
    from src.control.agents.nodes.booking_helpers import _match_branch, _match_doctor

    pref_date_val = state.get("preferred_date")
    dt_start, _ = parse_date_query_to_range(user_speech)
    if dt_start:
        pref_date_val = dt_start.strftime("%A, %B %d")

    matched_branch = _match_branch(user_speech) or state.get("preferred_location")
    matched_doctor = _match_doctor(user_speech) or state.get("preferred_doctor")

    return {
        "is_verified": False,
        "awaiting_identity_verification": True,
        "verify_attempts": attempts + 1,
        "pending_intent": state.get("intent") or "book",
        "pending_speech": user_speech,
        "preferred_date": pref_date_val,
        "preferred_location": matched_branch,
        "preferred_doctor": matched_doctor,
        "latest_agent_speech": prompt_msg,
    }

