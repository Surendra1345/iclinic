"""Identity verification node."""
import uuid
from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.state import CallState
from src.control.agents.tools.identity_tools import lookup_by_phone, verify_patient_by_name_and_dob
from src.config.settings import settings
from src.constants.enums import ConversationState
from src.data.repositories.conversation_repository import ConversationRepository


async def identity_agent_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    # If already verified on an earlier turn, pass through
    if state.get("is_verified"):
        return {
            "patient_id": state.get("patient_id"),
            "patient_name": state.get("patient_name"),
            "patient_email": state.get("patient_email"),
            "is_verified": True,
        }

    user_speech = state.get("latest_user_speech", "").strip()
    phone = state.get("patient_phone", "")
    attempts = state.get("verify_attempts", 0)
    convo_id = state.get("conversation_id")
    repo = ConversationRepository(db)

    # 1. Lookup patient by phone
    patient_data = None
    if phone:
        patient_data = await lookup_by_phone(phone, db)

    # If phone does NOT exist in DB:
    if not patient_data:
        if not user_speech:
            return {
                "patient_id": None,
                "patient_name": None,
                "is_new_patient": False,
                "latest_agent_speech": "I don't see an existing file under this phone number. Are you a new patient with City Care Clinic?",
            }
        user_text = user_speech.lower()
        if any(w in user_text for w in ["new", "register", "first time", "not registered", "yes"]):
            return {
                "is_new_patient": True,
                "latest_agent_speech": "Welcome to City Care Clinic! May I have your full name and date of birth to get you registered?",
            }
        # If existing patient calling from different number
        return {
            "is_new_patient": True,
            "latest_agent_speech": "Could you please state your full name and date of birth so I can locate your chart?",
        }

    # 2. Phone number EXISTS in DB -> Verify Name & DOB
    # If user hasn't spoken yet (initial call connect), ask for Name & DOB
    if not user_speech:
        return {
            "patient_id": patient_data["id"],
            "patient_name": patient_data["full_name"],
            "patient_email": patient_data.get("email"),
            "is_verified": False,
            "latest_agent_speech": "For your medical privacy and security, could you please confirm your full name and date of birth?",
        }

    import difflib

    user_text = user_speech.lower()
    name_parts = [p.lower() for p in patient_data["full_name"].split() if len(p) >= 2]
    words = [w.strip(".,?!\"'") for w in user_text.split()]

    # 1. Resilient name matching (exact substring, word match, or phonetic similarity >= 0.65)
    name_matched = False
    for p in name_parts:
        if p in user_text:
            name_matched = True
            break
        for w in words:
            if difflib.SequenceMatcher(None, w, p).ratio() >= 0.65:
                name_matched = True
                break
        if name_matched:
            break

    # 2. Date of birth matching (day, month name/num, year)
    dob_str = str(patient_data["date_of_birth"] or "")
    month_names = {
        "01": ["january", "jan"], "02": ["february", "feb"], "03": ["march", "mar"],
        "04": ["april", "apr"], "05": ["may"], "06": ["june", "jun"],
        "07": ["july", "jul"], "08": ["august", "aug"], "09": ["september", "sep", "sept"],
        "10": ["october", "oct"], "11": ["november", "nov"], "12": ["december", "dec"]
    }
    dob_parts = dob_str.split("-") if "-" in dob_str else []
    dob_matched = False
    if len(dob_parts) == 3:
        y, m, d = dob_parts
        d_int = str(int(d))
        m_aliases = month_names.get(m, [])
        has_d = (d in user_text or d_int in user_text or f"{d_int}th" in user_text or f"{d_int}st" in user_text or f"{d_int}nd" in user_text or f"{d_int}rd" in user_text)
        has_m = (m in user_text or any(alias in user_text for alias in m_aliases))
        has_y = (y in user_text or y[-2:] in user_text)

        dob_score = sum([has_d, has_m, has_y])
        # Verified if all 3 parts of DOB present, OR name matched with at least 2 parts (e.g. Month + Day), OR full DOB
        if dob_score >= 3 or (name_matched and dob_score >= 2) or (name_matched and has_d and has_m):
            dob_matched = True
            name_matched = True  # Verified via full credentials

    # Fallback to fuzzy DB matcher
    if not (name_matched and dob_matched):
        fuzzy_verified, _ = await verify_patient_by_name_and_dob(
            full_name=patient_data["full_name"],
            dob_str=user_speech,
            db=db,
        )
        if fuzzy_verified:
            name_matched = True
            dob_matched = True

    # Check match result
    if name_matched and dob_matched:
        first_name = patient_data["full_name"].split()[0]
        if convo_id:
            await repo.set_patient(uuid.UUID(convo_id), uuid.UUID(patient_data["id"]))
            await repo.mark_identity_verified(uuid.UUID(convo_id))
            await repo.update_state(uuid.UUID(convo_id), ConversationState.COLLECTING_DETAILS)

        return {
            "patient_id": patient_data["id"],
            "patient_name": patient_data["full_name"],
            "patient_dob": patient_data["date_of_birth"],
            "patient_email": patient_data.get("email"),
            "is_verified": True,
            "verify_attempts": attempts,
            "latest_agent_speech": f"Thank you for confirming, {first_name}! How can I help you today?",
        }

    # Verification attempt failed
    attempts += 1
    if attempts >= settings.MAX_VERIFY_ATTEMPTS:
        if convo_id:
            await repo.update_state(uuid.UUID(convo_id), ConversationState.HANDED_TO_FRONT_DESK)
        return {
            "verify_attempts": attempts,
            "handoff_required": True,
            "handoff_reason": "2 failed identity verification attempts",
            "latest_agent_speech": "For your medical privacy and security, I will transfer you to our front desk staff to assist you. Please hold on.",
        }

    return {
        "verify_attempts": attempts,
        "is_verified": False,
        "latest_agent_speech": "I couldn't verify that name and date of birth with our records. Could you please confirm your full name and date of birth once more?",
    }
