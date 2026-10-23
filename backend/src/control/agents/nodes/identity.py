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
from src.control.agents.tools.registration_tools import (
    is_closing_or_thanks,
    is_greeting,
    is_name_correction,
    is_name_only_candidate,
    name_from_speech,
    validate_dob,
)
from src.control.agents.tools.booking_tools import check_patient_active_appointment
from src.control.agents.tools.followup_tools import (
    followup_candidate_prompt,
    get_followup_candidates,
)
from src.config.settings import settings
from src.constants.enums import ConversationState
from src.data.repositories.conversation_repository import ConversationRepository


def _extract_name_and_dob_from_speech(text: str) -> tuple[Optional[str], Optional[date]]:
    """Extract name and date of birth if user speaks both together."""
    # Validate the date fragment itself instead of requiring the whole spoken
    # sentence to be a date. This handles natural speech such as "Kiran, my
    # date of birth is 31st July 2004" consistently across STT providers.
    date_fragment = re.search(
        r"\b(?:\d{1,2}[-/.]\d{1,2}[-/.]\d{4}|\d{1,2}(?:st|nd|rd|th)?\s+"
        r"(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\s+(?:\d\s*){3}\d)\b",
        text,
        flags=re.IGNORECASE,
    )
    date_text = date_fragment.group(0) if date_fragment else text
    is_valid, parsed_dob, _ = validate_dob(date_text)
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
        r"^(?:hello[\s,!.]*)?(?:my name is|i am|name is|this is|i'm|call me|my dob is|dob is|born on|date of birth is|date of birth)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    # STT commonly places a sentence stop after the name ("Kiran. My date of
    # birth..."). Treat that punctuation as a separator before accepting name
    # words, otherwise "Kiran." is rejected by ``isalpha`` below.
    cleaned = re.sub(r"[,;:\(\).]", " ", cleaned).strip()

    stop_words = {"my", "name", "is", "and", "dob", "date", "of", "birth", "born", "on", "year", "yes", "i", "am"}
    words = [w for w in cleaned.split() if w.lower() not in stop_words and w.isalpha()]
    name = " ".join(words).title() if words and len(words) <= 4 else None
    return name, parsed_dob


_NAME_CORRECTION_STRIP = re.compile(
    r"\b(?:(?:this|that|it)(?: is|'s| was)? not my name|not my name|wrong name|that(?:'s| is) wrong|"
    r"(?:that|this)(?: is|'s) not me|that name is wrong|isn't my name|is not my name)\b",
    re.IGNORECASE,
)


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
    attempts = int(state.get("verify_attempts") or 0)
    convo_id = state.get("conversation_id")
    repo = ConversationRepository(db)

    lower_speech = user_speech.lower()
    # Short acknowledgements are not identity data. This guard is especially
    # important for the chat endpoint, which can route bare text directly here.
    if is_closing_or_thanks(user_speech) or is_greeting(user_speech):
        existing_name = state.get("patient_name")
        if existing_name and existing_name not in ("Clinic Guest", "Valued Patient"):
            prompt = f"You're welcome, {existing_name.split()[0]}. Please provide your date of birth to verify your identity."
        else:
            prompt = "You're welcome. Please provide your full name and date of birth to verify your identity."
        return {
            "is_verified": False,
            "awaiting_identity_verification": True,
            "latest_agent_speech": prompt,
        }

    # Let a patient choose registration at any point during verification.
    if user_speech and any(
        phrase in lower_speech
        for phrase in ("new patient", "register", "not registered", "first time", "i am new", "i'm new", "sign up")
    ):
        return {
            "is_new_patient": True,
            "is_verified": False,
            "verify_attempts": 0,
            "patient_name": None,
            "patient_dob": None,
            "patient_email": None,
            "patient_phone": None,
            "awaiting_identity_verification": False,
            "latest_agent_speech": f"Welcome to {settings.CLINIC_NAME}! Could you please tell me your full name to start registration?",
        }

    # Do not keep collecting registration data when the patient says they
    # already have a record. Clear the failed values so the corrected pair is
    # independently provided and checked.
    if user_speech and any(
        phrase in lower_speech
        for phrase in ("old patient", "existing patient", "already a patient", "already registered", "i am a patient", "i'm a patient")
    ):
        return {
            "is_new_patient": False,
            "is_verified": False,
            "patient_name": None,
            "patient_dob": None,
            "awaiting_identity_verification": True,
            "latest_agent_speech": "Understood. Please provide your full name and date of birth again so I can verify your existing patient record.",
        }

    # 2. Check if user provided Name and DOB in their speech
    extracted_name, extracted_dob = _extract_name_and_dob_from_speech(user_speech)
    if (
        not extracted_name
        and state.get("patient_name")
        and state.get("patient_name") not in ("Clinic Guest", "Valued Patient")
        and is_name_only_candidate(str(state.get("patient_name")))
    ):
        is_valid_dob, parsed_dob, _ = validate_dob(user_speech)
        if is_valid_dob and parsed_dob:
            extracted_name = state.get("patient_name")
            extracted_dob = parsed_dob

    # "This is not my name": drop the captured name (and any DOB) and take the corrected one.
    if is_name_correction(user_speech):
        remainder = _NAME_CORRECTION_STRIP.sub(" ", user_speech)
        corrected = name_from_speech(re.sub(r"^[\s,.\-]*(?:(?:no|nope|but|actually|sorry)\b[\s,.\-]*)*", "", remainder, flags=re.IGNORECASE))
        if corrected:
            return {
                "patient_name": corrected,
                "patient_dob": None,
                "verify_attempts": 0,
                "awaiting_identity_verification": True,
                "pending_intent": state.get("pending_intent") or "book",
                "latest_agent_speech": f"Sorry about that, {corrected.split()[0]}. Please provide your date of birth to verify your identity.",
            }
        return {
            "patient_name": None,
            "patient_dob": None,
            "verify_attempts": 0,
            "awaiting_identity_verification": True,
            "latest_agent_speech": "Sorry about that. Could you please tell me your full name again?",
        }

    # Preserve a name supplied on its own and ask for DOB on the next turn.
    if not extracted_dob and is_name_only_candidate(user_speech):
        name = name_from_speech(user_speech) or user_speech.rstrip(".!?").strip().title()
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
                    if state.get("preferred_appointment_type") == "Follow-up Consultation":
                        candidates = await get_followup_candidates(matched_patient["id"], db)
                        if not candidates:
                            followup = (
                                "I couldn't find a previous completed appointment to link this follow-up to. "
                                "Would you like to book a regular General Consultation instead?"
                            )
                            return {
                                "patient_id": matched_patient["id"],
                                "patient_name": matched_patient["full_name"],
                                "patient_dob": matched_patient["date_of_birth"],
                                "patient_phone": matched_patient.get("phone") or phone,
                                "patient_email": matched_patient.get("email"),
                                "is_verified": True,
                                "verify_attempts": 0,
                                "awaiting_identity_verification": False,
                                "intent": "book",
                                "pending_intent": "book",
                                "preferred_appointment_type": None,
                                "awaiting_followup_decision": True,
                                "awaiting_followup_visit": False,
                                "followup_candidates": [],
                                "latest_agent_speech": f"Thank you, {first_name}! Your identity is verified. {followup}",
                            }

                        followup = followup_candidate_prompt(candidates)
                        followup_state = {
                            "preferred_appointment_type": "Follow-up Consultation",
                            "followup_candidates": candidates,
                            "awaiting_followup_visit": len(candidates) > 1,
                            "awaiting_followup_decision": False,
                        }
                        if len(candidates) == 1:
                            visit = candidates[0]
                            followup_state.update({
                                "preferred_doctor": visit["doctor_name"],
                                "preferred_specialty": visit["specialty"],
                                "preferred_location": visit["location_name"],
                                "preferred_date": None,
                                "awaiting_preferred_date": True,
                            })
                    elif pref_date and pref_loc:
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
            result = {
                "patient_id": matched_patient["id"],
                "patient_name": matched_patient["full_name"],
                "patient_dob": matched_patient["date_of_birth"],
                "patient_phone": matched_patient.get("phone") or phone,
                "patient_email": matched_patient.get("email"),
                "is_verified": True,
                "verify_attempts": 0,
                "awaiting_identity_verification": False,
                "active_appointment_id": active_appt_id,
                "active_appointment_details": active_appt_details,
                "intent": active_intent,
                "pending_intent": active_intent,
                "latest_agent_speech": f"Thank you, {first_name}! Your identity has been verified. {followup}",
            }
            if not existing_appt and pending == "book" and state.get("preferred_appointment_type") == "Follow-up Consultation":
                result.update(followup_state)
            return result
        else:
            # A first failed credential pair prompts for a correction. A
            # second failed pair escalates instead of creating a duplicate
            # patient record. This node is shared by every conversation channel.
            next_attempt = attempts + 1
            if attempts >= 1:
                return {
                    "is_new_patient": False,
                    "is_verified": False,
                    "awaiting_identity_verification": True,
                    "verify_attempts": next_attempt,
                    "handoff_required": True,
                    "handoff_reason": "Patient identity could not be verified after two attempts",
                    "latest_agent_speech": "I still couldn't verify those details after two attempts. I'll connect you with our front desk team to help verify your patient record.",
                }
            return {
                "patient_name": extracted_name,
                "patient_dob": extracted_dob.isoformat(),
                "is_new_patient": False,
                "is_verified": False,
                "awaiting_identity_verification": True,
                "verify_attempts": next_attempt,
                "latest_agent_speech": (
                    "I couldn't match that name and date of birth to a patient record. Please check the details and try again. "
                    "If you are a new patient, tell me and I'll help you register."
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
        # Phone lookup is only a candidate lookup, never proof of identity.
        # Require the spoken name and a complete, parsed DOB to match exactly.
        spoken_name, spoken_dob = _extract_name_and_dob_from_speech(user_speech)
        is_valid_d, parsed_spoken_dob, _ = validate_dob(user_speech)
        if spoken_dob is None and is_valid_d:
            spoken_dob = parsed_spoken_dob
        if spoken_name:
            spoken_words = [part.lower() for part in spoken_name.split()]
            name_matched = bool(spoken_words) and all(
                any(difflib.SequenceMatcher(None, part, expected).ratio() >= 0.80 for expected in name_parts)
                for part in spoken_words
            )
        dob_matched = bool(
            spoken_dob
            and patient_data.get("date_of_birth")
            and spoken_dob.isoformat() == str(patient_data["date_of_birth"])
        )

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
                "verify_attempts": 0,
                "awaiting_identity_verification": False,
                "active_appointment_id": active_appt_id,
                "active_appointment_details": active_appt_details,
                "latest_agent_speech": speech,
            }

        # Explain the failed check, allow one retry, then escalate. Never
        # expose the DOB stored on the patient record or relax verification.
        next_attempt = attempts + 1
        if attempts >= 1:
            return {
                "patient_id": patient_data["id"],
                "patient_name": patient_data["full_name"],
                "patient_email": patient_data.get("email"),
                "is_verified": False,
                "awaiting_identity_verification": True,
                "verify_attempts": next_attempt,
                "handoff_required": True,
                "handoff_reason": "Patient identity could not be verified after two attempts",
                "latest_agent_speech": "I still couldn't verify those details after two attempts. I'll connect you with our front desk team to help verify your patient record.",
            }
        return {
            "patient_id": patient_data["id"],
            "patient_name": patient_data["full_name"],
            "patient_email": patient_data.get("email"),
            "is_verified": False,
            "awaiting_identity_verification": True,
            "verify_attempts": next_attempt,
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
        "pending_intent": state.get("intent") or "book",
        "pending_speech": user_speech,
        "preferred_date": pref_date_val,
        "preferred_location": matched_branch,
        "preferred_doctor": matched_doctor,
        "latest_agent_speech": prompt_msg,
    }

