"""Intent detection node — classifies caller intent using Gemini 2.0 Flash."""
import logging
import re
from difflib import SequenceMatcher
from typing import Any, Dict
# pyrefly: ignore[missing-import]
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.control.agents.prompts import INTENT_DETECTION_PROMPT
from src.control.agents.state import CallState
from src.control.agents.tools.registration_tools import is_closing_or_thanks, is_greeting
from src.services.gemini_service import GeminiService

logger = logging.getLogger(__name__)


async def detect_intent_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    user_speech = state.get("latest_user_speech", "").strip()
    if not user_speech:
        return {"intent": "unknown"}

    lower = user_speech.lower()
    current_intent = state.get("intent")
    has_active_appt = bool(state.get("active_appointment_id") or state.get("active_appointment_details"))
    last_agent_speech = state.get("latest_agent_speech", "").lower()

    # A verified patient may explicitly ask for a *new* booking after we told
    # them they already have an appointment. Keep that as BOOK so the booking
    # node can enforce the one-active-appointment rule. Do not reinterpret it
    # as consent to reschedule merely because the previous agent turn mentioned
    # rescheduling.
    explicit_new_booking = any(phrase in lower for phrase in (
        "i want to book", "i want book", "i'd like to book", "i would like to book",
        "book a new appointment", "new appointment", "make a new appointment",
        "schedule a new appointment", "i want an appointment", "i need an appointment",
    ))
    if has_active_appt and explicit_new_booking:
        return {"intent": "book"}

    # Answer doctor availability questions as information requests, including
    # when the previous turn asked whether to reschedule. They must not cause
    # the active appointment to be moved or a new slot to be held.
    asks_doctor_availability = (
        any(term in lower for term in ("doctor", "doctors", "physician", "general consultation", "general medicine"))
        and any(term in lower for term in ("available", "availability", "which", "who", "list", "show"))
    )
    if asks_doctor_availability:
        from src.control.agents.tools.slot_tools import get_branch_doctors_info

        all_branch_doctors = []
        known_specialties = set()
        for branch in ("Anna Nagar", "T. Nagar", "Velachery", "Tambaram"):
            branch_info = get_branch_doctors_info(branch)
            all_branch_doctors.append((branch, branch_info["doctors"]))
            known_specialties.update(doctor["specialty"] for doctor in branch_info["doctors"])

        # "General consultation" is the clinic's General Medicine service.
        requested_specialty = None
        if any(term in lower for term in (
            "general consultation", "general medicine", "general doctor", "general physician"
        )):
            requested_specialty = "General Medicine"
        else:
            words = re.findall(r"[a-z]+", lower)
            candidates = sorted(known_specialties, key=len, reverse=True)
            for specialty in candidates:
                canonical = specialty.lower()
                if canonical in lower:
                    requested_specialty = specialty
                    break
            if not requested_specialty:
                # Accommodate common speech-to-text/spelling errors such as
                # "cordiology" for "cardiology", without defaulting to a
                # different specialty.
                matches = [
                    (SequenceMatcher(None, word, specialty.lower()).ratio(), specialty)
                    for word in words
                    for specialty in candidates
                    if len(word) >= 5
                ]
                if matches:
                    score, specialty = max(matches)
                    if score >= 0.76:
                        requested_specialty = specialty

        if requested_specialty:
            matching_doctors = [
                f"{doctor['name']} at {branch}"
                for branch, doctors in all_branch_doctors
                for doctor in doctors
                if doctor["specialty"].lower() == requested_specialty.lower()
            ]
            if matching_doctors:
                answer = (
                    f"For {requested_specialty}, available doctors are "
                    f"{', '.join(matching_doctors)}. Which branch would you prefer?"
                )
            else:
                answer = f"I couldn't find any listed doctors for {requested_specialty}. Which specialty would you like to ask about?"
        else:
            all_specialties = ", ".join(sorted(known_specialties))
            answer = f"We have doctors in these specialties: {all_specialties}. Which specialty are you interested in?"
        return {
            "intent": "faq_response",
            "preferred_specialty": requested_specialty,
            "latest_agent_speech": answer,
        }

    # Continue a doctor-browsing exchange using the specialty from the prior
    # turn. A branch-only reply should filter the list, not restart the search.
    if state.get("intent") == "faq_response" and state.get("preferred_specialty"):
        from src.control.agents.nodes.booking_helpers import _match_branch
        from src.control.agents.tools.slot_tools import get_branches_for_specialty, get_branch_doctors_info

        selected_branch = _match_branch(user_speech)
        if selected_branch:
            specialty = state["preferred_specialty"]
            branch_info = get_branch_doctors_info(selected_branch)
            doctors = [
                doctor["name"]
                for doctor in branch_info["doctors"]
                if doctor["specialty"].lower() == specialty.lower()
            ]
            if doctors:
                answer = (
                    f"For {specialty} at our {selected_branch} branch, "
                    f"the available doctor is {', '.join(doctors)}. "
                    "Would you like to book with this doctor?"
                )
            else:
                branches = get_branches_for_specialty(specialty)
                answer = (
                    f"Our {selected_branch} branch does not offer {specialty}. "
                    f"It is available at {', '.join(branches)}. Which branch would you prefer?"
                )
            return {
                "intent": "faq_response",
                "preferred_specialty": specialty,
                "preferred_location": selected_branch if doctors else None,
                "latest_agent_speech": answer,
            }

    # Fast path -2: Reschedule prompt on active appointment check
    asked_reschedule_active = has_active_appt and (
        "reschedule that appointment" in last_agent_speech
        or "allows one active" in last_agent_speech
        or "reschedule that appointment instead" in last_agent_speech
    )
    if asked_reschedule_active:
        # Declining the reschedule offer keeps the existing appointment. It
        # should not close the conversation or silently change its intent.
        if is_closing_or_thanks(user_speech):
            return {
                "intent": "close",
                "latest_agent_speech": "You're very welcome! I am always here to help. Your appointment remains confirmed. Have a wonderful day!",
            }
        if any(w in lower for w in ("no", "nope", "don't", "do not", "keep", "leave it")):
            return {
                "intent": "faq_response",
                "latest_agent_speech": "No problem. Your current appointment remains unchanged. How else can I help?",
            }
        if any(w in lower for w in ("yes", "sure", "okay", "ok", "please reschedule", "reschedule it", "move it", "change it")):
            return {"intent": "reschedule"}
        return {
            "intent": "faq_response",
            "latest_agent_speech": "Your current appointment is unchanged. Would you like to reschedule it, or can I help with something else?",
        }

    # Fast path -1b: General Closing / Gratitude check ("Thank you", "Thanks", "Goodbye", etc.)
    if is_closing_or_thanks(user_speech):
        return {
            "intent": "close",
            "latest_agent_speech": f"You're very welcome! I am always here to help. Thank you for choosing {settings.CLINIC_NAME}. Have a wonderful day!",
        }

    # Fast path -1: Greeting check ("Hii", "Hello", "Hey", etc.)
    if is_greeting(user_speech):
        return {"intent": "greet"}

    # A bare name is identity information, not a booking request. This also
    # prevents the classifier from starting scheduling before name/DOB checks.
    name_words = lower.rstrip(".!?").split()
    non_name_terms = {"book", "appointment", "schedule", "doctor", "cancel", "reschedule", "change", "help", "yes", "no", "hello", "hi"}
    if (
        not state.get("is_verified")
        and not any(word in non_name_terms for word in name_words)
        and re.fullmatch(r"[a-z][a-z'’-]*(?:\s+[a-z][a-z'’-]*){0,3}[.!?]?", lower)
    ):
        return {"intent": "identity"}

    # Fast path 0: If in new patient registration flow
    if state.get("is_new_patient") and not state.get("is_verified"):
        return {"intent": "register"}

    # Fast path 0a: If awaiting identity verification from previous turn or user states DOB/Name
    from src.control.agents.tools.registration_tools import validate_dob
    has_dob_match, _, _ = validate_dob(user_speech)
    if (state.get("awaiting_identity_verification") or has_dob_match or any(w in lower for w in ["dob", "date of birth", "born on"])) and not state.get("is_verified"):
        if any(w in lower for w in ["register", "new patient", "new", "sign up", "not registered"]):
            return {"intent": "register"}
        return {"intent": "identity"}

    # Fast path 0b: New patient registration direct keywords
    if any(w in lower for w in [
        "register as a new patient", "new patient registration", "how do i register",
        "i want to register", "register me", "registration", "i am a new patient", "sign up", "register"
    ]):
        return {"intent": "register"}

    # Fast path 0c: If awaiting preferred date or email from patient
    if state.get("awaiting_preferred_date") or state.get("awaiting_patient_email"):
        curr = state.get("intent")
        if curr in ("identity", "greet", None):
            curr = state.get("pending_intent") or ("reschedule" if has_active_appt else "book")
        return {"intent": curr}

    # Fast path 0d: Specific branch names, doctor names, or date queries
    if any(b in lower for b in ["t nagar", "t. nagar", "tnagar", "anna nagar", "annanagar", "velachery", "tambaram"]):
        return {"intent": "reschedule" if has_active_appt and current_intent == "reschedule" else "book"}
    if any(doc in lower for doc in [
        "arjun", "ashwin", "lakshmi", "rajesh", "sandeep", "harish",
        "priya", "shalini", "nithya", "karthik", "suresh", "meera",
        "divya", "vivek", "deepa", "ananya"
    ]):
        return {"intent": "reschedule" if has_active_appt and current_intent == "reschedule" else "book"}
    from src.control.agents.tools.slot_tools import parse_date_query_to_range
    dt_start, _ = parse_date_query_to_range(user_speech)
    if dt_start is not None:
        curr = state.get("intent")
        if curr in ("identity", "greet", None):
            curr = state.get("pending_intent") or ("reschedule" if has_active_appt else "book")
        return {"intent": curr}
    from src.control.agents.nodes.booking_helpers import _extract_time_of_day
    if _extract_time_of_day(user_speech) is not None:
        curr = state.get("intent")
        if curr in ("identity", "greet", None):
            curr = state.get("pending_intent") or ("reschedule" if has_active_appt else "book")
        return {"intent": curr}
    has_active_appt = bool(state.get("active_appointment_id") or state.get("active_appointment_details"))

    if any(w in lower for w in ["alternative slot", "another slot", "other slot", "alternative slots", "other slots", "different slot", "different slots"]):
        is_reschedule_context = has_active_appt and (
            current_intent == "reschedule" or bool(state.get("target_slot_id"))
        )
        return {"intent": "reschedule" if is_reschedule_context else "book"}

    # Fast path 1: If slot was offered and patient is responding (confirming, asking alternative slot, location, etc.)
    if state.get("target_slot_id"):
        if current_intent == "cancel":
            return {"intent": "cancel"}
        if current_intent == "reschedule":
            return {"intent": "reschedule"}
        return {"intent": "book"}

    # Fast path 2: Direct keyword patterns (0ms latency, eliminates Twilio timeout risks)
    if has_active_appt and any(w in lower for w in ["reschedule", "change appointment", "postpone", "move appointment", "reschedule appointment"]):
        return {"intent": "reschedule"}
    if any(w in lower for w in [
        "different time", "different day", "another time", "another day", "change time",
        "change my date", "change date", "new date", "alternative date", "alternative dates",
        "other dates", "another date", "change slot", "prefer", "preferred",
    ]):
        return {"intent": "reschedule" if (has_active_appt and current_intent == "reschedule") else "book"}
    if any(w in lower for w in ["cancel appointment", "drop appointment", "delete appointment", "cancel my appointment", "don't want the appointment"]):
        return {"intent": "cancel"}
    if any(w in lower for w in ["operator", "human", "representative", "front desk", "speak to receptionist", "speak to someone", "transfer me"]):
        return {"intent": "handoff"}
    # Medical advice check according to clinical protocol (transfer to triage nurse / front desk)
    if any(w in lower for w in ["prescribe", "what medicine", "which tablet", "medical diagnosis", "diagnose me"]):
        return {
            "intent": "handoff",
            "handoff_required": True,
            "handoff_reason": "Medical advice request",
            "latest_agent_speech": "I cannot provide medical advice. Let me transfer you to our triage nurse and front desk team right away.",
        }
    # Location and branch inquiries fast path
    if any(w in lower for w in ["location", "locations", "where are you", "where is", "address", "branch", "branches"]):
        return {"intent": "book"}
    # Patient reiteration
    if any(w in lower for w in ["i already said", "already told", "i said", "like i said", "as i said"]):
        return {"intent": "book"}
    # Booking & symptoms fast path
    if any(w in lower for w in [
        "book", "appointment", "doctor", "doc", "physician", "consult", "consultation", "see a doctor", "assist", "stomach",
        "pain", "belly", "abdominal", "fever", "cold", "cough", "headache", "chest", "heart", "skin", "rash",
        "orthopedic", "orthopaedic", "orthopedics", "orthopaedics",
        "shoulder", "knee", "back", "joint", "bone", "muscle", "fracture",
        "ankle", "wrist", "elbow", "hip", "leg", "arm", "foot", "neck",
        "spine", "arthritis", "sprain", "strain", "ligament", "tendon",
        "stiffness", "swelling", "sports injury", "sports injuries",
        "throat", "ear", "infection", "sick", "unwell", "ill", "visit"
    ]):
        return {"intent": "book"}


    # Fallback to Gemini 2.0 Flash for complex/ambiguous phrasing
    gemini = GeminiService()
    prompt = INTENT_DETECTION_PROMPT.format(user_speech=user_speech)

    try:
        raw_response = await gemini.generate_content(prompt, temperature=0.0)
        cleaned = raw_response.strip().upper()
        if "BOOK" in cleaned:
            intent = "book"
        elif "RESCHEDULE" in cleaned:
            intent = "reschedule"
        elif "CANCEL" in cleaned:
            intent = "cancel"
        elif "FAQ" in cleaned:
            intent = "faq"
        elif "HANDOFF" in cleaned:
            intent = "handoff"
        elif "CLOSE" in cleaned:
            intent = "close"
        else:
            intent = "unknown"
    except Exception as e:
        logger.error(f"Intent detection failed: {e}")
        # Rule-based fallback
        lower_speech = user_speech.lower()
        if any(w in lower_speech for w in ["thank", "thanks", "bye", "goodbye", "that's all", "that is all"]):
            intent = "close"
        elif any(w in lower_speech for w in ["reschedule", "change", "postpone", "move"]):
            intent = "reschedule"
        elif any(w in lower_speech for w in ["cancel", "drop"]):
            intent = "cancel"
        elif any(w in lower_speech for w in ["book", "new", "schedule", "appointment", "see a doctor"]):
            intent = "book"
        elif any(w in lower_speech for w in ["operator", "human", "representative", "front desk", "speak to someone"]):
            intent = "handoff"
        else:
            intent = "unknown"

    if intent in ("identity", "greet", None) and state.get("is_verified"):
        has_active = bool(state.get("active_appointment_id") or state.get("active_appointment_details"))
        intent = "reschedule" if has_active else (state.get("pending_intent") or "book")

    return {"intent": intent}
